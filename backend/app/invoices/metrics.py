"""开票的评估数据（Edison 11-14：每个项目都要有评估机制；周报模块 H 以后来取）。

- 开票申请率 = 这段时间完成的（能自己申请的渠道的）单里，申请了发票的单数 ÷ 完成的单数。
  完成前在下单页、交付页预填的也算申请；后来撤回、被驳回的也算（看的是「有多少人要发票」）。
- 平均出票用时 = 这段时间开出的发票，从进「待开票」到标记已开的小时数（平均、中位、最长）。草稿等订单完成的时间不算。
- 另给：现在待开票几张、等得最久的一张等了多久；待发的通知几条。
全从库里的表算（订单的 completed_at、invoice_requests 的时间戳），事件 invoice.* 留着做回放。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from statistics import median
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.intake.models import Order
from app.invoices.config import load_config
from app.invoices.models import InvoiceNotice, InvoiceRequest


def weekly(db: Session, *, days: int = 7, now: datetime | None = None) -> dict[str, Any]:
    now = now or utcnow()
    start = now - timedelta(days=days)
    cfg = load_config(db)
    platforms = cfg.eligible_platforms or ["web"]
    done_ids = set(db.scalars(select(Order.id).where(Order.completed_at >= start, Order.completed_at < now,
                                                       Order.platform.in_(platforms))))
    asked = set(db.scalars(select(InvoiceRequest.order_id).where(InvoiceRequest.order_id.in_(done_ids)))) if done_ids else set()
    issued = list(db.scalars(select(InvoiceRequest).where(InvoiceRequest.issued_at >= start, InvoiceRequest.issued_at < now)))
    hours = [round((i.issued_at - i.requested_at).total_seconds() / 3600, 2) for i in issued if i.requested_at and i.issued_at]
    pending = list(db.scalars(select(InvoiceRequest).where(InvoiceRequest.flow_step == "pending")))
    oldest = max(((now - i.requested_at).total_seconds() / 3600 for i in pending if i.requested_at), default=None)
    notices = db.scalar(select(func.count()).select_from(InvoiceNotice).where(InvoiceNotice.status == "pending")) or 0
    return {
        "days": days, "from": start, "to": now, "platforms": platforms,
        "completed_orders": len(done_ids), "orders_with_request": len(asked),
        "request_rate": round(len(asked) / len(done_ids), 3) if done_ids else None,
        "issued": len(issued), "issue_hours_avg": round(sum(hours) / len(hours), 2) if hours else None,
        "issue_hours_median": round(median(hours), 2) if hours else None, "issue_hours_max": max(hours) if hours else None,
        "pending_now": len(pending), "pending_oldest_hours": round(oldest, 1) if oldest is not None else None,
        "notices_pending": notices,
    }
