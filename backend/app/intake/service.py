"""接单的库操作：渠道收到消息、待发进出、开工判断和排期（gate.ready）、交水印版和修改、制作方会话的记账。

渠道（channels）、交付页（delivery）、后台（admin）都调这里；这里只依赖 core。
11-18 起：订单在付款时建（orders.py），状态由流程引擎（flow.py）按流程定义走；这里发事件（`refresh_status`
= 发 changed，让「收资料」那一步重新判断能不能开工）。条件都齐就排队；排到那天流程进「制作中」，交接给工厂。
交付分两步：先交水印版（deliver），订单到「已完成」才发最终版（orders.release_final）。

接单 v2：回复直接发（`create_outbox` 只有设置里打开了「先给我看」的类别才进待批）；
微信客服 48 小时窗口关着时发不出去的，客户下次说话时重发。
"""

from __future__ import annotations

import logging
import re
import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.db import txn_lock, utcnow
from app.core.events import record_event
from app.core.notify import Notifier
from app.core.storage import Storage
from app.intake import clock, flow, materials
from app.intake.config_store import BizConfig, load_config
from app.intake.models import (
    PAGE_KIND,
    PREVIEW_KIND,
    Customer,
    FileRecord,
    Job,
    Message,
    Order,
    Outbox,
    ProductionMessage,
    Revision,
)
from app.intake.rules import (
    Condition,
    FileFact,
    OrderFacts,
    Plan,
    can_start,
    due_hours,
    plan_slot,
    rush_decision,
    start_conditions,
)
from app.intake.settings import IntakeSettings

log = logging.getLogger("app.intake")

WECOM_WINDOW_HOURS = 48
WECOM_WINDOW_MAX = 5
WECOM_FILE_MAX = 20 * 1024 * 1024  # 交付时同时发文件的上限（微信客服发文件 20MB 以内）
# 发送失败是因为 48 小时窗口（客户再说一句就能发）：这几种原因的失败，客户下次说话时重新排队发
# （后两种是入口模块 D 的发件员加的：会话状态不是 0 / 1 时不调 send_msg；窗口快满时只发交付类，别的等客人再开口）
WINDOW_FAIL_PREFIXES = ("客户最后一次说话已经超过 48 小时", "48 小时内已经发满 5 条", "会话状态现在不能发", "窗口里给交付留着")


@dataclass
class Ctx:
    """跑业务流程要的底座东西（接口里从 app.state 拿，测试里直接构造）。"""

    settings: IntakeSettings
    storage: Storage
    notifier: Notifier
    public_base_url: str = "http://127.0.0.1:8710"

    def delivery_url(self, order: Order) -> str:
        return f"{self.public_base_url.rstrip('/')}/d/{order.delivery_token}"


# ---------------------------------------------------------------- 客户、订单

def display_name(customer: Customer) -> str:
    if customer.nickname:
        return customer.nickname
    prefix = "网页客户" if customer.channel == "web" else "微信客户"
    return f"{prefix}{customer.id}"


def get_or_create_customer(
    db: Session,
    channel: str,
    external_id: str,
    *,
    open_kfid: str = "",
    nickname: str = "",
    source: str = "",
) -> Customer:
    c = db.scalar(select(Customer).where(Customer.channel == channel, Customer.external_id == external_id))
    if c is None:
        c = Customer(
            channel=channel, external_id=external_id, open_kfid=open_kfid, nickname=nickname,
            source=source, created_at=utcnow(), last_activity_at=utcnow(),
        )
        db.add(c)
        db.flush()
        record_event(db, "intake.customer_created", f"customer:{c.id}", {"channel": channel, "source": source})
    else:
        if nickname and not c.nickname:
            c.nickname = nickname
        if source and not c.source:
            c.source = source
        if open_kfid and not c.open_kfid:
            c.open_kfid = open_kfid
    return c


def new_delivery_token() -> str:
    return secrets.token_urlsafe(24)


def current_order(db: Session, customer: Customer) -> Order | None:
    """这个会话在走的单；没认领过就是 None（11-18 起订单不在开口时建，在付款时建）。"""
    from app.intake.orders import current_order as _current  # orders 依赖本文件，放这里免得循环

    return _current(db, customer)


def order_files(db: Session, order: Order, role: str = "material") -> list[FileRecord]:
    return list(db.scalars(
        select(FileRecord).where(FileRecord.order_id == order.id, FileRecord.role == role).order_by(FileRecord.id)
    ))


def open_revision(db: Session, order: Order) -> Revision | None:
    return db.scalar(
        select(Revision).where(Revision.order_id == order.id, Revision.status == "open", Revision.free.is_(True))
        .order_by(Revision.id.desc()).limit(1)
    )


def has_undelivered_deliverable(db: Session, order: Order) -> bool:
    """有没交出去的新一版文件（成品或整页图）：后台显示「交这一版」。"""
    n = db.scalar(select(func.count()).select_from(FileRecord).where(
        FileRecord.order_id == order.id, FileRecord.role.in_(("deliverable", "page")), FileRecord.round > order.delivery_round,
    ))
    return bool(n)


def order_facts(db: Session, order: Order) -> OrderFacts:
    keys = {a.get("key", "") for a in (order.addons or [])}
    return OrderFacts(
        stage=order.stage,
        sku=order.sku,
        tier_key=order.tier_key,
        band_key=order.band_key,
        addons=keys,
        rush_by_edison=any(a.get("key") == "rush" and a.get("by") == "edison" for a in (order.addons or [])),
        occasion=order.occasion,
        title=order.title,
        duration_min=order.duration_min,
        duration_default=order.duration_default,
        duration_confirmed=order.duration_confirmed,
        present_date=order.present_date,
        present_date_text=order.present_date_text,
        paper_count=order.paper_count,
        page_count=order.page_count,
        school=order.school,
        language=order.language,
        structure_req=order.structure_req,
        requirement_quotes=list(order.requirement_quotes or []),
        claimed=order.customer_id is not None,
        rush=order.rush,
        queued=order.queued_at is not None,
        start_date=order.start_date,
        eta_date=order.eta_date,
        started=order.started_at is not None,
        files=[FileFact(f.id, f.filename, f.purpose) for f in order_files(db, order)],
    )


def booked_by_day(db: Session, *, exclude_order_id: int | None = None) -> dict[date, int]:
    """每天已经排了几单开工：排队中的按排定开工日，已开工的按实际开工那天。"""
    booked: dict[date, int] = {}
    rows = db.scalars(select(Order).where(Order.queued_at.is_not(None), Order.voided_at.is_(None), Order.rush.is_(False)))
    for o in rows:
        if o.id == exclude_order_id:
            continue
        d = clock.local_now(o.started_at).date() if o.started_at else o.start_date
        if d is not None:
            booked[d] = booked.get(d, 0) + 1
    return booked


def rush_booked_today(db: Session, today: date | None = None, *, exclude_order_id: int | None = None) -> int:
    """今天已经卖出去的加急单（排在今天开工的、今天开工了的）。"""
    today = today or clock.today()
    n = 0
    for o in db.scalars(select(Order).where(Order.rush.is_(True), Order.voided_at.is_(None), Order.queued_at.is_not(None))):
        if o.id == exclude_order_id:
            continue
        d = clock.local_now(o.started_at).date() if o.started_at else o.start_date
        if d == today:
            n += 1
    return n


def revisions_left(order: Order, cfg: BizConfig) -> int:
    """还能改几次：含的免费修改 + 用新激活码换的，减去提过的。"""
    return max(0, cfg.revisions_included + (order.extra_revisions or 0) - (order.revision_used or 0))


def plan_for(db: Session, order: Order, cfg: BizConfig, today: date | None = None) -> Plan | None:
    today = today or clock.today()
    if order.queued_at and order.start_date and order.eta_date:
        return Plan(order.start_date, order.eta_date, 0, order.due_hours or 0)
    facts = order_facts(db, order)
    rush, _ = rush_decision(facts, cfg, rush_booked_today(db, today, exclude_order_id=order.id))
    hours = due_hours(facts, cfg, rush=rush)
    return plan_slot(today, booked_by_day(db, exclude_order_id=order.id), cfg, hours, rush=rush, now=clock.local_now())


def collect_for(db: Session, order: Order, ctx: Any = None) -> Any:
    """intake.collect 节点：照清单算这单还缺什么（「资料齐」只有这一份来源）。"""
    from app.core.nodes import NodeCall, run_node

    flow.ensure_nodes()
    return run_node("intake.collect", NodeCall(db, ctx, "system", order.id), {"order_id": order.id}).output


def conditions_for(db: Session, order: Order, cfg: BizConfig | None = None, today: date | None = None) -> list[Condition]:
    """开工条件（后台订单卡、助手、进度一句话看的）。最后一条是需求卡：判断在流程的闸口节点 gate.brief_confirmed，这里只是摆出来。"""
    from app.intake import brief

    cfg = cfg or load_config(db)
    today = today or clock.today()
    conds = start_conditions(order_facts(db, order), cfg, plan_for(db, order, cfg, today), today, collect=collect_for(db, order))
    ok, detail = brief.condition(db, order)
    return [*conds, Condition("brief", "需求卡确认了", ok, detail)]


def _touch(order: Order) -> None:
    order.updated_at = utcnow()


def add_need(order: Order, kind: str, detail: str) -> None:
    """发了负责人微信的一件事（后台订单卡上显示，处理了点掉）。同一类还没处理的，补在同一条后面。"""
    needs = list(order.needs_edison or [])
    for i, n in enumerate(needs):
        if n.get("type") == kind and not n.get("resolved"):
            needs[i] = {**n, "detail": (n["detail"] + "；" + detail)[-600:], "at": utcnow().isoformat()}
            order.needs_edison = needs
            return
    needs.append({"type": kind, "detail": detail[:300], "at": utcnow().isoformat(), "resolved": False})
    order.needs_edison = needs


def refresh_status(db: Session, ctx: Ctx, order: Order | None, *, announce: bool = True) -> str:
    """事实变了（收到材料、信息改了、加购了、到了新的一天……）：发 changed，「收资料」那一步重新判断能不能开工。

    announce=False：排上时不另发「排上啦」（机器人这一趟自己说）。返回现在的状态。
    """
    if order is None:
        return ""
    flow.emit(db, ctx, order, "changed", by="system", why="事实变了", data={"announce": announce})
    return order.stage


def gate_check(db: Session, ctx: Ctx, order: Order, *, announce: bool = True) -> tuple[str, str]:
    """gate.ready 节点：条件都齐就排队；排到今天（今天名额没满，或加急）就开工。返回（start | wait, 说明）。"""
    txn_lock(db, "intake.quota")  # 先数已排几单再排：PG 上几单同时排要一个一个来，不然会超名额（SQLite 写会话本来就独占）
    cfg = load_config(db)
    today = clock.today()
    if order.hold_reason:
        return "wait", f"暂停：{order.hold_reason}"
    if order.queued_at is None:
        facts = order_facts(db, order)
        rush_today = rush_booked_today(db, today, exclude_order_id=order.id)
        rush, rush_why = rush_decision(facts, cfg, rush_today)
        facts.rush = rush
        hours = due_hours(facts, cfg, rush=rush)
        plan = plan_slot(today, booked_by_day(db, exclude_order_id=order.id), cfg, hours, rush=rush, now=clock.local_now())
        conds = start_conditions(facts, cfg, plan, today, collect=collect_for(db, order, ctx))
        bad = [c for c in conds if not c.ok]
        if bad or plan is None:
            return "wait", "；".join(f"{c.name}：{c.detail}" for c in bad) or "名额排满了"
        if "rush" in facts.addons and not rush:
            add_need(order, "退款", f"付了加急但{rush_why}，按标准做，要退加急费")
            ctx.notifier.send(f"#{order.id} 付了加急但{rush_why}，按标准做，要退加急费", link="/admin/orders", level="urgent", kind="付了加急做不到", who=f"order:{order.id}")
        order.rush = rush
        _enqueue_order(db, ctx, order, plan, announce=announce)
    if order.start_date and order.start_date <= today:
        if order.rush:
            return "start", "加急，今天开工"
        started_today = sum(
            1 for o in db.scalars(select(Order).where(Order.started_at.is_not(None), Order.rush.is_(False), Order.id != order.id))
            if clock.local_now(o.started_at).date() == today
        )
        if started_today < cfg.daily_quota:
            return "start", "排到今天"
        return "wait", "今天开工的名额满了，等明天"
    return "wait", f"排在 {clock.fmt_date(order.start_date)}开工"


def _enqueue_order(db: Session, ctx: Ctx, order: Order, plan: Plan, *, announce: bool = True) -> None:
    order.queued_at = utcnow()
    order.start_date = plan.start_date
    order.eta_date = plan.eta_date
    order.due_hours = plan.hours
    _touch(order)
    record_event(db, "intake.order_queued", f"order:{order.id}", {
        "start_date": plan.start_date.isoformat(), "eta_date": plan.eta_date.isoformat(), "rush": order.rush,
        "due_hours": plan.hours,
    })
    customer = db.get(Customer, order.customer_id) if order.customer_id else None
    if customer is None:
        return
    ctx.notifier.send(f"{display_name(customer)} 资料齐了，排在 {clock.fmt_date(plan.start_date)}开工"
                      f"（{'加急，' if order.rush else ''}开工后 {plan.hours} 小时内交第一版）", link=f"/admin/conversations/{customer.id}", level="digest", kind="资料齐了排期", who=f"order:{order.id}")
    if not announce:
        return
    text = (f"资料齐了，排上啦：{clock.fmt_date(plan.start_date)}开工，开工后 {plan.hours} 小时内先发你水印版看。"
            if plan.start_date != clock.today() else f"资料齐了，今天就开工，{plan.hours} 小时内先发你水印版看。")
    create_outbox(db, ctx, customer, order, text=text, category="排期通知", author="system",
                  reasons=["开工条件都齐了，代码自动排进队", f"开工日 {clock.fmt_date(plan.start_date)}"])


# ---------------------------------------------------------------- 收消息（渠道调）

def _after_customer_message(db: Session, ctx: Ctx, customer: Customer, msg: Message, *, run_bot: bool = True) -> None:
    now = msg.created_at
    first = customer.last_customer_msg_at is None
    customer.last_customer_msg_at = now
    customer.last_activity_at = now
    if customer.channel == "wecom":
        requeue_window_failed(db, customer)
    if run_bot and not customer.human_takeover:
        enqueue_job(db, customer, delay=ctx.settings.INTAKE_DEBOUNCE_SECONDS)
    if first:
        preview = msg.text[:40] if msg.kind == "text" else f"[{msg.kind}]"
        ctx.notifier.send(f"新客户 {display_name(customer)}（{'网页聊天' if customer.channel == 'web' else '微信客服'}）：{preview}",
                          link=f"/admin/conversations/{customer.id}", level="count", kind="新客户", who=f"customer:{customer.id}")
    elif customer.human_takeover:
        ctx.notifier.send(f"{display_name(customer)}（你在接）发来新消息：{msg.text[:40] if msg.kind == 'text' else '[' + msg.kind + ']'}",
                          link=f"/admin/conversations/{customer.id}", level="urgent", kind="客人消息", who=f"customer:{customer.id}")


def is_duplicate(db: Session, customer: Customer, channel_msgid: str | None) -> bool:
    if not channel_msgid:
        return False
    return db.scalar(select(func.count()).select_from(Message).where(
        Message.customer_id == customer.id, Message.channel_msgid == channel_msgid,
    )) > 0


def receive_text(
    db: Session, ctx: Ctx, customer: Customer, text: str, *,
    channel_msgid: str | None = None, at: datetime | None = None, claim: bool = True, run_bot: bool = True,
) -> Message | None:
    """存一句客人的话。claim=False、run_bot=False：入口模块（D）的 entry.route 自己认领、自己决定叫不叫助手。"""
    if is_duplicate(db, customer, channel_msgid):
        return None
    order = current_order(db, customer)  # 没认领时是 None：消息挂在会话上，认领时再挂到订单
    msg = Message(
        customer_id=customer.id, order_id=order.id if order else None, direction="in", sender="customer", kind="text",
        text=text[:8000], channel_msgid=channel_msgid, created_at=at or utcnow(),
    )
    db.add(msg)
    db.flush()
    record_event(db, "intake.message_received", f"customer:{customer.id}", {"message": msg.id, "kind": "text", "text": text[:500]})
    if claim:
        claim_codes_in(db, ctx, customer, text)
    _after_customer_message(db, ctx, customer, msg, run_bot=run_bot)
    return msg


def claim_codes_in(db: Session, ctx: Ctx, customer: Customer, text: str) -> list[Any]:
    """消息里有激活码就当场认领（order.claim 节点），后面同一批发来的材料就能收了。结果助手从码的状态读出来告诉客人。
    第一期在这里做；入口模块（D）的 entry.route 接手后由它在入站时做。"""
    import re as _re

    from app.core.nodes import NodeCall, run_node
    from app.intake import codes

    found: list[str] = []
    for piece in _re.split(r"[，,。;；\n]+", text or ""):
        code = codes.normalize_code(piece)
        if code and code not in found:
            found.append(code)
    out = []
    if not found:
        return out
    flow.ensure_nodes()
    for code in found[:3]:
        res = run_node("order.claim", NodeCall(db, ctx, "customer"), {
            "customer_id": customer.id, "code": code, "channel": customer.channel,
            "wechat_external_userid": customer.external_id if customer.channel == "wecom" else ""})
        out.append(res.output)
    return out


def receive_file(
    db: Session, ctx: Ctx, customer: Customer, *, filename: str, data: bytes, content_type: str = "",
    kind: str = "file", channel_msgid: str | None = None, at: datetime | None = None, run_bot: bool = True,
) -> tuple[Message, FileRecord | None] | None:
    """收一个文件。还没认领（这个人没有在走的单）时不收、不存（主窗口 11-18 裁决 K1：「聊天也要花钱」「先认领」），
    回一句设置里的固定话（entry_texts.file_refused），返回 (消息, None)。"""
    if is_duplicate(db, customer, channel_msgid):
        return None
    order = current_order(db, customer)
    if order is None:
        msg = Message(customer_id=customer.id, order_id=None, direction="in", sender="customer", kind="text",
                      text=f"[发了文件「{filename[:120]}」，还没认领激活码，没收]", channel_msgid=channel_msgid,
                      created_at=at or utcnow())
        db.add(msg)
        db.flush()
        record_event(db, "intake.file_refused", f"customer:{customer.id}", {"name": filename[:200], "size": len(data), "kind": kind})
        _after_customer_message(db, ctx, customer, msg, run_bot=False)
        today0 = datetime.combine(clock.today(), datetime.min.time(), tzinfo=clock.TZ)
        told = db.scalar(select(func.count()).select_from(Outbox).where(
            Outbox.customer_id == customer.id, Outbox.category == "收到文件", Outbox.created_at >= today0))
        if not told:  # 每个会话每天说一次，之后静默（入口设计卡 1 规则 7）
            create_outbox(db, ctx, customer, None, text=load_config(db).text("file_refused"), category="收到文件", author="system",
                          reasons=["还没认领，不收资料"])
        return msg, None
    key = ctx.storage.save(data, folder=f"intake/{customer.id}", filename=filename)
    role = "voice" if kind == "voice" else "material"
    rec = FileRecord(
        customer_id=customer.id, order_id=order.id if order else None, role=role, filename=filename[:256], size=len(data),
        content_type=content_type[:128], storage_key=key, created_at=utcnow(),
    )
    db.add(rec)
    db.flush()
    msg = Message(
        customer_id=customer.id, order_id=order.id if order else None, direction="in", sender="customer", kind=kind,
        text=filename[:256], file_id=rec.id, channel_msgid=channel_msgid, created_at=at or utcnow(),
    )
    db.add(msg)
    db.flush()
    record_event(db, "intake.file_received", f"customer:{customer.id}", {"file": rec.id, "name": filename, "size": len(data), "kind": kind})
    _after_customer_message(db, ctx, customer, msg, run_bot=run_bot)
    if kind != "voice" and order is not None:
        refresh_status(db, ctx, order)
    return msg, rec


def receive_voice(db: Session, ctx: Ctx, customer: Customer, *, filename: str, data: bytes,
                  channel_msgid: str | None = None, at: datetime | None = None) -> Message | None:
    """语音先存文件，回一句固定的话（机器人听不了）。"""
    got = receive_file(db, ctx, customer, filename=filename, data=data, content_type="audio/amr", kind="voice",
                       channel_msgid=channel_msgid, at=at, run_bot=False)
    if got is None:
        return None
    msg, rec = got
    if rec is None:  # 还没认领，已经回过「先发激活码」了
        return msg
    order = current_order(db, customer)
    create_outbox(db, ctx, customer, order, text="语音我这边听不了，打字或者发文字稿哦", category="语音提示",
                  author="system", reasons=["客户发了语音，固定回这一句"])
    return msg


def requeue_window_failed(db: Session, customer: Customer) -> int:
    """客户又说话了，48 小时窗口重新开：之前因为窗口发不出去的（交付链接、转告制作方的话……）重新排队发。"""
    n = 0
    for ob in db.scalars(select(Outbox).where(Outbox.customer_id == customer.id, Outbox.status == "failed")):
        if ob.error.startswith(WINDOW_FAIL_PREFIXES):
            ob.status = "approved"
            ob.error = ""
            n += 1
    if n:
        record_event(db, "intake.outbox_requeued", f"customer:{customer.id}", {"count": n})
    return n


def enqueue_job(db: Session, customer: Customer, *, delay: float = 0.0) -> Job:
    """同一客户有没领的任务就把时间往后推（连发几条合成一趟）。"""
    run_after = utcnow() + timedelta(seconds=delay)
    job = db.scalar(select(Job).where(Job.customer_id == customer.id, Job.status == "pending").limit(1))
    if job is None:
        job = Job(customer_id=customer.id, run_after=run_after, created_at=utcnow(), updated_at=utcnow())
        db.add(job)
    else:
        job.run_after = run_after
        job.updated_at = utcnow()
    db.flush()
    return job


# ---------------------------------------------------------------- 待发

def create_outbox(
    db: Session, ctx: Ctx, customer: Customer, order: Order | None, *,
    text: str = "", kind: str = "text", category: str = "一般回复", author: str = "bot",
    reasons: list[str] | None = None, run_id: int | None = None, file_id: int | None = None,
    asset: str = "", approved: bool = False, send_after: datetime | None = None,
) -> Outbox:
    cfg = load_config(db)
    reasons = list(reasons or [])
    auto = False
    if approved or author == "edison":
        status = "approved"
    elif cfg.needs_approval(category):
        status = "pending"  # 设置里这一类打开了「先给我看」
    else:
        status, auto = "approved", True
    ob = Outbox(
        customer_id=customer.id, order_id=order.id if order else None, channel=customer.channel,
        recipient=customer.external_id, kind=kind, text=text, file_id=file_id, asset=asset, category=category,
        author=author, status=status, auto=auto, reasons=reasons, run_id=run_id, created_at=utcnow(),
        decided_at=utcnow() if status == "approved" else None, send_after=send_after,
    )
    db.add(ob)
    db.flush()
    customer.last_activity_at = utcnow()
    record_event(db, "intake.outbox_created", f"customer:{customer.id}", {
        "outbox": ob.id, "category": category, "status": status, "author": author, "text": text[:500],
    })
    if status == "pending":
        others = db.scalar(select(func.count()).select_from(Outbox).where(
            Outbox.customer_id == customer.id, Outbox.status == "pending", Outbox.id != ob.id,
        ))
        if not others:
            ctx.notifier.send(f"{display_name(customer)} 有一条回复等你批（{category}）：{text[:40]}", link=f"/admin/conversations/{customer.id}", level="urgent", kind="回复等你批", who=f"customer:{customer.id}")
    return ob


def approve_outbox(db: Session, ob: Outbox, *, text: str | None = None) -> Outbox:
    if ob.status not in ("pending", "failed"):
        raise ValueError(f"这条现在是「{ob.status}」，不能再批")
    if text is not None and text.strip() and text.strip() != ob.text:
        ob.original_text = ob.original_text or ob.text
        ob.text = text.strip()
    ob.status = "approved"
    ob.error = ""
    ob.decided_at = utcnow()
    record_event(db, "admin.reply_approved", f"customer:{ob.customer_id}", {
        "outbox": ob.id, "edited": bool(ob.original_text), "text": ob.text[:500],
    })
    return ob


def reject_outbox(db: Session, ob: Outbox) -> Outbox:
    if ob.status != "pending" and ob.status != "failed":
        raise ValueError(f"这条现在是「{ob.status}」，不能改成不发")
    ob.status = "rejected"
    ob.decided_at = utcnow()
    record_event(db, "admin.reply_rejected", f"customer:{ob.customer_id}", {"outbox": ob.id})
    return ob


def approved_outbox(db: Session, *, channel: str | None = None, limit: int = 50, now: datetime | None = None) -> list[Outbox]:
    """批了、到点了的（send_after 空 = 马上；接待机器人排了时间的，到点才发）。"""
    now = now or utcnow()
    stmt = (select(Outbox).where(Outbox.status == "approved", or_(Outbox.send_after.is_(None), Outbox.send_after <= now))
            .order_by(Outbox.id).limit(limit))
    if channel:
        stmt = stmt.where(Outbox.channel == channel)
    return list(db.scalars(stmt))


def mark_sent(db: Session, ob: Outbox, *, channel_msgid: str | None = None) -> Message:
    """渠道真的发出去了：待发标「已发」，客户看得到的对话里加一条。"""
    ob.status = "sent"
    ob.sent_at = utcnow()
    ob.attempts += 1
    msg = Message(
        customer_id=ob.customer_id, order_id=ob.order_id, direction="out", sender=ob.author,
        kind=ob.kind, text=ob.text, file_id=ob.file_id, asset=ob.asset, outbox_id=ob.id,
        channel_msgid=channel_msgid, created_at=ob.sent_at,
    )
    db.add(msg)
    customer = db.get(Customer, ob.customer_id)
    if customer is not None:
        customer.last_activity_at = ob.sent_at
    record_event(db, "intake.message_sent", f"customer:{ob.customer_id}", {"outbox": ob.id, "channel": ob.channel})
    db.flush()
    return msg


def mark_failed(db: Session, ob: Outbox, error: str) -> Outbox:
    ob.status = "failed"
    ob.error = error[:500]
    ob.attempts += 1
    record_event(db, "intake.send_failed", f"customer:{ob.customer_id}", {"outbox": ob.id, "error": error[:500]})
    return ob


def window_info(db: Session, customer: Customer, now: datetime | None = None) -> dict[str, Any]:
    """微信客服：客户最后一次说话后 48 小时内最多 5 条（客户再说一句就重新计）。网页聊天不限。"""
    if customer.channel != "wecom":
        return {"limited": False, "can_send": True, "sends_left": None, "hours_left": None}
    now = now or utcnow()
    last = customer.last_customer_msg_at
    if last is None:
        return {"limited": True, "can_send": False, "sends_left": 0, "hours_left": 0.0}
    hours_left = WECOM_WINDOW_HOURS - (now - last).total_seconds() / 3600
    sent = db.scalar(select(func.count()).select_from(Outbox).where(
        Outbox.customer_id == customer.id, Outbox.status == "sent", Outbox.sent_at >= last,
    )) or 0
    sends_left = max(0, WECOM_WINDOW_MAX - sent)
    return {
        "limited": True,
        "can_send": hours_left > 0 and sends_left > 0,
        "sends_left": sends_left if hours_left > 0 else 0,
        "hours_left": round(max(0.0, hours_left), 1),
    }


# ---------------------------------------------------------------- 订单动作（后台调）

EDITABLE_FIELDS = (
    "occasion", "title", "duration_min", "duration_default", "duration_confirmed", "present_date",
    "present_date_text", "school", "language", "structure_req", "requirement_quotes", "paper_count", "page_count",
)


def update_order(db: Session, ctx: Ctx, order: Order, changes: dict[str, Any], *, by: str = "edison") -> Order:
    applied: dict[str, Any] = {}
    for k, v in changes.items():
        if k not in EDITABLE_FIELDS:
            continue
        setattr(order, k, v)
        applied[k] = v.isoformat() if isinstance(v, date) else v
    if applied:
        _touch(order)
        record_event(db, "intake.order_updated", f"order:{order.id}", {"by": by, "changes": applied})
        if "occasion" in applied:  # 场合定了（需求卡确认、后台改）：这个场合要的资料一次发全
            send_materials_list(db, ctx, order, via=by)
        refresh_status(db, ctx, order)
    return order


def materials_list_due(db: Session, order: Order, ctx: Any = None) -> bool:
    """该不该把这个场合的资料清单发一遍：还在收资料、没排上、场合知道了、这个场合没发过、资料还没齐。"""
    if order.stage not in ("claimed", "collecting") or order.started_at is not None or order.queued_at is not None:
        return False
    if not order.customer_id or not order.occasion or load_config(db).rule(order.occasion) is None:
        return False
    if materials.listed(db, order.id, order.occasion):
        return False
    return not collect_for(db, order, ctx).complete


def materials_list_text(db: Session, order: Order, ctx: Any = None, facts: OrderFacts | None = None) -> str:
    """这单这个场合要的资料，完整一遍（收到的标「收到了」，说过的几样不再列）。字全从设置里的资料清单来。"""
    cfg = load_config(db)
    facts = facts or order_facts(db, order)
    collect = collect_for(db, order, ctx)
    return materials.occasion_text(
        cfg, facts.occasion or order.occasion, head="order", find_refs=facts.find_refs,
        have={f.purpose for f in facts.files if f.purpose}, done_keys={it.key for it in collect.items if it.done},
        req_keys=materials.required_keys(cfg, facts.sku, facts.addons))


def send_materials_list(db: Session, ctx: Ctx, order: Order, *, via: str) -> Outbox | None:
    """场合定了以后一次把这个场合要的资料完整发一遍（Edison 11-19：开工之前要跟他讲清楚要拿到什么资料），之后按缺的一样样追。
    每单每个场合只发一次（认领那句话里带全了也算）；资料已经齐了就不发。"""
    if not materials_list_due(db, order, ctx):
        return None
    customer = db.get(Customer, order.customer_id)
    text = materials_list_text(db, order, ctx)
    if customer is None or not text:
        return None
    ob = create_outbox(db, ctx, customer, order, text=text, asset="materials", category="资料清单", author="system",
                       reasons=["场合定了：这个场合要的资料一次发全（设置里的资料清单，一字不改）", f"materials:{order.occasion}"])
    materials.mark_listed(db, order.id, order.occasion, via=via)
    return ob


def set_rush(db: Session, ctx: Ctx, order: Order, value: bool) -> Order:
    """后台给加急 / 收回后台给的加急（不看名额、材料；付了码的加急由 gate.ready 判断）。已经排上的单不改排期。"""
    from app.intake.orders import apply_addon, remove_manual_addon

    if value:
        if not any(a.get("key") == "rush" and a.get("by") == "edison" for a in (order.addons or [])):
            apply_addon(db, ctx, order, "rush", by="edison")
    else:
        remove_manual_addon(db, order, "rush", by="edison")
        if order.queued_at is None:
            order.rush = False
    _touch(order)
    record_event(db, "admin.order_rush", f"order:{order.id}", {"value": value})
    refresh_status(db, ctx, order)
    return order


def resolve_need(db: Session, order: Order, index: int) -> None:
    needs = list(order.needs_edison or [])
    if 0 <= index < len(needs):
        needs[index] = {**needs[index], "resolved": True}
        order.needs_edison = needs
        record_event(db, "admin.need_resolved", f"order:{order.id}", {"index": index})


def set_takeover(db: Session, ctx: Ctx, customer: Customer, on: bool) -> Customer:
    customer.human_takeover = on
    record_event(db, "admin.takeover", f"customer:{customer.id}", {"on": on})
    if not on:
        # 交还机器人：如果期间客户说过话，让机器人接着看
        newest = db.scalar(select(func.max(Message.id)).where(
            Message.customer_id == customer.id, Message.direction == "in"))
        if newest and newest > customer.bot_seen_msg_id:
            enqueue_job(db, customer, delay=0)
    return customer


def handoff_due_orders(db: Session, ctx: Ctx, *, today: date | None = None) -> list[int]:
    """排到今天（或更早）的单再判断一次（工人每分钟调）：今天名额没满就进「制作中」交接给工厂。"""
    today = today or clock.today()
    due = list(db.scalars(
        select(Order).where(Order.stage == "collecting", Order.queued_at.is_not(None), Order.started_at.is_(None),
                            Order.start_date <= today).order_by(Order.queued_at)
    ))
    done: list[int] = []
    for o in due:
        refresh_status(db, ctx, o, announce=False)
        if o.started_at is not None:
            done.append(o.id)
    return done


def start_now(db: Session, ctx: Ctx, order: Order) -> Order:
    """Edison 点「现在开工」：流程里「收资料 → 制作中」那条手动连线（条件不齐也照做，事件里记下当时缺什么）。"""
    from app.intake import brief

    if order.started_at is not None:
        raise ValueError("这单已经交接过了")
    if not brief.confirmed(db, order):  # 没确认不开工（09 需求引导）：先让客人点「对，开工」，或在需求卡上代客人确认
        raise ValueError("需求卡还没确认：客人点「对，开工」，或你在需求卡上代客人确认（写明依据）之后才能开工")
    cfg = load_config(db)
    conds = conditions_for(db, order, cfg)
    record_event(db, "admin.start_now", f"order:{order.id}", {"conditions": [c.__dict__ for c in conds]})
    flow.push(db, ctx, order, "start_now", by="edison", why="后台点了现在开工")
    return order


def prepare_handoff(db: Session, order: Order) -> None:
    """交接前补齐排期（后台「现在开工」时可能还没排）：开工日今天、承诺时限。"""
    if order.queued_at is not None and order.due_hours:
        return
    cfg = load_config(db)
    facts = order_facts(db, order)
    order.queued_at = order.queued_at or utcnow()
    order.start_date = order.start_date or clock.today()
    order.due_hours = order.due_hours or due_hours(facts, cfg, rush=order.rush)


def add_deliverable(db: Session, ctx: Ctx, order: Order, *, filename: str, data: bytes, kind: str = "PPT",
                    content_type: str = "", page_no: int | None = None, round_no: int | None = None) -> FileRecord:
    """存一个成品文件（开放给模块 E）。kind：PPT / 讲稿 / PDF / 可编辑图 / 其他 = 最终版（订单到「已完成」才发）；
    水印版 = 给客人先看的；页图 = 整页底图（role=page，只给出水印图用，任何接口都不返回）。round 默认是下一版。"""
    key = ctx.storage.save(data, folder=f"deliverables/{order.id}", filename=filename)
    rec = FileRecord(
        customer_id=order.customer_id or 0, order_id=order.id, role="page" if kind == PAGE_KIND else "deliverable",
        filename=filename[:256], size=len(data), content_type=content_type[:128], storage_key=key,
        purpose=kind, page_no=page_no, round=round_no if round_no is not None else order.delivery_round + 1,
        created_at=utcnow(),
    )
    db.add(rec)
    if order.ready_at is None or order.delivered_at is not None:
        order.ready_at = utcnow()
    db.flush()
    record_event(db, "admin.deliverable_added", f"order:{order.id}", {"file": rec.id, "name": filename, "round": rec.round, "kind": kind})
    return rec


def round_files(db: Session, order: Order, round_no: int, *, role: str = "deliverable", kind: str | None = None) -> list[FileRecord]:
    stmt = select(FileRecord).where(FileRecord.order_id == order.id, FileRecord.role == role, FileRecord.round == round_no)
    if kind is not None:
        stmt = stmt.where(FileRecord.purpose == kind)
    return list(db.scalars(stmt.order_by(FileRecord.page_no, FileRecord.id)))


def unpublished_files(db: Session, order: Order) -> list[FileRecord]:
    """下一版（delivery_round + 1）里已经存了、还没发布也没放出的成品和整页图：客人一张都没见过。"""
    nxt = order.delivery_round + 1
    return list(db.scalars(select(FileRecord).where(
        FileRecord.order_id == order.id, FileRecord.round == nxt, FileRecord.role.in_(("deliverable", "page")))
        .order_by(FileRecord.id)))


def discard_unpublished(db: Session, ctx: Ctx, order: Order, *, by: str, why: str, keep_ids: set[int] | None = None) -> list[str]:
    """作废还没发布的那一版文件（开放给模块 E、后台）：重交一版、传错了重来时，旧的 pptx、整页图、水印图删掉，
    免得同一版里两份 pptx 一起放出去、旧页图混进新一版。已经发布、放出的版次一张不动（版次 ≤ delivery_round）。
    只删库里的记录（存储里的文件留着：同一个事务没提交前删了就回不来）。返回删掉的文件名。"""
    keep = keep_ids or set()
    rows = [f for f in unpublished_files(db, order) if f.id not in keep]
    if not rows:
        return []
    names = [f.filename for f in rows]
    record_event(db, "intake.deliverables_discarded", f"order:{order.id}", {
        "round": order.delivery_round + 1, "files": names, "ids": [f.id for f in rows], "why": why[:200], "by": by})
    for f in rows:
        db.delete(f)
    db.flush()
    return names


def submit_package(db: Session, ctx: Ctx, order: Order, *, by: str, note: str = "") -> int:
    """制作方（或后台）交了这一版成品包（deliver.receive 节点）：检查齐不齐，发流程事件 package_received。
    制作中、修改中：要有整页图（出水印图用）和可编辑的 PPT；已完成、已交付后再改：要有最终版。返回第几版。"""
    nxt = order.delivery_round + 1
    finals = [f for f in round_files(db, order, nxt) if f.purpose != PREVIEW_KIND]
    pages = round_files(db, order, nxt, role="page")
    after = order.stage in ("completed", "delivered") or order.flow_step == "revising_after"
    if not after:
        if not pages:
            raise ValueError("这一版没有整页图（每页一张，长边 1600 以上）：出水印图要用，不能只交 pptx")
        if not any(f.purpose == "PPT" for f in finals):
            raise ValueError("这一版没有可编辑的 PPT：最终版要先锁在库里，确认收货后才发")
    elif not finals:
        raise ValueError("没有最终版文件（pptx、讲稿）")
    if not flow.accepts(order, "package_received"):
        raise ValueError(f"这单现在是「{flow.stage_label(order)}」，不收成品")
    record_event(db, "delivery.package_received", f"order:{order.id}", {
        "round": nxt, "pages": len(pages), "finals": [f.filename for f in finals], "note": note[:300], "by": by})
    flow.emit(db, ctx, order, "package_received", by=by, why=f"交了第 {nxt} 版成品", data={"round": nxt})
    return nxt


def publish_preview(db: Session, ctx: Ctx, order: Order, *, by: str) -> Outbox | None:
    """deliver.preview 发布：这一版水印版发给客人（只发交付页链接，不发最终版），交过的版数 + 1。"""
    nxt = order.delivery_round + 1
    if order.hold_reason:
        raise ValueError(f"暂停中（{order.hold_reason}），先不交这一版")
    if not round_files(db, order, nxt, kind=PREVIEW_KIND):
        raise ValueError("这一版还没有水印图")
    if order.customer_id is None:
        raise ValueError("这单还没人认领，交给谁？")
    order.delivery_round = nxt
    order.delivered_at = utcnow()
    for rev in db.scalars(select(Revision).where(Revision.order_id == order.id, Revision.status == "open")):
        rev.status = "done"
    _touch(order)
    customer = db.get(Customer, order.customer_id)
    cfg = load_config(db)
    platform_names = {"xhs": "小红书", "dy": "抖音", "xy": "闲鱼"}
    self_confirm = "customer" in cfg.delivery.sources(order.platform or "legacy")
    key = "publish_self" if self_confirm else "publish_platform"
    tpl = cfg.delivery.texts.get(key) or "第 {round} 版做好了，先给你看预览：{url}"
    try:
        text = tpl.format(round=nxt, url=ctx.delivery_url(order), platform_name=platform_names.get(order.platform, "平台"))
    except (KeyError, IndexError):
        text = tpl
    record_event(db, "delivery.proof_published", f"order:{order.id}", {"round": nxt, "by": by})
    if order.platform_completed_at is not None:
        return None  # 平台早就确认收货了：流程接着直接放最终版，那条消息里一起说
    return create_outbox(db, ctx, customer, order, text=text, category="交付", author="system",
                         reasons=[f"第 {nxt} 版水印版，只发交付页链接"])


def cancel_order(db: Session, ctx: Ctx, order: Order, *, by: str = "edison", why: str = "") -> Order:
    """客户开工前撤单：作废，码退回还能用（注意事项第 6 条）。开工后不退（要退款走「退款，码作废」）。"""
    from app.intake.orders import void_order

    return void_order(db, ctx, order, code_action="return", by=by, why=why or "开工前撤单")


# ---------------------------------------------------------------- 交付页（delivery 调）

_PAGE_HEAD = re.compile(r"^\s*(?:\d+[.、)）]\s*)?第\s*(\d{1,3})\s*页\s*[：:，,的]?\s*(.*)$", re.S)


def split_revision_text(text: str) -> list[dict[str, Any]]:
    """交付页只给了一段话：按行、分号拆成几条，开头写了「第 N 页」的记成那一页，其他的算整体意见。"""
    out: list[dict[str, Any]] = []
    for piece in re.split(r"[\n；;]+", text or ""):
        piece = piece.strip()
        if not piece:
            continue
        m = _PAGE_HEAD.match(piece)
        if m and m.group(2).strip():
            out.append({"page": int(m.group(1)), "text": m.group(2).strip()})
        else:
            out.append({"page": None, "text": piece})
    return out


def revision_text(items: list[dict[str, Any]]) -> str:
    lines = []
    for i, it in enumerate(items, start=1):
        page = it.get("page")
        lines.append(f"{i}. {'第 ' + str(page) + ' 页' if page else '整体'}：{str(it.get('text', '')).strip()}")
    return "\n".join(lines)


def submit_revision(db: Session, ctx: Ctx, order: Order, *, text: str = "", files: list[tuple[str, bytes, str]] | None = None,
                    items: list[dict[str, Any]] | None = None, source: str = "delivery") -> Revision:
    """提修改（revision.collect，开放给模块 E 和助手工具）。逐页收：items=[{page, text}]（page 空 = 整体意见）；只给一段话也行。
    还有轮数（含的 + 加购的）：整理成改稿单交给制作方，流程进「修改中」（已交付后还剩轮数的进「已交付后再改」）。
    轮数用完了：记下来（后台看得到），不交给制作方；客户要再改得买「再改一轮」的码或加负责人微信。"""
    files = files or []
    if order.delivered_at is None:
        raise ValueError("还没交付，不能提修改")
    if order.stage not in ("watermarked", "revising", "delivered"):
        raise ValueError(f"这单现在是「{flow.stage_label(order)}」，不能再提修改")
    items = [i for i in (items or []) if str(i.get("text", "")).strip()]
    if not items and text.strip():
        items = split_revision_text(text)
    if not items:
        raise ValueError("说一下改哪一页、改成什么")
    body_text = revision_text(items)
    free = revisions_left(order, load_config(db)) > 0
    ids: list[int] = []
    for name, data, ctype in files:
        key = ctx.storage.save(data, folder=f"revisions/{order.id}", filename=name)
        rec = FileRecord(customer_id=order.customer_id or 0, order_id=order.id, role="revision", filename=name[:256],
                         size=len(data), content_type=ctype[:128], storage_key=key, created_at=utcnow())
        db.add(rec)
        db.flush()
        ids.append(rec.id)
    rev = Revision(order_id=order.id, text=body_text[:8000], items=items, based_on_round=order.delivery_round,
                   file_ids=ids, free=free, created_at=utcnow())
    db.add(rev)
    customer = db.get(Customer, order.customer_id) if order.customer_id else None
    who = display_name(customer) if customer else f"#{order.id}"
    if free:
        order.revision_used = (order.revision_used or 0) + 1
        names = "、".join(n for n, _, _ in files)
        hours = load_config(db).delivery.revision_hours
        body = (f"改稿单 · 第 {order.delivery_round} 版 → 第 {order.delivery_round + 1} 版"
                f"（客户{'在交付页' if source == 'delivery' else '在聊天里'}提的）· 请在 {hours} 小时内交下一版\n{body_text}"
                "\n页码 = 水印版底栏的「第 N 页」= pptx 第 N 张。")
        if names:
            body += f"\n附件：{names}"
        add_production_message(db, order, "to_maker", "改稿单", body, author="bot" if source == "bot" else "system", file_ids=ids)
        ctx.notifier.send(f"{who} 提了修改，改稿单交给制作方了：{body_text[:60]}", link="/admin/orders", level="digest", kind="提了修改", who=f"order:{order.id}")
    else:
        add_need(order, "再改", body_text)
        ctx.notifier.send(f"{who} 修改次数用完了还想改：{body_text[:60]}", link=f"/admin/conversations/{order.customer_id}", level="urgent", kind="修改次数用完", who=f"order:{order.id}")
    _touch(order)
    db.flush()
    record_event(db, "delivery.revision", f"order:{order.id}", {"revision": rev.id, "free": free, "files": ids, "source": source,
                                                                "items": len(items)})
    if free:
        flow.emit(db, ctx, order, "revision", by="customer" if source == "delivery" else source, why="交了改稿单")
    return rev


def confirm_received(db: Session, ctx: Ctx, order: Order) -> Order:
    """客户在交付页点「确认收货」→ 订单到「已完成」，接着发最终版。"""
    from app.intake.orders import mark_completed

    return mark_completed(db, ctx, order, source="customer", by="customer")


def submit_feedback(db: Session, ctx: Ctx, order: Order, data: dict[str, Any]) -> Order:
    order.feedback = {**data, "at": utcnow().isoformat()}
    record_event(db, "delivery.feedback", f"order:{order.id}", data)
    customer = db.get(Customer, order.customer_id)
    ctx.notifier.send(f"{display_name(customer)} 留了反馈：{str(data.get('comment', ''))[:60]}", link=f"/admin/conversations/{order.customer_id}", level="urgent", kind="客人反馈", who=f"order:{order.id}")
    return order


# ---------------------------------------------------------------- 制作方会话（记账；对外接口在 production.py）

def add_production_message(db: Session, order: Order, direction: str, kind: str, text: str, *,
                           author: str = "bot", file_ids: list[int] | None = None,
                           relayed: bool = False) -> ProductionMessage:
    m = ProductionMessage(order_id=order.id, direction=direction, kind=kind, author=author, text=text[:20000],
                          file_ids=list(file_ids or []), created_at=utcnow(),
                          relayed_at=utcnow() if relayed else None)
    db.add(m)
    db.flush()
    record_event(db, "intake.production_message", f"order:{order.id}",
                 {"message": m.id, "direction": direction, "kind": kind, "author": author, "text": text[:300]})
    return m


def production_messages(db: Session, order: Order) -> list[ProductionMessage]:
    return list(db.scalars(select(ProductionMessage).where(ProductionMessage.order_id == order.id)
                           .order_by(ProductionMessage.id)))


def unrelayed_from_maker(db: Session, customer: Customer) -> list[ProductionMessage]:
    """制作方发来、机器人还没转告客户的（成品不在里面：成品自动交付）。"""
    order_ids = list(db.scalars(select(Order.id).where(Order.customer_id == customer.id)))
    if not order_ids:
        return []
    return list(db.scalars(select(ProductionMessage).where(
        ProductionMessage.order_id.in_(order_ids), ProductionMessage.direction == "to_sales",
        ProductionMessage.relayed_at.is_(None)).order_by(ProductionMessage.id)))


# ---------------------------------------------------------------- 发给客户的固定图片

ASSETS = ("pay_qr", "owner_qr", "service_qr")


def asset_path(db: Session, ctx: Ctx, asset: str) -> Path | None:
    """发给客户的固定图片在本机哪：付款二维码（设置页填的路径，没填用 PAY_QR_IMAGE）、负责人微信二维码。"""
    p: Path | str | None = None
    if asset == "pay_qr":
        p = load_config(db).payment.qr_image or ctx.settings.PAY_QR_IMAGE
    elif asset == "owner_qr":
        p = ctx.settings.OWNER_WECHAT_QR
    elif asset == "service_qr":
        p = ctx.settings.SERVICE_QR_IMAGE
    if not p:
        return None
    path = Path(p)
    if path.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp", ".gif") or not path.is_file():
        return None
    return path
