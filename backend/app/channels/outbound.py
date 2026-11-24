"""入口出站的公共部分：一句话（OutboundMessage）→ 订单中枢的待发（create_outbox）。

同一件事不发两遍：dedupe_key 记在待发的 reasons 第一条（「dedupe:claim:12」），同一会话已经有就不再排。
真的发出去由发件员（dispatch.py）做：网页直接标已发；微信客服发前查窗口、会话状态。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.channels.entry_types import PURPOSE_CATEGORY, OutboundMessage, SendResult
from app.core.nodes import NodeCall
from app.intake import service
from app.intake.models import Customer, Order, Outbox


def already_sent(db: Session, customer_id: int, dedupe_key: str) -> Outbox | None:
    if not dedupe_key:
        return None
    tag = f"dedupe:{dedupe_key}"
    rows = db.scalars(select(Outbox).where(Outbox.customer_id == customer_id, Outbox.status != "rejected")
                      .order_by(Outbox.id.desc()).limit(200))
    return next((ob for ob in rows if (ob.reasons or [])[:1] == [tag]), None)


def queue(call: NodeCall, data: OutboundMessage, *, send_now: bool) -> SendResult:
    db = call.db
    c = db.get(Customer, data.session_id)
    if c is None:
        return SendResult(status="failed", detail="没有这个会话")
    dup = already_sent(db, c.id, data.dedupe_key)
    if dup is not None:
        return SendResult(status="duplicate", outbox_id=None, detail=f"同一件事发过了（待发 {dup.id}）")
    order = db.get(Order, data.order_id) if data.order_id else service.current_order(db, c)
    category = data.category or PURPOSE_CATEGORY.get(data.purpose, "一般回复")
    reasons = ([f"dedupe:{data.dedupe_key}"] if data.dedupe_key else []) + [f"入口固定话术（{data.purpose}）"]
    ob = service.create_outbox(db, call.ctx, c, order, text=data.text, kind=data.kind, file_id=data.file_id,
                               category=category, author="system", reasons=reasons)
    if ob.status == "approved" and send_now:
        service.mark_sent(db, ob)
        return SendResult(status="sent", outbox_id=ob.id)
    return SendResult(status="queued", outbox_id=ob.id, detail=f"待发（{ob.status}）")
