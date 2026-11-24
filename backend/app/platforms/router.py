"""平台渠道的对外接口（挂在 /api/platforms）。路由里不写判断，全转给渠道节点。

- GET  /claim/{product_token}         固定链接页：这个商品是什么（买家打开 /x/<口令>）
- POST /claim                         买家填平台订单号 → 待核对（同一 IP 每小时最多 10 次）
- GET  /claim/status/{claim_token}    买家页面轮询：核对了没、码
- POST /{platform}/push               以后平台推送、发货工具回写；人工渠道现在一律不收
录单、核对、平台信号只在后台（/api/admin/platforms）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import access
from app.core.deps import client_ip, get_db, get_ratelimiter
from app.core.nodes import NodeCall, has_handler, run_node
from app.intake import pricing
from app.intake.runtime import get_ctx
from app.platforms import nodes as _nodes  # noqa: F401  登记本模块的节点
from app.platforms import profiles, service
from app.platforms.models import PlatformsProduct
from app.platforms.models_io import PlatformInbound

CLAIM_LIMIT_PER_HOUR = 10


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"


router = APIRouter(dependencies=[Depends(_no_store)])


class ProductView(BaseModel):
    ok: bool
    platform: str = ""
    platform_label: str = ""
    title: str = ""
    sku_name: str = ""
    why: str = ""


class ClaimBody(BaseModel):
    product_token: str = Field(min_length=4, max_length=24)
    platform_order_id: str = Field(min_length=1, max_length=64)


class ClaimView(BaseModel):
    status: str
    claim_token: str = ""
    code: str = ""
    redeem_url: str = ""
    message: str = ""


def _product(db: Session, token: str) -> tuple[PlatformsProduct | None, dict[str, Any] | None]:
    prod = db.scalar(select(PlatformsProduct).where(PlatformsProduct.token == token, PlatformsProduct.active.is_(True)))
    prof = profiles.get(db, prod.platform) if prod is not None else None
    if prod is None or prof is None or not prof.get("enabled") or prof["mode"] != "verify_then_create":
        return None, None
    return prod, prof


@router.get("/claim/{product_token}", dependencies=[Depends(access.by_token)], response_model=ProductView)
def claim_product(product_token: str, db: Session = Depends(get_db)) -> ProductView:
    prod, prof = _product(db, product_token)
    if prod is None or prof is None:
        return ProductView(ok=False, why="这个链接现在用不了")
    p = pricing.parse_sku(prod.sku)
    cat = run_node("sku.catalog", NodeCall(db, None, "customer"), {}).output
    tier = next((t.name for t in cat.tiers if p is not None and t.key == p.tier), "")
    band = next((b["name"] for b in cat.bands if p is not None and b["key"] == p.band), "")
    addon = next((a["name"] for a in cat.addons if p is not None and a["key"] == p.addon), "")
    sku_name = f"{tier} · {band}" if tier and band else (f"加购：{addon}" if addon else prod.sku)
    return ProductView(ok=True, platform=prod.platform, platform_label=str(prof.get("label") or ""), title=prod.title,
                       sku_name=sku_name)


def _hit(request: Request, ip: str) -> None:
    if not get_ratelimiter(request).hit("platforms.claim", ip, limit=CLAIM_LIMIT_PER_HOUR, window=3600):
        raise HTTPException(429, detail="提交太频繁了，过一会儿再试")


@router.post("/claim", dependencies=[Depends(access.by_token)], response_model=ClaimView)
def claim(body: ClaimBody, request: Request, db: Session = Depends(get_db)) -> ClaimView:
    ip = client_ip(request)
    _hit(request, ip)
    prod, prof = _product(db, body.product_token)
    if prod is None:
        raise HTTPException(404, detail="这个链接现在用不了")
    node = profiles.PLATFORM_NODES[prod.platform]
    res = run_node(node, NodeCall(db, get_ctx(request), "customer"), PlatformInbound(
        source="buyer_claim", form={"product_token": body.product_token, "platform_order_id": body.platform_order_id}, client_ip=ip))
    if res.exit == "invalid":
        db.rollback()
        raise HTTPException(400, detail=res.detail)
    db.commit()
    out = res.output
    if res.exit == "exists":
        return ClaimView(status="exists", message=out.why if out else "这个订单号已经提交过了")
    return ClaimView(status="pending", claim_token=out.claim_token if out else "",
                     message="收到了，正在核对订单号（一般几分钟），这个页面会自己刷出激活码，别关")


@router.get("/claim/status/{claim_token}", dependencies=[Depends(access.by_token)], response_model=ClaimView)
def claim_status(claim_token: str, db: Session = Depends(get_db)) -> ClaimView:
    st = service.claim_status(db, claim_token)
    if st is None:
        raise HTTPException(404, detail="没有这条记录")
    msg = {"pending": "正在核对订单号，核对好了这里自己刷出激活码", "rejected": "订单号没核对上：回去看一下订单号有没有填错，再提交一次",
           "problem": "订单号核对上了，但激活码没能发出来，我们会尽快在平台上联系你", "ok": ""}[st["status"]]
    return ClaimView(status=st["status"], claim_token=claim_token, code=st["code"], redeem_url=st["redeem_url"], message=msg)


async def _raw_body(request: Request) -> bytes:
    return await request.body()


@router.post("/{platform}/push", dependencies=[Depends(access.webhook)])
def push(platform: str, request: Request, raw: bytes = Depends(_raw_body), db: Session = Depends(get_db)) -> Response:
    node = profiles.PLATFORM_NODES.get(platform)
    if node is None:
        raise HTTPException(404, detail="Not Found")
    if not has_handler(node):
        raise HTTPException(404, detail="这个渠道还没接")
    res = run_node(node, NodeCall(db, get_ctx(request), f"push:{platform}"),
                   PlatformInbound(source="push", headers=dict(request.headers.items()), raw=raw))
    db.commit()
    if res.exit == "invalid":
        raise HTTPException(404, detail="这个渠道现在不收推送")
    ack = res.output.ack if res.output else ""
    return JSONResponse(ack) if isinstance(ack, dict) else PlainTextResponse(str(ack or "success"))
