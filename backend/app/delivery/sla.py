"""时限看门（deliver.sla 的实现）：从开工算，承诺几小时内交第一版水印版（订单上的 due_hours）。

「加急 3 小时」怎么算（定价方案、交付与退款方案原话：「从开工到交出水印版」）：开工 = 订单进「制作中」那一刻
（started_at，开工交接时写）；交出 = 第 1 版水印版发布（版本表第 1 版的 published_at）。不含客人看和改的时间。设计 4.7 节。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.events import Event
from app.delivery.models import DeliveryVersion
from app.intake.models import Order


@dataclass
class SlaFacts:
    due_at: datetime | None
    first_published_at: datetime | None
    used_ratio: float
    state: str  # ok | warn | late


def first_published_at(db: Session, o: Order) -> datetime | None:
    v = db.scalar(select(DeliveryVersion).where(DeliveryVersion.order_id == o.id, DeliveryVersion.round == 1))
    if v is not None and v.published_at is not None:
        return v.published_at
    return o.delivered_at if o.delivery_round >= 1 and v is None else None


def facts(db: Session, o: Order, *, warn_ratio: float, now: datetime | None = None) -> SlaFacts:
    if o.started_at is None or not o.due_hours:
        return SlaFacts(None, None, 0.0, "ok")
    due_at = o.started_at + timedelta(hours=o.due_hours)
    first = first_published_at(db, o)
    end = first or now or utcnow()
    used = max(0.0, (end - o.started_at).total_seconds() / (o.due_hours * 3600))
    if used >= 1:
        state = "late"
    elif first is None and used >= warn_ratio:
        state = "warn"
    else:
        state = "ok"
    return SlaFacts(due_at, first, round(used, 3), state)


def already(db: Session, order_id: int, event_type: str) -> bool:
    return bool(db.scalar(select(func.count()).select_from(Event).where(Event.type == event_type, Event.subject == f"order:{order_id}")))


def watching(db: Session) -> list[int]:
    """在做第一版的单：制作中（含出图、发布这两步）、开工了、有时限、还没交过。只读。"""
    return list(db.scalars(select(Order.id).where(Order.stage == "making", Order.started_at.is_not(None),
                                                  Order.due_hours.is_not(None), Order.delivery_round == 0)))
