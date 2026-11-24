"""一单的实付、退款、能不能开票（只读，不改任何别的模块的表）。设计第四节、第五节 invoice.gate。

- 实付 = 这单所有没作废的激活码的实付之和（基础码 + 单独买的加购码，「含加购」）；没有码的按订单 paid_amount。
  开票金额 = 实付 − 已退（含税，不另加税：Edison「客人付多少就开多少」）。
- 退款：订单作废原因是 refund → 全退；自有网页的退款从事件 shop.refund_requested / shop.refund_done 算
  （同一付款单 subject 对得上；refund_requested 里有 order_id）；平台申请退款（订单 hold_reason）、
  网页退款还没出结果 → 在退款中。
- 这里只读订单中枢的表；等模块 A 给 orders.paid_breakdown 就换成它（设计第六节需求 1）。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.events import Event
from app.intake.models import ActivationCode, Order
from app.invoices.checks import InvoiceCheckFailed, fmt, money, require_completed, require_not_refunded
from app.invoices.config import InvoiceConfig

PLATFORM_NAMES = {"web": "自有网页", "fk": "发卡站", "manual": "后台手动开单", "xhs": "小红书", "xy": "闲鱼", "dy": "抖音",
                  "legacy": "旧单"}


@dataclass
class PaidFacts:
    order_id: int
    platform: str
    paid: Decimal | None  # 查不到（后台手动开单没填实付）是 None
    parts: list[dict[str, str]] = field(default_factory=list)  # 每枚码：{code, sku, amount}
    paid_complete: bool = True  # 每枚码都有实付
    refunded: Decimal = Decimal("0.00")
    refund_pending: bool = False
    fully_refunded: bool = False
    voided: bool = False
    void_reason: str = ""
    completed_at: datetime | None = None
    stage: str = ""

    @property
    def max_amount(self) -> Decimal | None:
        if self.paid is None:
            return None
        return max(Decimal("0.00"), self.paid - self.refunded)

    def as_dict(self) -> dict[str, Any]:
        return {"order_id": self.order_id, "platform": self.platform, "platform_name": PLATFORM_NAMES.get(self.platform, self.platform),
                "paid": fmt(self.paid), "refunded": fmt(self.refunded), "max_amount": fmt(self.max_amount),
                "parts": self.parts, "paid_complete": self.paid_complete, "refund_pending": self.refund_pending,
                "fully_refunded": self.fully_refunded, "voided": self.voided, "completed": self.completed_at is not None,
                "completed_at": self.completed_at, "stage": self.stage}


def shop_refunds(db: Session, order_ids: set[int]) -> dict[int, tuple[Decimal, bool]]:
    """自有网页的退款：{order_id: (已退金额, 还有没出结果的退款)}。从模块 B 记的事件算，不读它的表。"""
    if not order_ids:
        return {}
    subj_order: dict[str, int] = {}
    asked: Counter[str] = Counter()
    for e in db.scalars(select(Event).where(Event.type == "shop.refund_requested")):
        oid = (e.content or {}).get("order_id")
        if isinstance(oid, int) and oid in order_ids:
            subj_order[e.subject] = oid
            asked[e.subject] += 1
    if not subj_order:
        return {}
    done: Counter[str] = Counter()
    got: dict[str, int] = {}
    for e in db.scalars(select(Event).where(Event.type == "shop.refund_done", Event.subject.in_(list(subj_order)))):
        c = e.content or {}
        done[e.subject] += 1
        if c.get("ok") and isinstance(c.get("amount_fen"), int):
            got[e.subject] = got.get(e.subject, 0) + c["amount_fen"]
    out: dict[int, tuple[Decimal, bool]] = {}
    for subj, oid in subj_order.items():
        prev_amt, prev_pending = out.get(oid, (Decimal("0.00"), False))
        amt = prev_amt + (Decimal(got.get(subj, 0)) / 100).quantize(Decimal("0.01"))
        out[oid] = (amt, prev_pending or asked[subj] > done[subj])
    return out


def paid_facts(db: Session, order: Order, refunds: dict[int, tuple[Decimal, bool]] | None = None) -> PaidFacts:
    if refunds is None:
        refunds = shop_refunds(db, {order.id})
    rows = list(db.scalars(select(ActivationCode).where(ActivationCode.order_id == order.id).order_by(ActivationCode.id)))
    parts, total, complete = [], Decimal("0.00"), True
    for r in rows:
        if r.status == "void":
            continue
        amt = money(r.paid_amount)
        parts.append({"code": r.code, "sku": r.sku, "amount": fmt(amt)})
        if amt is None:
            complete = False
        else:
            total += amt
    if parts and any(p["amount"] for p in parts):
        paid: Decimal | None = total
    else:
        paid = money(order.paid_amount)
        complete = paid is not None
    voided = order.voided_at is not None or order.stage == "void"
    refunded, pending = refunds.get(order.id, (Decimal("0.00"), False))
    f = PaidFacts(order_id=order.id, platform=order.platform or "legacy", paid=paid, parts=parts, paid_complete=complete,
                  refunded=refunded, refund_pending=pending or bool(order.hold_reason), voided=voided,
                  void_reason=order.void_reason or "", completed_at=order.completed_at, stage=order.stage or "")
    f.fully_refunded = (voided and order.void_reason == "refund") or (paid is not None and paid > 0 and refunded >= paid)
    if f.fully_refunded and paid is not None:
        f.refunded = max(refunded, paid)
    return f


@dataclass
class Verdict:
    exit: str  # open 能开 / wait 等（订单没完成、在退款中）/ blocked 不能开
    reason: str = ""  # 给人看的一句（wait、blocked 时）
    warnings: list[str] = field(default_factory=list)
    facts: PaidFacts | None = None
    fail: InvoiceCheckFailed | None = None


def judge(db: Session, order: Order | None, cfg: InvoiceConfig, *, admin: bool = False, now: datetime | None = None,
          refunds: dict[int, tuple[Decimal, bool]] | None = None) -> Verdict:
    """invoice.gate 的判断（代码判断，不让模型判断）。admin=True：后台手工录的，不看渠道名单和申请期限。"""
    if order is None:
        return Verdict("blocked", "找不到这一单")
    f = paid_facts(db, order, refunds)
    v = Verdict("open", facts=f)
    if not admin and f.platform not in cfg.eligible_platforms:
        v.exit, v.reason = "blocked", f"这单是在{PLATFORM_NAMES.get(f.platform, f.platform)}下的，发票请在下单的平台申请"
        return v
    try:
        require_not_refunded(fully_refunded=f.fully_refunded, refund_pending=False, voided=f.voided)
    except InvoiceCheckFailed as e:
        v.exit, v.reason, v.fail = "blocked", e.what if not f.voided or f.fully_refunded else "这单作废了", e
        return v
    try:
        require_not_refunded(fully_refunded=False, refund_pending=f.refund_pending, voided=False)
    except InvoiceCheckFailed as e:
        v.exit, v.reason, v.fail = "wait", e.what, e
        return v
    try:
        require_completed(completed_at=f.completed_at, voided=False)
    except InvoiceCheckFailed as e:
        v.exit, v.reason, v.fail = "wait", "订单完成（确认收货）后自动提交开票", e
        return v
    if not admin and cfg.apply_window_days and f.completed_at is not None:
        if (now or utcnow()) - f.completed_at > timedelta(days=cfg.apply_window_days):
            v.exit, v.reason = "blocked", f"订单完成已超过 {cfg.apply_window_days} 天，网上不能再申请了，请联系负责人"
            return v
    if f.max_amount is None:
        v.warnings.append("查不到这单的实付，开票时要手填金额（不能超过客人真付的）")
    elif f.refunded > 0:
        v.warnings.append(f"退过 {fmt(f.refunded)} 元，按退后 {fmt(f.max_amount)} 元开")
    if not f.paid_complete and f.paid is not None:
        v.warnings.append("有激活码没记实付，实付可能算少了，开票前核一下")
    return v
