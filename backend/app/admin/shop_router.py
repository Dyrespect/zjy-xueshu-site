"""后台：自有网页收款（/api/admin/shop，要登录；只有 Edison 用）。

- GET  status        付款方式开没开、缺哪些 .env 配置、假网关、定时任务、自动确认几天
- GET  checkouts     待付款单 / 已付 / 已关 / 退款（最近 200 条）
- POST refunds       退款（channel.web op=refund）：只限自有网页的单，金额 ≤ 实付 − 已退；退全款后订单作废、码作废
- GET  due           该看一眼：付了没发码的、通知验签或金额不对的、退款卡住的
- POST tick          现在跑一轮定时任务（超时自动确认、关过期单、查退款）
退款只在这里，对外接口没有退款（设计第九节检查 8）。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.deps import get_db
from app.core.nodes import NodeCall, run_node
from app.shop import service
from app.shop.adapter import fen_to_amount
from app.shop.models import CHECKOUT_STATUS_LABELS, REFUND_STATUS_LABELS, ShopCheckout, ShopNotification, ShopRefund
from app.shop.models_io import WebRefund
from app.shop.router import run_tick
from app.shop.runtime import ShopCtx, shop_ctx_dep
from app.shop.settings import METHOD_LABELS

router = APIRouter(prefix="/shop", tags=["admin"])


@router.get("/status")
def status(db: Session = Depends(get_db), ctx: ShopCtx = Depends(shop_ctx_dep)) -> dict[str, Any]:
    s = ctx.shop.settings
    cat = run_node("sku.catalog", NodeCall(db, ctx, "edison"), {}).output
    configured = s.methods()
    rows = []
    for method, label in METHOD_LABELS.items():
        node = configured.get(method, "")
        missing: list[str] = []
        if node == "pay.wechat":
            missing = s.wechat_missing()
        elif node == "pay.alipay":
            missing = s.alipay_missing()
        if method == "wechat_jsapi" and node and not service.oauth_ready(ctx.shop, node):
            missing = [*missing, "WECHAT_MP_APPSECRET_FILE（或 WECHAT_MP_APPSECRET）"]
        ready = bool(node) and not missing and (node != "pay.fake" or s.SHOP_FAKE_PAY)
        rows.append({"method": method, "label": label, "node": node, "missing": missing, "ready": ready,
                     "where": {"wechat_native": "电脑", "wechat_jsapi": "微信里", "wechat_h5": "手机浏览器",
                               "alipay_page": "电脑", "alipay_wap": "手机浏览器"}[method]})
    return {"enabled": s.SHOP_ENABLED, "fake": s.SHOP_FAKE_PAY, "methods": rows, "timer": s.SHOP_TIMER_ENABLED,
            "timer_minutes": max(30, s.SHOP_TIMER_INTERVAL_SEC) // 60, "auto_confirm_days": cat.auto_confirm_days,
            "auto_confirm_platforms": s.auto_confirm_platforms(), "checkout_ttl_min": s.SHOP_CHECKOUT_TTL_MIN,
            "redeem_url": s.SHOP_REDEEM_URL}


def _checkout_row(c: ShopCheckout, refunds: list[ShopRefund]) -> dict[str, Any]:
    q = c.quote or {}
    return {"id": c.id, "out_trade_no": c.out_trade_no, "status": c.status, "status_label": CHECKOUT_STATUS_LABELS.get(c.status, c.status),
            "sku_name": q.get("sku_name", c.sku), "addons": [a.get("name") for a in q.get("addons", [])],
            "amount": fen_to_amount(c.amount_fen), "amount_fen": c.amount_fen, "paid_fen": c.paid_fen,
            "refunded_fen": c.refunded_fen, "method": METHOD_LABELS.get(c.method, c.method), "pay_node": c.pay_node,
            "order_id": c.order_id, "code": c.code, "create_exit": c.create_exit, "ua_kind": c.ua_kind, "source": c.source,
            "created_at": c.created_at, "paid_at": c.paid_at,
            "refunds": [{"id": r.id, "amount": fen_to_amount(r.amount_fen), "status": r.status,
                         "status_label": REFUND_STATUS_LABELS.get(r.status, r.status), "reason": r.reason, "scope": r.scope,
                         "void_result": r.void_result, "created_at": r.created_at} for r in refunds]}


@router.get("/checkouts")
def checkouts(status: str = "", db: Session = Depends(get_db)) -> dict[str, Any]:
    q = select(ShopCheckout).order_by(ShopCheckout.id.desc()).limit(200)
    if status == "paid":
        q = q.where(ShopCheckout.status.in_(("paid", "part_refunded", "refunding", "refunded")))
    elif status:
        q = q.where(ShopCheckout.status == status)
    rows = list(db.scalars(q))
    refunds: dict[int, list[ShopRefund]] = {}
    if rows:
        for r in db.scalars(select(ShopRefund).where(ShopRefund.checkout_id.in_([c.id for c in rows])).order_by(ShopRefund.id)):
            refunds.setdefault(r.checkout_id, []).append(r)
    return {"rows": [_checkout_row(c, refunds.get(c.id, [])) for c in rows]}


class RefundIn(BaseModel):
    order_id: int
    amount_fen: int = Field(ge=1)
    scope: str = Field(default="full", max_length=32)
    reason: str = Field(default="", max_length=200)


@router.post("/refunds")
def refunds(body: RefundIn, db: Session = Depends(get_db), ctx: ShopCtx = Depends(shop_ctx_dep)) -> dict[str, Any]:
    res = run_node("channel.web", NodeCall(db, ctx, "edison", body.order_id), WebRefund(**body.model_dump()))
    db.commit()
    if res.exit not in ("ok", "waiting"):
        raise HTTPException(409, detail=res.detail or "退不了")
    return {"exit": res.exit, "message": "退款成功" if res.exit == "ok" else "退款在处理，稍后自动再查", "detail": res.detail}


@router.get("/due")
def due(db: Session = Depends(get_db)) -> dict[str, Any]:
    """该看一眼（自有网页这一半；平台那一半在 /api/admin/platforms/due）。"""
    week = utcnow() - timedelta(days=7)
    items: list[dict[str, Any]] = []
    for c in db.scalars(select(ShopCheckout).where(ShopCheckout.status.in_(("paid", "part_refunded")),
                                                   or_(ShopCheckout.create_exit == "", ShopCheckout.create_exit.not_in(("created", "exists"))))):
        items.append({"kind": "paid_no_code", "level": "high", "title": f"自有网页单 {c.out_trade_no} 付了 {fen_to_amount(c.paid_fen)} 元，没发码",
                      "detail": "付款人退款作废太多次" if c.create_exit == "blocked" else "建单失败", "order_id": c.order_id,
                      "action": "退款", "at": c.paid_at})
    for n in db.scalars(select(ShopNotification).where(ShopNotification.created_at >= week, or_(
            ShopNotification.verified.is_(False), ShopNotification.result.in_(("invalid", "no_checkout")))).order_by(ShopNotification.id.desc()).limit(20)):
        items.append({"kind": "bad_notify", "level": "mid", "title": f"一条{('验签不过' if not n.verified else '对不上')}的支付通知（{n.pay_node}）",
                      "detail": (n.error or n.result)[:120], "order_id": None, "action": "看一眼", "at": n.created_at})
    stuck = utcnow() - timedelta(minutes=30)
    for r in db.scalars(select(ShopRefund).where(or_(ShopRefund.status == "abnormal",
                                                     (ShopRefund.status == "processing") & (ShopRefund.created_at <= stuck)))):
        items.append({"kind": "refund_stuck", "level": "high", "title": f"退款 {fen_to_amount(r.amount_fen)} 元{REFUND_STATUS_LABELS.get(r.status, r.status)}",
                      "detail": r.reason, "order_id": r.order_id, "action": "去网关后台核对", "at": r.created_at})
    return {"items": items}


class TickBody(BaseModel):
    now: datetime | None = None


@router.post("/tick")
def tick(body: TickBody, request: Request) -> dict[str, Any]:
    """现在跑一轮定时任务。now 只给本机走查用（假装过了几天）；生产上不传。"""
    if body.now is not None and request.app.state.settings.APP_ENV == "prod":
        raise HTTPException(400, detail="生产上不能指定时间")
    return run_tick(request.app, body.now)
