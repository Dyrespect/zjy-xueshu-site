"""intake 模块的接口入口（挂在 /api/intake）。

客户从渠道（channels：网页聊天、微信客服）进来，交付页在 delivery，后台的操作在 admin/intake_router.py。
这里放两样：
1. 启动：建运行时、把后台工人登记到底座调度器（网站进程或 python -m app.worker 跑，见 intake/worker.py）。
2. 给制作方（Claude，在工厂里做 PPT）用的接口 /api/intake/production（PRD v2 第六节）。命令行是
   scripts/production_cli.py。鉴权：请求头 `Authorization: Bearer <PRODUCTION_TOKEN>`（单独一个令牌，
   不用后台密码和 cookie）；没配令牌 → 503；令牌不对 → 401，同一 IP 连错 5 次 10 分钟内不让再试。

- `GET  /production/orders?which=open|all`        待开、在做、改稿中的单（有开单说明的）
- `GET  /production/orders/{id}`                  一单：开单说明 + 整条会话 + 材料在 inbox 哪 + 成品
- `POST /production/orders/{id}/read`             看过了（发给制作方的消息记已读）
- `GET  /production/messages?unread=true`         发给制作方的新消息（开单说明、补充要求、问题、回答、改稿单）
- `POST /production/orders/{id}/messages`         制作方发一条 {kind: 进度|问题|回答, text} → 机器人去转告客户
- `POST /production/orders/{id}/package`          交一版成品包（multipart：files 最终版 pptx、讲稿……；pages 每页整页图）
                                                   → 出水印图、发布给客户看；已完成之后交的直接放最终版
- `POST /production/orders/{id}/deliverables`     停用（410）：旧接口交了就把 pptx 直接发给客户，绕过水印和已完成关口
- `POST /production/orders/{id}/start` | `/done`  开始做 / 做好了

这个文件导入 app.intake.nodes：启动时把接单这一块的节点登记进注册表（顶层设计第十八节）。
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import access
from app.core.deps import get_db
from app.intake import nodes as _nodes  # noqa: F401 登记接单这一块的节点
from app.intake import production
from app.intake.auth import require_production_token
from app.intake.models import FileRecord, Order, ProductionMessage
from app.intake.runtime import get_runtime
from app.intake.worker import register as register_worker

router = APIRouter()

MAX_DELIVERABLE = 200 * 1024 * 1024
MAX_PAGES = 120


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    rt = get_runtime(app)
    if rt.ctx.settings.INTAKE_WORKER:
        register_worker(app.state.scheduler, rt)
    yield


# ---------------------------------------------------------------- 制作方接口

maker = APIRouter(prefix="/production", tags=["production"], dependencies=[Depends(access.service), Depends(require_production_token)])


def _order(db: Session, oid: int) -> Order:
    o = db.get(Order, oid)
    if o is None:
        raise HTTPException(404, detail="没有这单")
    return o


@maker.get("/orders")
def maker_orders(which: Literal["open", "all"] = "open", db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    return production.list_orders(db, which)


@maker.get("/orders/{oid}")
def maker_order(oid: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    return production.order_detail(db, _order(db, oid))


@maker.post("/orders/{oid}/read")
def maker_read(oid: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    n = production.mark_read(db, _order(db, oid))
    db.commit()
    return {"read": n}


@maker.get("/messages")
def maker_messages(unread: bool = True, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    q = select(ProductionMessage).where(ProductionMessage.direction == "to_maker")
    if unread:
        q = q.where(ProductionMessage.read_at.is_(None))
    msgs = list(db.scalars(q.order_by(ProductionMessage.id).limit(200)))
    fids = {i for m in msgs for i in (m.file_ids or [])}
    files = {f.id: f for f in db.scalars(select(FileRecord).where(FileRecord.id.in_(fids)))} if fids else {}
    return [{**production.message_out(m, files), "order_id": m.order_id} for m in msgs]


class SayIn(BaseModel):
    kind: Literal["进度", "问题", "回答"] = "进度"
    text: str = Field(min_length=1, max_length=4000)


@maker.post("/orders/{oid}/messages")
def maker_say(oid: int, body: SayIn, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    o = _order(db, oid)
    try:
        m = production.maker_says(db, get_runtime(request.app).ctx, o, body.kind, body.text)
    except ValueError as e:
        raise HTTPException(409, detail=str(e)) from e
    db.commit()
    return production.message_out(m, {})


async def _read_upload(up: UploadFile) -> tuple[str, bytes, str]:
    data = bytearray()
    while chunk := await up.read(1024 * 1024):
        data.extend(chunk)
        if len(data) > MAX_DELIVERABLE:
            raise HTTPException(413, detail="单个文件不超过 200MB")
    return Path(up.filename or "成品").name, bytes(data), up.content_type or ""


_PAGE_NO = re.compile(r"(\d+)(?!.*\d)")


@maker.post("/orders/{oid}/package")
async def maker_package(oid: int, request: Request, files: list[UploadFile] = File(default=[]),
                        pages: list[UploadFile] = File(default=[]), note: str = Form(""),
                        db: Session = Depends(get_db)) -> dict[str, Any]:
    """交一版成品包：最终版（pptx、讲稿……，锁在库里，确认收货后才发）+ 每页整页图（文件名带页码，如 page-05.png）。"""
    o = _order(db, oid)
    if len(pages) > MAX_PAGES:
        raise HTTPException(413, detail=f"整页图一次不超过 {MAX_PAGES} 张")
    got = [await _read_upload(up) for up in files[:10]]
    imgs = []
    for i, up in enumerate(pages, start=1):
        name, data, ctype = await _read_upload(up)
        m = _PAGE_NO.search(Path(name).stem)
        imgs.append((int(m.group(1)) if m else i, name, data, ctype))
    try:
        out = production.maker_package(db, get_runtime(request.app).ctx, o, got, sorted(imgs), note=note)
    except ValueError as e:
        db.rollback()
        raise HTTPException(409, detail=str(e)) from e
    db.commit()
    return out


@maker.post("/orders/{oid}/deliverables")
def maker_deliver_gone(oid: int) -> None:
    raise HTTPException(410, detail="这个接口停用了：交成品改用 POST /api/intake/production/orders/{id}/package"
                                    "（最终版 + 每页整页图，先出水印版，确认收货后才发最终版）；命令行用 production_cli.py deliver")


@maker.post("/orders/{oid}/{what}")
def maker_mark(oid: int, what: Literal["start", "done"], db: Session = Depends(get_db)) -> dict[str, Any]:
    o = _order(db, oid)
    try:
        production.maker_mark(db, o, what)
    except ValueError as e:
        raise HTTPException(409, detail=str(e)) from e
    db.commit()
    return production.order_brief(db, o)


router.include_router(maker)
