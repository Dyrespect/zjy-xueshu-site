"""给客人发话（交付这一块自己发的：到期前提醒）。

设计第 4.3 节：发话先 `customer.memory(pick_session)` 选会话，再交入口节点（模块 D 的 entry.wecom / entry.webchat，
`OutboundMessage{purpose:"delivery", dedupe_key}`）。模块 D 还没做完：这两个节点没登记时，退回订单中枢的待发
（service.create_outbox → 发件员发）。同一件事不发两遍：dedupe_key 记在事件 delivery.sent 里。
发布水印版、放出最终版那两句话由订单中枢的 publish_preview / release_final 发（契约第六节），不在这里。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.events import Event, record_event
from app.core.nodes import NodeCall, has_handler, run_node
from app.intake import service
from app.intake.models import Customer, Order
from app.intake.service import Ctx

ENTRY_NODE = {"wecom": "entry.wecom", "web": "entry.webchat"}


def already_sent(db: Session, order_id: int, dedupe_key: str) -> bool:
    rows = db.scalars(select(Event).where(Event.type == "delivery.sent", Event.subject == f"order:{order_id}"))
    return any((e.content or {}).get("dedupe_key") == dedupe_key for e in rows)


def send_text(db: Session, ctx: Ctx, o: Order, text: str, *, dedupe_key: str, by: str) -> dict[str, Any]:
    """发一句话给这单的客人。返回 {status: sent|queued|deferred|skipped|no_customer, via}。"""
    if already_sent(db, o.id, dedupe_key):
        return {"status": "skipped", "via": ""}
    if o.customer_id is None:
        return {"status": "no_customer", "via": ""}
    result: dict[str, Any]
    session_id = o.customer_id
    if has_handler("customer.memory"):
        picked = run_node("customer.memory", NodeCall(db, ctx, by, o.id), {"action": "pick_session", "order_id": o.id})
        session_id = getattr(picked.output, "session_id", None) or o.customer_id
    customer = db.get(Customer, session_id)
    node = ENTRY_NODE.get(customer.channel if customer else "", "")
    if customer is not None and node and has_handler(node):
        res = run_node(node, NodeCall(db, ctx, by, o.id), {
            "session_id": customer.id, "purpose": "delivery", "kind": "text", "text": text,
            "fallback_url": ctx.delivery_url(o), "dedupe_key": dedupe_key})
        result = {"status": getattr(res.output, "status", res.exit), "via": node}
    else:
        if customer is None:
            return {"status": "no_customer", "via": ""}
        ob = service.create_outbox(db, ctx, customer, o, text=text, category="交付", author="system",
                                   reasons=[f"交付提醒（{dedupe_key}）"])
        result = {"status": "queued", "via": "outbox", "outbox_id": ob.id}
    record_event(db, "delivery.sent", f"order:{o.id}", {"dedupe_key": dedupe_key, "by": by, **result, "text": text[:300]})
    return result
