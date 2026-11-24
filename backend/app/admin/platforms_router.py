"""后台：平台渠道（/api/admin/platforms，要登录；只有 Edison 用）。小红书、闲鱼第一期人工录单。

- GET  overview                   渠道档案（收单方式、开没开）、商品对照、能卖的货号
- PUT  profiles/{platform}        切收单方式（小红书：manual_paste 录单贴文案 / fixed_link 固定链接 + 核对）、开关渠道
- POST products、PATCH products/{id}   登记平台商品 → 货号、标价、上下架；固定链接方式下每个商品一个 /x/<口令>
- POST manual-entry               录一单 → 返回要贴到平台的发货文案
- POST verify                     核对买家在固定链接页填的订单号
- POST {platform}/signal          平台已完成 / 申请退款 / 已退款 / 退款关闭
- POST inbox/{id}/pasted          发货文案贴好了
- GET  inbox                      录过的单（带订单现在到哪一步）
- GET  due                        该看一眼（平台这一半 + 自有网页那一半）
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin.shop_router import due as shop_due
from app.core.db import utcnow
from app.core.deps import get_db
from app.core.nodes import NodeCall, run_node
from app.intake import pricing
from app.intake.config_store import load_config
from app.intake.models import STAGE_LABELS, Order
from app.intake.runtime import get_ctx
from app.platforms import profiles, service
from app.platforms.models import INBOX_EXIT_LABELS, PlatformsInbox, PlatformsProduct
from app.platforms.models_io import PlatformInbound, PlatformSignalIn, PlatformVerify

router = APIRouter(prefix="/platforms", tags=["admin"])


def _node(platform: str) -> str:
    node = profiles.PLATFORM_NODES.get(platform)
    if node is None:
        raise HTTPException(404, detail="没有这个渠道")
    return node


def _product_row(p: PlatformsProduct, base: str, cfg: Any) -> dict[str, Any]:
    want = pricing.sku_price(cfg, p.sku, list(p.addons or []))
    return {"id": p.id, "platform": p.platform, "product_ref": p.product_ref, "title": p.title, "sku": p.sku, "addons": p.addons,
            "sku_name": pricing.sku_name(cfg, p.sku, list(p.addons or [])), "listed_price": p.listed_price,
            "price": pricing.fmt_money(want), "price_ok": _price_ok(p.listed_price, want), "token": p.token, "link": f"{base.rstrip('/')}/x/{p.token}", "active": p.active,
            "note": p.note}


def _price_ok(listed: str, want: Decimal | None) -> bool:
    """平台标价和设置价对得上（没填标价、货号不卖的不算对不上）。"""
    if not listed or want is None:
        return True
    try:
        return Decimal(listed) == want
    except InvalidOperation:
        return False


@router.get("/overview")
def overview(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    cfg = load_config(db)
    base = get_ctx(request).public_base_url
    profs = profiles.load(db)
    skus = [{"sku": s, "name": pricing.sku_name(cfg, s), "price": pricing.fmt_money(pricing.sku_price(cfg, s))}
            for s in pricing.sellable_skus(cfg)]
    return {
        "profiles": [{"platform": k, **{f: v.get(f) for f in ("label", "adapter", "adapters", "enabled", "mode", "delivery_template",
                                                              "allow_url", "remind_after_paid_hours", "confirm")}}
                     for k, v in profs.items() if k != "web"],
        "products": [_product_row(p, base, cfg) for p in db.scalars(select(PlatformsProduct).order_by(PlatformsProduct.id.desc()))],
        "skus": skus,
        "addons": [{"key": a.key, "name": a.name, "price": a.price} for a in cfg.addons if a.price],
    }


class ProfileIn(BaseModel):
    adapter: str = Field(min_length=1, max_length=24)
    enabled: bool = True


@router.put("/profiles/{platform}")
def put_profile(platform: str, body: ProfileIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        p = profiles.save(db, platform, adapter=body.adapter, enabled=body.enabled, by="edison")
    except ValueError as e:
        raise HTTPException(400, detail=str(e)) from e
    db.commit()
    return {"platform": platform, **p}


class ProductIn(BaseModel):
    platform: Literal["xhs", "xy", "dy"]
    product_ref: str = Field(min_length=1, max_length=64)
    title: str = Field(default="", max_length=64)
    sku: str = Field(min_length=1, max_length=48)
    addons: list[str] = Field(default_factory=list)
    listed_price: str = Field(default="", max_length=16)
    note: str = Field(default="", max_length=200)


@router.post("/products")
def add_product(body: ProductIn, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        row = service.new_product(db, **body.model_dump())
    except ValueError as e:
        raise HTTPException(400, detail=str(e)) from e
    db.commit()
    return _product_row(row, get_ctx(request).public_base_url, load_config(db))


class ProductPatch(BaseModel):
    active: bool | None = None
    listed_price: str | None = Field(default=None, max_length=16)
    title: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=200)


@router.patch("/products/{pid}")
def patch_product(pid: int, body: ProductPatch, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    row = db.get(PlatformsProduct, pid)
    if row is None:
        raise HTTPException(404, detail="没有这个商品")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(row, k, v)
    db.commit()
    return _product_row(row, get_ctx(request).public_base_url, load_config(db))


class ManualEntryIn(BaseModel):
    platform: Literal["xhs", "xy", "dy"]
    platform_order_id: str = Field(min_length=3, max_length=64)
    product_id: int | None = None
    sku: str = Field(default="", max_length=48)
    addons: list[str] = Field(default_factory=list)
    paid_amount: str = Field(default="", max_length=16)
    buyer_hint: str = Field(default="", max_length=64)


@router.post("/manual-entry")
def manual_entry(body: ManualEntryIn, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    form = body.model_dump(exclude={"platform"})
    res = run_node(_node(body.platform), NodeCall(db, get_ctx(request), "edison"), PlatformInbound(source="manual", form=form))
    db.commit()
    out = res.output
    if res.exit in ("invalid", "ignored", "fail") and (out is None or not out.code):
        raise HTTPException(409, detail=res.detail or "没录成")
    return {"exit": res.exit, "detail": res.detail, "inbox_id": out.inbox_id if out else None, "order_id": out.order_id if out else None,
            "code": out.code if out else "", "text": out.text_for_edison if out else ""}


class VerifyIn(BaseModel):
    inbox_id: int
    ok: bool
    buyer_hint: str = Field(default="", max_length=64)
    note: str = Field(default="", max_length=200)


@router.post("/verify")
def verify(body: VerifyIn, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    row = db.get(PlatformsInbox, body.inbox_id)
    if row is None:
        raise HTTPException(404, detail="没有这条")
    res = run_node(_node(row.platform), NodeCall(db, get_ctx(request), "edison"), PlatformVerify(**body.model_dump()))
    db.commit()
    if res.exit in ("invalid", "fail"):
        raise HTTPException(409, detail=res.detail or "没核对成")
    return {"exit": res.exit, "detail": res.detail, "code": res.output.code if res.output else ""}


class SignalIn(BaseModel):
    platform_order_id: str = Field(min_length=1, max_length=64)
    kind: Literal["completed", "refund_requested", "refund", "refund_closed"]


@router.post("/{platform}/signal")
def signal(platform: str, body: SignalIn, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    res = run_node(_node(platform), NodeCall(db, get_ctx(request), "edison"), PlatformSignalIn(**body.model_dump()))
    db.commit()
    if res.exit != "signal_applied":
        raise HTTPException(409, detail=res.detail or "没点成")
    return {"exit": res.exit, "result": res.output.why if res.output else "", "stage": res.output.stage if res.output else ""}


@router.post("/inbox/{iid}/pasted")
def pasted(iid: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    row = db.get(PlatformsInbox, iid)
    if row is None:
        raise HTTPException(404, detail="没有这条")
    row.pasted_at = row.pasted_at or utcnow()
    db.commit()
    return {"ok": True}


@router.get("/inbox")
def inbox(platform: str = "", db: Session = Depends(get_db)) -> dict[str, Any]:
    profs = profiles.load(db)
    q = select(PlatformsInbox).order_by(PlatformsInbox.id.desc()).limit(200)
    if platform:
        q = q.where(PlatformsInbox.platform == platform)
    rows = list(db.scalars(q))
    ids = [r.order_id for r in rows if r.order_id]
    orders = {o.id: o for o in db.scalars(select(Order).where(Order.id.in_(ids)))} if ids else {}
    cfg = load_config(db)
    out = []
    for r in rows:
        o = orders.get(r.order_id) if r.order_id else None
        out.append({"id": r.id, "platform": r.platform, "platform_label": profs.get(r.platform, {}).get("label", r.platform),
                    "source": r.source, "platform_order_id": r.platform_order_id, "sku_name": pricing.sku_name(cfg, r.sku, list(r.addons or [])),
                    "paid_amount": r.paid_amount, "buyer_hint": r.buyer_hint, "exit": r.exit,
                    "exit_label": INBOX_EXIT_LABELS.get(r.exit, r.exit), "verify_status": r.verify_status, "order_id": r.order_id,
                    "code": r.code, "text": r.delivery_text, "pasted_at": r.pasted_at, "completed_at": r.completed_at,
                    "signals": r.signals or [], "error": r.error, "created_at": r.created_at,
                    "stage": o.stage if o else "", "stage_label": STAGE_LABELS.get(o.stage, o.stage) if o else "",
                    "hold": bool(o.hold_reason) if o else False})
    return {"rows": out}


@router.get("/due")
def due(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    items = service.due(NodeCall(db, get_ctx(request), "edison")) + shop_due(db)["items"]
    order = {"high": 0, "mid": 1, "low": 2}
    items.sort(key=lambda x: (order.get(x.get("level", "mid"), 1), str(x.get("at") or "")))
    return {"items": items}
