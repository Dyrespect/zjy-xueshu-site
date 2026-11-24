"""订单中枢：建单、发码、认领、加购、作废、确认收货、最终版关口（节点 order.create / code.issue / order.claim /
order.void / confirm.receipt / gate.final 背后的实现）。

- 会话（Customer）先于订单存在；订单在付款时建（平台付款、自有网页付款），码池的码认领时建。
- 认领那一刻：码绑会话，会话里还没挂单的消息和材料挂到这单上，流程走到「已认领」。
- 状态只由流程引擎（flow.py）按流程定义走；这里只发事件（claimed、changed、voided、completed……）。
- 已完成之前都能作废：撤单（码退回还能用）、退款（码作废）；作废后停在原进度、不发最终版。
- 最终版（水印版以外的成品）只能在「已完成」之后发：release_final 先过 require_completed。
契约：docs/任务单/06_订单中枢契约.md。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.events import record_event
from app.intake import clock, codes, flow, pricing
from app.intake.adapters import PaidIn, PlatformSignal
from app.intake.config_store import BizConfig, load_config
from app.intake.config_store import dec as config_dec
from app.intake.flow import StageError
from app.intake.models import (
    PREVIEW_KIND,
    STAGE_LABELS,
    ActivationCode,
    CodeRedemption,
    Customer,
    FileRecord,
    Message,
    Order,
    ProductionMessage,
)
from app.intake.service import (
    WECOM_FILE_MAX,
    Ctx,
    add_production_message,
    create_outbox,
    display_name,
    new_delivery_token,
)

ACTIVE_LIMIT = 20


# ---------------------------------------------------------------- 查

def session_ids(db: Session, customer: Customer) -> list[int]:
    """同一个人的会话（网页、微信各一行；person_id 由模块 D 的 customer.memory 写）。"""
    if customer.person_id is None:
        return [customer.id]
    return list(db.scalars(select(Customer.id).where(Customer.person_id == customer.person_id))) or [customer.id]


def _still_open(o: Order, cfg: BizConfig) -> bool:
    if flow.is_closed(o):
        return False
    if o.stage == "delivered":
        # 已交付：还剩修改轮数、交付后 revise_after_days 天内仍算在走（客人用剩下那轮改）
        from app.intake.service import revisions_left

        recent = o.finished_at is not None and utcnow() - o.finished_at <= timedelta(days=cfg.revise_after_days)
        return recent and revisions_left(o, cfg) > 0
    return True


def active_orders(db: Session, customer: Customer) -> list[Order]:
    """这个人在走的单（不含作废、旧草稿；已交付的只算还能改的），最近活跃的在前。"""
    cfg = load_config(db)
    rows = db.scalars(select(Order).where(Order.customer_id.in_(session_ids(db, customer)))
                      .order_by(Order.updated_at.desc(), Order.id.desc()).limit(ACTIVE_LIMIT))
    return [o for o in rows if _still_open(o, cfg)]


def current_order(db: Session, customer: Customer) -> Order | None:
    """这个人在走的单里最近活跃的一单（按人算：网页、微信两个会话都算）。同时有几单时其余的由助手在回复里提一句。"""
    rows = active_orders(db, customer)
    return rows[0] if rows else None


def latest_order(db: Session, customer: Customer) -> Order | None:
    return current_order(db, customer) or db.scalar(
        select(Order).where(Order.customer_id == customer.id).order_by(Order.id.desc()).limit(1))


def addon_keys(order: Order) -> list[str]:
    return [a.get("key", "") for a in (order.addons or [])]


def has_addon(order: Order, key: str) -> bool:
    return key in addon_keys(order)


def sku_label(cfg: BizConfig, order: Order) -> str:
    return pricing.sku_name(cfg, order.sku) if order.sku else "货号没定"


# ---------------------------------------------------------------- 建单、发码

def new_order(db: Session, ctx: Ctx, *, platform: str, sku: str, addons: list[str] | tuple[str, ...] = (),
              platform_order_id: str | None = None, buyer_id: str = "", paid_at: datetime | None = None,
              paid_amount: str = "", source: str = "", flow_key: str = "", by: str) -> Order:
    cfg = load_config(db)
    p = pricing.parse_sku(sku)
    tier, band = (p.tier, p.band) if p and p.kind == "base" else ("", "")
    price = pricing.sku_price(cfg, sku, list(addons)) if p and p.kind == "base" else None
    now = utcnow()
    o = Order(
        platform=platform, source=source[:64], platform_order_id=platform_order_id or None, buyer_id=buyer_id[:128], paid_at=paid_at,
        paid_amount=paid_amount[:16], sku=sku, tier_key=tier, band_key=band,
        addons=[{"key": k, "code": "", "by": "bundle", "at": now.isoformat()} for k in addons],
        extra_revisions=sum(1 for k in addons if k == "revision"),
        quoted_price=pricing.fmt_money(price), delivery_token=new_delivery_token(), created_at=now, updated_at=now,
    )
    db.add(o)
    db.flush()
    record_event(db, "intake.order_created", f"order:{o.id}", {
        "platform": platform, "platform_order_id": platform_order_id, "sku": sku, "addons": list(addons), "by": by})
    flow.start(db, ctx, o, flow_key or None, by=by, why="建单")
    return o


@dataclass
class PaidResult:
    exit: str  # created | exists | blocked
    code: ActivationCode | None
    order: Order | None


def _check_sku(cfg: BizConfig, sku: str, addons: list[str]) -> pricing.Sku:
    p = pricing.parse_sku(sku)
    if p is None or p.kind == "legacy":
        raise ValueError(f"货号「{sku}」不对")
    if p.kind == "addon" and addons:
        raise ValueError("加购货号不能再带加购")
    bad = [k for k in addons if k not in pricing.ADDON_KEYS]
    if bad:
        raise ValueError(f"不认识的加购：{'、'.join(bad)}")
    if not pricing.sku_open(cfg, sku, addons):
        raise ValueError(f"货号「{pricing.sku_name(cfg, sku, addons)}」现在不卖（设置里价格空着）")
    if p.kind == "base" and "rush" in addons:
        ok, why = pricing.rush_allowed(cfg, cfg.tier(p.tier), find_refs="find_refs" in addons)
        if not ok:
            raise ValueError(f"这个货号不能带加急：{why}")
    return p


def refund_count(db: Session, platform: str, buyer_id: str) -> int:
    if not buyer_id:
        return 0
    return db.scalar(select(func.count()).select_from(Order).where(
        Order.platform == platform, Order.buyer_id == buyer_id, Order.void_reason == "refund")) or 0


def receive_paid(db: Session, ctx: Ctx, paid: PaidIn, *, by: str) -> PaidResult:
    """一笔付款进来（平台适配器、自有网页付款回调调）。幂等：同一平台单号再来返回同一枚码。

    基础货号：建码 + 建订单（已付款、没有会话）；加购货号：只建码（认领时挂到在走的单）。
    """
    cfg = load_config(db)
    p = _check_sku(cfg, paid.sku, paid.addons)
    if paid.platform_order_id:
        row = db.scalar(select(ActivationCode).where(ActivationCode.platform == paid.platform,
                                                     ActivationCode.platform_order_id == paid.platform_order_id))
        if row is not None:
            return PaidResult("exists", row, db.get(Order, row.order_id) if row.order_id else None)
    if cfg.refund_block_after and refund_count(db, paid.platform, paid.buyer_id) >= cfg.refund_block_after:
        record_event(db, "intake.paid_blocked", f"buyer:{paid.platform}:{paid.buyer_id}", {
            "platform": paid.platform, "platform_order_id": paid.platform_order_id, "buyer_id": paid.buyer_id, "by": by})
        ctx.notifier.send(f"{paid.platform} 买家 {paid.buyer_id[-6:]} 退款作废满 {cfg.refund_block_after} 次，这单 "
                          f"{paid.platform_order_id or ''} 没发码：去平台主动退款（平台虚拟单有发货时限）", link="/admin/channels", level="urgent", kind="退款作废太多次")
        return PaidResult("blocked", None, None)
    want = pricing.sku_price(cfg, paid.sku, paid.addons if p.kind == "base" else [])
    got = config_dec(paid.paid_amount)
    if got is not None and want is not None and got != want:
        record_event(db, "intake.paid_amount_mismatch", f"buyer:{paid.platform}:{paid.buyer_id}", {
            "platform": paid.platform, "platform_order_id": paid.platform_order_id, "sku": paid.sku,
            "paid_amount": paid.paid_amount, "price": pricing.fmt_money(want), "by": by})
        ctx.notifier.send(f"{paid.platform} 单 {paid.platform_order_id or ''} 实付 {paid.paid_amount}，设置里的价是 "
                          f"{pricing.fmt_money(want)}，对不上：平台后台的价可能没跟着改", link="/admin/settings", level="urgent", kind="实付和价目对不上")
    row = codes.new_code(db, sku=paid.sku, addons=paid.addons, platform=paid.platform,
                         platform_order_id=paid.platform_order_id, buyer_id=paid.buyer_id, paid_at=paid.paid_at or utcnow(),
                         paid_amount=paid.paid_amount, note=paid.raw_ref)
    order = None
    if p.kind == "base":
        order = new_order(db, ctx, platform=paid.platform, sku=paid.sku, addons=paid.addons,
                          platform_order_id=paid.platform_order_id, buyer_id=paid.buyer_id,
                          paid_at=row.paid_at, paid_amount=paid.paid_amount, source=paid.source, flow_key=paid.flow_key, by=by)
        row.order_id = order.id
        order.code_id = row.id
    record_event(db, "intake.paid_received", f"order:{order.id}" if order else f"code:{row.id}", {
        "platform": paid.platform, "platform_order_id": paid.platform_order_id, "buyer_id": paid.buyer_id,
        "sku": paid.sku, "by": by})
    return PaidResult("created", row, order)


def attach_platform_order(db: Session, row: ActivationCode, *, platform_order_id: str, buyer_id: str = "",
                          paid_at: datetime | None = None, paid_amount: str = "", by: str) -> None:
    """码池的码卖出后，发货工具回写平台单号（闲鱼）。码已经认领建了单的，单号也写到单上。"""
    dup = db.scalar(select(ActivationCode).where(ActivationCode.platform == row.platform,
                                                 ActivationCode.platform_order_id == platform_order_id,
                                                 ActivationCode.id != row.id))
    if dup is not None:
        raise ValueError(f"平台单号 {platform_order_id} 已经对应了别的码")
    row.platform_order_id = platform_order_id
    row.buyer_id = buyer_id[:128] or row.buyer_id
    row.paid_at = paid_at or row.paid_at
    row.paid_amount = paid_amount[:16] or row.paid_amount
    if row.order_id:
        o = db.get(Order, row.order_id)
        if o is not None:
            o.platform_order_id = platform_order_id
            o.buyer_id = row.buyer_id
            o.paid_at = o.paid_at or row.paid_at
            o.paid_amount = o.paid_amount or row.paid_amount
    record_event(db, "intake.paid_received", f"code:{row.id}", {
        "platform": row.platform, "platform_order_id": platform_order_id, "buyer_id": buyer_id, "by": by, "attach": True})


# ---------------------------------------------------------------- 认领

@dataclass
class ClaimResult:
    ok: bool
    result: str  # ok | not_found | used | void | expired | wrong | legacy | locked
    code: str = ""
    order_id: int | None = None
    kind: str = ""  # base | addon
    sku_name: str = ""
    detail: str = ""
    locked_until: datetime | None = None
    fails_left: int | None = None
    claimed_by: int | None = None  # 码已经被认领时，认领它的会话（只给入口模块判断是不是同一个人，不给客人看）


def _addon_rules(cfg: BizConfig, order: Order | None) -> dict[str, str | None]:
    """这单现在能挂哪种加购码：key → None（能挂）或为什么不能。"""
    if order is None:
        return {k: "这是加购码，要先认领基础档的码（买的那一单的码）" for k in pricing.ADDON_KEYS}
    started = order.started_at is not None
    have = addon_keys(order)
    out: dict[str, str | None] = {}
    out["revision"] = "这单已经确认收货了，不能再改" if order.stage in ("completed", "delivered") else None
    if started:
        out["rush"] = "已经开工了，加急要开工前买"
        out["find_refs"] = "已经开工了，帮我找文献要开工前买"
    else:
        ok, why = pricing.rush_allowed(cfg, cfg.tier(order.tier_key), find_refs="find_refs" in have)
        out["rush"] = None if ok and "rush" not in have else (why or "这单已经有加急了")
        out["find_refs"] = (None if "find_refs" not in have and "rush" not in have
                            else ("这单已经有帮我找文献了" if "find_refs" in have else "加急的单不能再加帮我找文献"))
    return out


def _attach_session(db: Session, order: Order, customer: Customer) -> tuple[int, int]:
    """会话里还没挂单的消息、材料挂到这单上。"""
    db.flush()
    m = db.execute(update(Message).where(Message.customer_id == customer.id, Message.order_id.is_(None))
                   .values(order_id=order.id).execution_options(synchronize_session=False)).rowcount
    f = db.execute(update(FileRecord).where(FileRecord.customer_id == customer.id, FileRecord.order_id.is_(None),
                                            FileRecord.role.in_(("material", "voice")))
                   .values(order_id=order.id).execution_options(synchronize_session=False)).rowcount
    db.expire_all()
    return m or 0, f or 0


def _bind(db: Session, ctx: Ctx, order: Order, customer: Customer, *, channel: str, wechat: str, code: str, by: str) -> None:
    now = utcnow()
    order.customer_id = customer.id
    order.claimed_at = order.redeemed_at = now
    if not order.source and customer.source:
        order.source = customer.source[:64]  # 最早从哪来：没有下单页带的，就用会话进线时的来源
    if wechat or customer.channel == "wecom":
        order.wechat_external_userid = wechat or customer.external_id
    order.updated_at = now
    db.flush()
    msgs, files = _attach_session(db, order, customer)
    order = db.get(Order, order.id)
    record_event(db, "intake.order_claimed", f"order:{order.id}", {
        "code": code, "customer": customer.id, "channel": channel, "attached_messages": msgs, "attached_files": files, "by": by})
    flow.emit(db, ctx, order, "claimed", by=by, why="认领")
    if files:
        flow.emit(db, ctx, order, "changed", by=by, why="认领前发来的材料挂上了")


def claim(db: Session, ctx: Ctx, customer: Customer, given: str, *, channel: str, wechat_external_userid: str = "",
          by: str = "bot") -> ClaimResult:
    """认领一枚码（order.claim 节点）。同一会话再交同一枚码算成功（幂等）。调用方提交事务。"""
    cfg = load_config(db)
    order = current_order(db, customer)
    rules = _addon_rules(cfg, order)
    addon_skus = [f"addon-{k}" for k, why in rules.items() if why is None]
    # 同一个人可以同时有几单在走（主窗口 11-18 裁决 K2）：基础码总能认领；加购码挂到最近活跃的那单
    taken = codes.take(db, given=given, customer_id=customer.id, base_ok=True, addon_skus=addon_skus)
    if taken.ok:
        row = taken.row
        p = pricing.parse_sku(row.sku)
        if p.kind == "base":
            o = db.get(Order, row.order_id) if row.order_id else None
            if o is None or o.customer_id is not None or flow.is_closed(o) or o.stage != "paid":
                o = new_order(db, ctx, platform=row.platform or "fk", sku=row.sku, addons=row.addons or [],
                              platform_order_id=row.platform_order_id, buyer_id=row.buyer_id, paid_at=row.paid_at,
                              paid_amount=row.paid_amount, by=by)
            row.order_id = o.id
            o.code_id = row.id
            db.add(CodeRedemption(code=row.code, code_id=row.id, order_id=o.id, customer_id=customer.id, channel=channel,
                                  created_at=utcnow()))
            codes.record_attempt(db, customer.id, o.id, given, "ok")
            record_event(db, "intake.code_redeemed", f"order:{o.id}", {"code": row.code, "result": "ok", "kind": "base", "by": by})
            _bind(db, ctx, o, customer, channel=channel, wechat=wechat_external_userid, code=row.code, by=by)
            name = pricing.sku_name(cfg, row.sku, row.addons or [])
            ctx.notifier.send(f"新单：{display_name(customer)} 认领了 #{o.id}（{name}）", link=f"/admin/conversations/{customer.id}", level="count", kind="新单认领", who=f"customer:{customer.id}")
            return ClaimResult(True, "ok", row.code, o.id, "base", name)
        # 加购码
        row.order_id = order.id
        db.add(CodeRedemption(code=row.code, code_id=row.id, order_id=order.id, customer_id=customer.id, channel=channel,
                              created_at=utcnow()))
        codes.record_attempt(db, customer.id, order.id, given, "ok")
        record_event(db, "intake.code_redeemed", f"order:{order.id}", {"code": row.code, "result": "ok", "kind": "addon", "by": by})
        apply_addon(db, ctx, order, p.addon, code=row.code, by=by)
        return ClaimResult(True, "ok", row.code, order.id, "addon", pricing.sku_name(cfg, row.sku))

    # 没领到
    row = taken.row
    result, detail, claimed_by = taken.reason, "", None
    if result == "used" and row is not None:
        red = codes.redemption_of(db, row.code)
        claimed_by = red.customer_id if red is not None else row.customer_id
        if red is not None and red.customer_id in session_ids(db, customer):
            kind = "addon" if row.sku.startswith("addon-") else "base"
            return ClaimResult(True, "ok", row.code, red.order_id, kind, pricing.sku_name(cfg, row.sku, row.addons or []),
                               "这个码这个会话已经认领过了")
    if result == "wrong" and row is not None:
        p = pricing.parse_sku(row.sku)
        if p is not None and p.kind == "base":
            detail = "基础码现在用不上"
        elif p is not None and p.kind == "addon":
            detail = rules.get(p.addon) or "这个加购码现在用不上"
        detail = f"这个码是「{pricing.sku_name(cfg, row.sku, row.addons or [])}」：{detail}"
    elif result == "legacy" and row is not None:
        detail = f"这个码是「{pricing.sku_name(cfg, row.sku)}」（11-18 改价之前的档位），要负责人来处理"
    codes.record_attempt(db, customer.id, order.id if order else None, given, result)
    record_event(db, "intake.code_failed", f"customer:{customer.id}", {"given": given[:64], "result": result, "by": by})
    db.flush()
    until = codes.locked_until(db, customer.id)
    return ClaimResult(False, result, taken.code, order.id if order else None, "", "", detail, until,
                       codes.fails_left(db, customer.id), claimed_by)


def apply_addon(db: Session, ctx: Ctx, order: Order, key: str, *, code: str = "", by: str) -> None:
    now = utcnow()
    order.addons = [*(order.addons or []), {"key": key, "code": code, "by": "code" if code else by, "at": now.isoformat()}]
    if key == "revision":
        order.extra_revisions = (order.extra_revisions or 0) + 1
    order.updated_at = now
    record_event(db, "intake.addon_added", f"order:{order.id}", {"key": key, "code": code, "by": by})
    flow.emit(db, ctx, order, "changed", by=by, why=f"加购：{key}")


def remove_manual_addon(db: Session, order: Order, key: str, *, by: str) -> None:
    order.addons = [a for a in (order.addons or []) if not (a.get("key") == key and a.get("by") == "edison")]
    order.updated_at = utcnow()
    record_event(db, "intake.addon_removed", f"order:{order.id}", {"key": key, "by": by})


def create_manual_order(db: Session, ctx: Ctx, customer: Customer, sku: str, addons: list[str] | tuple[str, ...] = (),
                        *, by: str = "edison", why: str = "") -> Order:
    """后台手动开单（先做后付、熟人）：不收码，platform=manual，直接到已认领。"""
    cfg = load_config(db)
    p = _check_sku(cfg, sku, list(addons))
    if p.kind != "base":
        raise ValueError("手动开单要选基础货号（时长档 × 篇数）")
    if current_order(db, customer) is not None:
        raise ValueError("这个会话已经有一单在走了")
    o = new_order(db, ctx, platform="manual", sku=sku, addons=addons, paid_at=None, by=by)
    record_event(db, "admin.manual_order", f"order:{o.id}", {"customer": customer.id, "sku": sku, "why": why[:200], "by": by})
    _bind(db, ctx, o, customer, channel=customer.channel, wechat="", code="", by=by)
    return o


# ---------------------------------------------------------------- 查码（code.lookup，只读）

@dataclass
class CodeLookup:
    state: str  # not_found | unused_pool | paid | claimed | void | expired | addon | legacy
    code: str = ""
    sku: str = ""
    sku_name: str = ""
    std_hours: int | None = None
    order_id: int | None = None
    customer_id: int | None = None
    stage: str = ""
    progress: str = ""


def lookup_code(db: Session, given: str) -> CodeLookup:
    """兑换页、入口用：这枚码现在什么情况。不改库、不算撞库。"""
    code = codes.normalize_code(given)
    row = db.scalar(select(ActivationCode).where(ActivationCode.code == code)) if code else None
    if row is None:
        return CodeLookup("not_found", code or "")
    cfg = load_config(db)
    p = pricing.parse_sku(row.sku)
    out = CodeLookup("", row.code, row.sku, pricing.sku_name(cfg, row.sku, row.addons or []))
    if p is not None and p.kind == "base":
        t = cfg.tier(p.tier)
        out.std_hours = pricing.promised_hours(cfg, t) if t else None  # 对客说的时限（含余量）
    order = db.get(Order, row.order_id) if row.order_id else None
    if order is not None:
        out = replace(out, order_id=order.id, customer_id=order.customer_id, stage=order.stage, progress=progress(db, order, cfg))
    if row.status == "void":
        out.state = "void"
    elif p is not None and p.kind == "legacy":
        out.state = "legacy"
    elif row.status == "used":
        red = codes.redemption_of(db, row.code)
        out.customer_id = red.customer_id if red else row.customer_id
        out.state = "claimed"
    elif row.expires_at is not None and row.expires_at <= utcnow():
        out.state = "expired"
    elif p is not None and p.kind == "addon":
        out.state = "addon"
    else:
        out.state = "paid" if order is not None else "unused_pool"
    return out


# ---------------------------------------------------------------- 客户与记忆（模块 D 写）

def set_customer_memory(db: Session, customer_id: int, *, person_id: int | None = None, memory_brief: str | None = None,
                        handoff_brief: str | None = None, by: str = "customer.memory") -> Customer:
    """customer.memory 节点写这三列：同一个人的 person_id、给助手的摘要、给制作方的摘要。只有这里写。"""
    c = db.get(Customer, customer_id)
    if c is None:
        raise ValueError("没有这个会话")
    if person_id is not None:
        c.person_id = person_id
    if memory_brief is not None:
        c.memory_brief = memory_brief[:2000]
    if handoff_brief is not None:
        c.handoff_brief = handoff_brief[:4000]
    record_event(db, "intake.customer_memory", f"customer:{c.id}", {
        "person_id": c.person_id, "memory_brief": bool(c.memory_brief), "handoff_brief": bool(c.handoff_brief), "by": by})
    return c


# ---------------------------------------------------------------- 作废

def void_order(db: Session, ctx: Ctx, order: Order, *, code_action: str, by: str, why: str) -> Order:
    """作废（order.void 节点）：撤单 return（码退回还能用，只许开工前）/ 退款 void（码作废）。已完成之后不能作废。"""
    if code_action not in ("return", "void"):
        raise ValueError("code_action 只能是 return 或 void")
    label = flow.stage_label(order)
    if not flow.accepts(order, "voided"):
        if order.stage in ("completed", "delivered"):
            raise StageError(f"这单已经「{label}」，之后的退款走平台售后，不作废、不自动补发")
        raise StageError(f"这单现在是「{label}」，不能作废")
    if code_action == "return" and order.started_at is not None:
        raise StageError("已经开工了，码不能退回；平台退款请选「退款，码作废」")
    now = utcnow()
    order.voided_from = order.stage
    order.void_reason = "return" if code_action == "return" else "refund"
    order.hold_reason = ""
    order.voided_at = now
    rows = list(db.scalars(select(ActivationCode).where(ActivationCode.order_id == order.id)))
    for row in rows:
        if code_action == "return":
            codes.return_code(db, row, why=why or "开工前撤单", by=by)
        else:
            codes.void_for_refund(db, row, why=why or "退款", by=by)
    if code_action == "return":
        order.code_id = None
    record_event(db, "intake.order_voided", f"order:{order.id}", {
        "from": order.voided_from, "code_action": code_action, "codes": [r.code for r in rows], "why": why[:200], "by": by})
    flow.emit(db, ctx, order, "voided", by=by, why=why)
    if order.started_at is not None:
        add_production_message(db, order, "to_maker", "补充要求", f"这单作废了（{why or '退款'}），停工，不用再交。", author="system")
    customer = db.get(Customer, order.customer_id) if order.customer_id else None
    who = display_name(customer) if customer else f"{order.platform} 单 {order.platform_order_id or order.id}"
    ctx.notifier.send(f"{who} 这单作废了（{'码退回' if code_action == 'return' else '退款，码作废'}）：{why[:60]}", link="/admin/orders", level="digest", kind="作废", who=f"order:{order.id}")
    return order


# ---------------------------------------------------------------- 确认收货、最终版

def mark_completed(db: Session, ctx: Ctx, order: Order, *, source: str, by: str) -> str:
    """confirm.receipt：订单到「已完成」，流程接着跑 gate.final 发最终版。返回 completed / recorded / ignored。

    - 这个渠道认不认这种来源只看一张表（设置 delivery.confirm_sources_by_platform；平台单客人自己说确认不算）。
    - 平台的「已完成」来早了（还没交水印版）：先记成事实 platform_completed_at，发布水印版那一步直接放最终版。
    """
    cfg = load_config(db)
    platform = order.platform or "legacy"
    if source != "free" and source not in cfg.delivery.sources(platform):
        record_event(db, "intake.signal_ignored", f"order:{order.id}", {
            "platform": platform, "kind": "completed", "source": source, "why": "这个渠道不认这种确认来源", "by": by})
        if source == "customer":
            raise StageError("这单是平台订单：去平台订单里点「确认收货」，平台确认后才发可编辑的 PPT 和讲稿")
        return "ignored"
    if order.stage in ("completed", "delivered") or order.flow_step == "revising_after":
        return "completed"  # 已经确认过了（幂等）
    if flow.accepts(order, "completed"):
        flow.emit(db, ctx, order, "completed", by=by, why=f"确认收货（{source}）", data={"source": source})
        return "completed"
    if source in ("platform", "edison") and not flow.is_closed(order):
        if order.platform_completed_at is None:
            order.platform_completed_at = utcnow()
            record_event(db, "intake.platform_completed", f"order:{order.id}", {
                "source": source, "stage": order.stage, "by": by, "why": "平台的已完成来得早，先记下，发布水印版时直接放最终版"})
        return "recorded"
    raise StageError(f"这单现在是「{flow.stage_label(order)}」，还没交水印版，不能确认收货")


def record_completion(db: Session, ctx: Ctx, order: Order, *, source: str, by: str) -> None:
    """confirm.receipt 节点（引擎进「确认」这一步时）：记下谁确认的、什么时候。"""
    now = utcnow()
    if not source:
        source = "platform" if order.platform_completed_at else "edison"
    order.completed_at = order.completed_at or now
    if source == "customer":
        order.received_at = order.received_at or now
    record_event(db, "intake.order_completed", f"order:{order.id}", {"source": source, "by": by})
    customer = db.get(Customer, order.customer_id) if order.customer_id else None
    ctx.notifier.send(f"{display_name(customer) if customer else '#' + str(order.id)} 这单已完成（{source}），接着发最终版", level="count", kind="已完成", who=f"order:{order.id}")


def require_completed(order: Order) -> None:
    """最终版关口：不是「已完成」不发（契约第八节检查 4）。"""
    if order.stage != "completed":
        raise StageError(f"最终版只能在「已完成」之后发；这单现在是「{flow.stage_label(order)}」")


def final_files(db: Session, order: Order) -> list[FileRecord]:
    """要放出的最终版：最新的一批（最大的版次），同名文件传了几次只认最后一次。"""
    rows = list(db.scalars(select(FileRecord).where(FileRecord.order_id == order.id, FileRecord.role == "deliverable",
                                                    FileRecord.purpose != PREVIEW_KIND).order_by(FileRecord.round, FileRecord.id)))
    if not rows:
        return []
    top = max(f.round for f in rows)
    latest: dict[str, FileRecord] = {}
    for f in rows:
        if f.round == top:
            latest[f.filename] = f  # 按 id 升序，后传的覆盖先传的
    return sorted(latest.values(), key=lambda f: f.id)


def release_final(db: Session, ctx: Ctx, order: Order, *, by: str) -> bool:
    """gate.final 节点：已完成 → 发最终版（可编辑 pptx、讲稿）+ 交付页链接。还没有最终版文件就叫制作方传，返回 False。"""
    require_completed(order)
    if order.hold_reason:
        return False  # 暂停中（平台申请退款）：先不发最终版
    files = final_files(db, order)
    customer = db.get(Customer, order.customer_id) if order.customer_id else None
    if not files:
        asked = db.scalar(select(func.count()).select_from(ProductionMessage).where(
            ProductionMessage.order_id == order.id, ProductionMessage.kind == "补充要求",
            ProductionMessage.text.like("客户确认收货了%")))
        if not asked and order.started_at is not None:
            add_production_message(db, order, "to_maker", "补充要求",
                                   "客户确认收货了，请传最终版（可编辑的 pptx、讲稿），传上来会自动发给客户。", author="system")
        return False
    if customer is not None:
        tpl = load_config(db).delivery.texts.get("final") or "可编辑的 PPT 和讲稿在这个页面下载：{url}"
        try:
            text = tpl.format(url=ctx.delivery_url(order))
        except (KeyError, IndexError):
            text = tpl
        create_outbox(db, ctx, customer, order, text=text, category="交付", author="system", reasons=["已完成，发最终版"])
        for f in files:
            if f.size <= WECOM_FILE_MAX:
                create_outbox(db, ctx, customer, order, text=f.filename, kind="file", file_id=f.id, category="交付",
                              author="system", reasons=["最终版 20MB 以内，跟链接一起发"])
    order.finished_at = utcnow()
    # 放出的这一批算交过的一版：已交付后再改、再交新的最终版，落到下一个版次，不跟这一批混在一起
    order.delivery_round = max(order.delivery_round, max(f.round for f in files))
    record_event(db, "intake.final_released", f"order:{order.id}", {
        "files": [f.filename for f in files], "round": order.delivery_round, "by": by})
    return True


def deliverables_for_customer(db: Session, order: Order) -> list[FileRecord]:
    """客户能拿到的成品：已完成之前只有交过的水印版；已完成、已交付才有最终版。交付页、聊天发文件只许用它。"""
    rows = list(db.scalars(select(FileRecord).where(FileRecord.order_id == order.id, FileRecord.role == "deliverable",
                                                    FileRecord.round > 0).order_by(FileRecord.round.desc(), FileRecord.page_no, FileRecord.id)))
    if order.stage in ("completed", "delivered") or order.finished_at is not None:
        if order.stage == "void":
            return []
        return [f for f in rows if f.purpose != PREVIEW_KIND]  # 最终版（不含水印版）
    return [f for f in rows if f.purpose == PREVIEW_KIND and f.round <= order.delivery_round]


# ---------------------------------------------------------------- 平台信号、暂停

def hold(db: Session, ctx: Ctx, order: Order, *, reason: str, by: str) -> None:
    """暂停（平台上申请了退款）：不开工、不交下一版、不发最终版，等真退（作废）或申请撤了（恢复）。通知负责人。"""
    if order.hold_reason:
        return
    order.hold_reason, order.hold_at = reason[:64], utcnow()
    record_event(db, "intake.order_held", f"order:{order.id}", {"reason": reason, "stage": order.stage, "by": by})
    ctx.notifier.send(f"#{order.id} 平台上申请了退款（{flow.stage_label(order)}），先暂停：不开工、不交下一版、不发最终版。"
                      "同意退款等平台退款消息；拒了等申请关闭消息", link="/admin/orders", level="urgent", kind="平台退款", who=f"order:{order.id}")


def release_hold(db: Session, ctx: Ctx, order: Order, *, by: str) -> None:
    """恢复：申请撤了或被拒。卡在哪一步就再推一下（收资料再判断开工、发布、发最终版）。"""
    if not order.hold_reason:
        return
    record_event(db, "intake.order_released", f"order:{order.id}", {"reason": order.hold_reason, "by": by})
    order.hold_reason, order.hold_at = "", None
    for event in ("changed", "proof_ready", "final_ready"):
        if flow.accepts(order, event) and flow.emit(db, ctx, order, event, by=by, why="退款申请关闭，恢复"):
            break


def apply_signal(db: Session, ctx: Ctx, sig: PlatformSignal, *, by: str) -> Order | None:
    """平台信号：completed → 确认收货（来得早先记下）；refund_requested → 暂停；refund → 已完成之前作废（码作废），
    之后只记下、走平台售后；refund_closed → 恢复。"""
    row = db.scalar(select(ActivationCode).where(ActivationCode.platform == sig.platform,
                                                 ActivationCode.platform_order_id == sig.platform_order_id))
    order = db.get(Order, row.order_id) if row is not None and row.order_id else None
    if order is None:
        if row is not None and sig.kind == "refund" and row.status == "unused":
            codes.void_for_refund(db, row, why="平台退款（还没认领）", by=by)
            return None
        record_event(db, "intake.signal_ignored", f"code:{row.id}" if row else "", {
            "platform": sig.platform, "platform_order_id": sig.platform_order_id, "kind": sig.kind, "why": "没有对应的单", "by": by})
        return None
    if sig.kind == "completed":
        try:
            mark_completed(db, ctx, order, source="platform", by=by)
        except StageError as e:
            record_event(db, "intake.signal_ignored", f"order:{order.id}", {
                "platform": sig.platform, "kind": sig.kind, "why": str(e), "by": by})
        return order
    if sig.kind == "refund_requested":
        if flow.is_closed(order):
            return order
        hold(db, ctx, order, reason="平台申请退款", by=by)
        return order
    if sig.kind == "refund_closed":
        release_hold(db, ctx, order, by=by)
        return order
    if flow.accepts(order, "voided"):
        void_order(db, ctx, order, code_action="void", by=by, why="平台退款")
    else:
        record_event(db, "intake.signal_ignored", f"order:{order.id}", {
            "platform": sig.platform, "kind": sig.kind, "why": "已完成之后的退款走平台售后", "by": by})
        ctx.notifier.send(f"#{order.id} 已完成之后平台退款了，走平台售后，不自动补发", link="/admin/orders", level="urgent", kind="平台退款", who=f"order:{order.id}")
    return order


def orders_waiting_customer(db: Session, *, platforms: list[str] | tuple[str, ...], idle_since: datetime) -> list[int]:
    """给模块 B 的超时自动确认（trigger.confirm_timeout）：在等客人看水印版的单——在「已交水印版」、最近一版已交出、
    没有没处理完的改稿单、最近一版交出时间早于 idle_since、没暂停。只读。"""
    from app.intake.models import Revision

    rows = db.scalars(select(Order).where(Order.stage == "watermarked", Order.platform.in_(list(platforms)),
                                          Order.delivered_at.is_not(None), Order.delivered_at <= idle_since,
                                          Order.hold_reason == ""))
    out = []
    for o in rows:
        open_rev = db.scalar(select(func.count()).select_from(Revision).where(Revision.order_id == o.id, Revision.status == "open"))
        if not open_rev:
            out.append(o.id)
    return out


# ---------------------------------------------------------------- 看（旧 status 的只读推导视图）

def progress(db: Session, order: Order, cfg: BizConfig | None = None) -> str:
    """给后台和助手看细一层（不拿来做判断）。"""
    stage = order.stage
    if not order.flow_step:
        return "旧草稿：11-18 之前没付款就建的单"
    if stage == "paid":
        return "已付款，等客人来认领"
    if stage == "claimed":
        return "认领了，还没收到资料"
    if stage == "collecting":
        if order.queued_at and order.start_date:
            due = f"，开工后 {order.due_hours} 小时内交第一版" if order.due_hours else ""
            return f"资料齐了，排在 {clock.fmt_date(order.start_date)}开工{due}"
        from app.intake.service import conditions_for  # 避免循环 import

        bad = [c for c in conditions_for(db, order, cfg) if not c.ok]
        return f"{bad[0].name}：{bad[0].detail}" if bad else "资料齐了，等排期"
    if stage == "making":
        if order.maker_done_at:
            return "制作方说做好了，等交水印版"
        if order.maker_started_at:
            return "制作方在做"
        return "交接了，等制作方开始"
    if stage == "watermarked":
        return f"交了第 {order.delivery_round} 版水印版，等客人看"
    if stage == "revising":
        return f"改第 {order.delivery_round} 版"
    if stage == "completed":
        return "已完成，等制作方传最终版" if not final_files(db, order) else "已完成"
    if stage == "delivered":
        return "最终版发了"
    if stage == "void":
        how = "码退回" if order.void_reason == "return" else "退款，码作废"
        return f"作废（{how}），停在「{STAGE_LABELS.get(order.voided_from, order.voided_from)}」"
    return STAGE_LABELS.get(stage, stage)


def to_jsonable(v: Any) -> Any:
    if isinstance(v, datetime):
        return v.isoformat()
    return v
