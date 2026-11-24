"""不加急的单，第一版水印版最早什么时候发给客人（Edison 11-19）。

他说的：「我们可以正常时间往后面多说两个小时……你跟他说了你要等 5 个小时……结果你一个半小时就发给他了，然后他又没有买加急，
然后他之前又买过加急，那不炸了吗？」所以：
- 对客承诺 = 正常用时 + 余量（pricing.promised_hours）；
- 不加急的单，第一版最早在「加急的承诺时长」之后才发：做完了也先压着（订单停在「把水印版发布给客人」这一步），
  到点由后台圈自动发；加急单照常做完就发；改稿后的版本不压；档位不开放加急的也不压（没有更快的可买）。
- 负责人在后台订单卡上看得到「几点自动发」，能点「现在就发」。
压着的时间记在版本表 delivery_versions.release_at；负责人点「现在就发」就把它改成现在。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.delivery.models import DeliveryVersion
from app.delivery.runtime import get_settings
from app.intake import pricing
from app.intake.config_store import BizConfig, load_config
from app.intake.models import Order


def earliest(o: Order, cfg: BizConfig) -> datetime | None:
    """按规矩算的最早可发时间；不用压的返回 None。"""
    if not get_settings().DELIVERY_HOLD_STANDARD:
        return None
    if o.delivery_round != 0 or o.rush or o.started_at is None:
        return None  # 只压第一版；加急单不压；没开工的算不出来
    t = cfg.tier(o.tier_key)
    if t is None or not t.rush:
        return None  # 这一档不卖加急：没有更快的能买，不压
    return o.started_at + timedelta(hours=pricing.promised_hours(cfg, t, rush=True))


def hold_until(db: Session, o: Order, v: DeliveryVersion | None) -> datetime | None:
    """这一版要压到几点（负责人改过就用改过的）。到点了或不用压返回 None。"""
    until = v.release_at if v is not None and v.release_at is not None else earliest(o, load_config(db))
    if until is None or utcnow() >= until:
        return None
    return until


def due(db: Session, now: datetime | None = None) -> list[tuple[int, int]]:
    """压着的、到点了的：[(订单 id, 版本 id)]。订单还停在「把水印版发布给客人」那一步才算。"""
    now = now or utcnow()
    rows = db.execute(select(DeliveryVersion.id, DeliveryVersion.order_id, DeliveryVersion.round, Order.delivery_round, Order.flow_step)
                      .join(Order, Order.id == DeliveryVersion.order_id)
                      .where(DeliveryVersion.status == "ready", DeliveryVersion.release_at.is_not(None),
                             DeliveryVersion.release_at <= now, Order.flow_step == "publish")).all()
    return [(oid, vid) for vid, oid, rnd, done, _ in rows if rnd == done + 1]


def waiting(db: Session, o: Order) -> datetime | None:
    """给后台看：这单的水印版做好了、压着，几点自动发（没有就 None）。"""
    if o.flow_step != "publish":
        return None
    v = db.scalar(select(DeliveryVersion).where(DeliveryVersion.order_id == o.id, DeliveryVersion.round == o.delivery_round + 1))
    if v is None or v.status != "ready" or v.release_at is None or v.release_at <= utcnow():
        return None
    return v.release_at
