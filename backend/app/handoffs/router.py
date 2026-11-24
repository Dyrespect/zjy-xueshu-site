"""工厂来领交接包的接口（挂在 /api/handoffs），只给 Mac 上的 scripts/factory_pull.py 用。

- 鉴权：请求头 `Authorization: Bearer <FACTORY_PULL_TOKEN>`。单独一个令牌，不用后台密码和 cookie；
  没配令牌 → 503（这个口子是关着的）；令牌不对 → 401，同一 IP 连错 5 次 10 分钟内不让再试。
- `GET  /api/handoffs?status=ready`     待领的交接包（ready | claimed | all）
- `GET  /api/handoffs/{id}/package`     下载交接包 zip（响应头带 X-Package-SHA256）
- `POST /api/handoffs/{id}/claim`       回执「已领」{folder, by}；重复回执不改东西（断了重跑会再报一次）
交接包怎么打、领完怎么办见 app/intake/handoff.py。所有返回不缓存（底座 headers 中间件统一加 no-store）。
"""

from __future__ import annotations

import hmac
from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core import access
from app.core.deps import client_ip, get_db, get_ratelimiter
from app.intake.handoff import claim_handoff, drop_package, handoff_out, list_handoffs
from app.intake.models import Handoff
from app.intake.runtime import get_runtime

router = APIRouter(dependencies=[Depends(access.service)])  # 工厂凭令牌来领（规矩 24）

_MAX_FAILS = 5
_LOCK_SECONDS = 600


def require_factory_token(request: Request) -> None:
    ctx = get_runtime(request.app).ctx
    token = ctx.settings.FACTORY_PULL_TOKEN.get_secret_value()
    if not token:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="没配 FACTORY_PULL_TOKEN，领交接包的口子是关着的")
    limiter, ip = get_ratelimiter(request), client_ip(request)  # 计数在 core.ratelimit，不在进程内存
    rule = dict(limit=_MAX_FAILS, window=_LOCK_SECONDS)
    if not limiter.test("handoffs.token_fail", ip, **rule):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail="令牌错太多次，10 分钟后再试")
    auth = request.headers.get("authorization", "")
    given = auth[7:].strip() if auth[:7].lower() == "bearer " else ""
    if not given or not hmac.compare_digest(given.encode("utf-8"), token.encode("utf-8")):
        limiter.hit("handoffs.token_fail", ip, **rule)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="令牌不对")
    if limiter.used("handoffs.token_fail", ip, **rule):
        limiter.clear("handoffs.token_fail", ip, **rule)


guarded = [Depends(require_factory_token)]


def _get(db: Session, hid: int) -> Handoff:
    h = db.get(Handoff, hid)
    if h is None or h.mode != "pull":
        raise HTTPException(404, detail="没有这个交接包")
    return h


@router.get("", dependencies=guarded)
def handoffs(status: Literal["ready", "claimed", "all"] = "ready", db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    return [handoff_out(h) for h in list_handoffs(db, status)]


@router.get("/{hid}/package", dependencies=guarded)
def package(hid: int, request: Request, db: Session = Depends(get_db)) -> StreamingResponse:
    h = _get(db, hid)
    if not h.package_key:
        raise HTTPException(410, detail="这个交接包已经领过、删掉了")
    storage = get_runtime(request.app).ctx.storage
    try:
        f = storage.open(h.package_key)
    except FileNotFoundError as e:
        raise HTTPException(410, detail="交接包文件不在了") from e

    def chunks():
        with f:
            while chunk := f.read(1024 * 1024):
                yield chunk

    return StreamingResponse(chunks(), media_type="application/zip", headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(h.folder)}.zip",
        "Content-Length": str(h.package_size),
        "X-Package-SHA256": h.package_sha256,
    })


class ClaimIn(BaseModel):
    folder: str = Field(min_length=1, max_length=256)  # Mac 上实际写进的文件夹名（可能带了后缀）
    by: str = Field(default="", max_length=128)  # 哪台机器


@router.post("/{hid}/claim", dependencies=guarded)
def claim(hid: int, body: ClaimIn, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    h = _get(db, hid)
    ctx = get_runtime(request.app).ctx
    old_key = claim_handoff(db, ctx, h, folder=body.folder, by=body.by)
    db.commit()
    drop_package(ctx, old_key)
    return handoff_out(h)
