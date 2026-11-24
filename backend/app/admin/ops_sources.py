"""把各业务模块的读数登记进运维的接口位（app/ops/sources.py）。运维只依赖 core，业务读数由后台这一层（admin 能依赖全部）接上。

全部只读。登记的五种（设计 docs/任务单/07_运维与数据_设计.md 第三节）：
- gauge：水印出图队列（delivery 的版本表）、做单产能（订单状态）、付款通知缺失（shop 的付款单和通知表）、底座任务队列（有的话）
- todo：渠道与收款的「该看一眼」（复用 platforms.service.due 和 /api/admin/shop/due 的同一份逻辑）、待开票、超时没交的单、发送失败的回复、
  聚人的待看截图和待贴网盘链接、版权下架申请
- suggestion：图库的标签反馈、提需求、投图、网站意见（交付页的修改意见不是建议，不在这里）
- external：DeepSeek、微信支付、支付宝、微信客服（只说配没配、连哪个地址；不碰密钥）
- lifecycle：过了保存期限的客户材料、水印图、最终版、聊天记录有多少（只数）
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.admin.shop_router import due as shop_due
from app.core.db import utcnow
from app.core.nodes import NodeCall
from app.core.redact import redact_text
from app.delivery import sla
from app.delivery.models import DeliveryVersion
from app.delivery.settings import DeliverySettings
from app.figures.inbox import FEEDBACK_REASONS
from app.figures.models import FigureFeedback, FigureRequest, FigureSubmission, SiteFeedback
from app.intake.models import PREVIEW_KIND, FileRecord, Message, Order, Outbox
from app.intake.runtime import get_runtime
from app.invoices.models import InvoiceRequest
from app.ops import sources
from app.ops.config import load_config
from app.ops.sources import ExternalTarget, Gauge, LifecycleRow, SuggestionGroup, TodoGroup
from app.platforms import service as platforms_service
from app.shop.models import ShopCheckout, ShopNotification
from app.shop.settings import ShopSettings


def _short(text: str, n: int = 28) -> str:
    t = redact_text(" ".join(str(text or "").split()))
    return t if len(t) <= n else t[: n - 1] + "…"


# ---------------------------------------------------------------- gauge

def watermark_gauges(db: Session, app: Any) -> list[Gauge]:
    now = utcnow()
    p = load_config(db).rule("watermark_backlog")["params"]
    rendering = list(db.scalars(select(DeliveryVersion).where(DeliveryVersion.status == "rendering")))
    oldest = min((v.created_at for v in rendering), default=None)
    failed = db.scalar(select(func.count()).select_from(DeliveryVersion).where(
        DeliveryVersion.status == "failed", DeliveryVersion.updated_at >= now - timedelta(hours=p["failed_hours"]))) or 0
    done = list(db.execute(select(DeliveryVersion.created_at, DeliveryVersion.rendered_at).where(
        DeliveryVersion.rendered_at.is_not(None), DeliveryVersion.rendered_at >= now - timedelta(hours=24))))
    avg = sum((r - c).total_seconds() for c, r in done) / len(done) if done else None
    link = "/admin/orders"
    return [Gauge(key="watermark.rendering", label="水印在排", value=len(rendering), unit="版", link=link),
            Gauge(key="watermark.oldest_wait_min", label="最老的等了", value=round((now - oldest).total_seconds() / 60, 1) if oldest else 0,
                  unit="分钟", link=link),
            Gauge(key="watermark.failed_24h", label="出图失败", value=int(failed), unit="版", link=link),
            Gauge(key="watermark.avg_sec", label="收包到出完图（24 小时平均）", value=round(avg, 1) if avg is not None else None, unit="秒")]


def capacity_gauges(db: Session, app: Any) -> list[Gauge]:
    rows = dict(db.execute(select(Order.stage, func.count()).group_by(Order.stage)).all())
    making = rows.get("making", 0) + rows.get("revising", 0)
    waiting = rows.get("claimed", 0) + rows.get("collecting", 0)
    return [Gauge(key="capacity.making", label="在做", value=making, unit="单", link="/admin/orders"),
            Gauge(key="capacity.waiting", label="已认领、收资料中", value=waiting, unit="单", link="/admin/orders"),
            Gauge(key="capacity.unclaimed", label="付了还没认领", value=rows.get("paid", 0), unit="单", link="/admin/orders")]


def pay_gauges(db: Session, app: Any) -> list[Gauge]:
    p = load_config(db).rule("pay_notify_silent")["params"]
    now = utcnow()
    paid = list(db.scalars(select(ShopCheckout).where(
        ShopCheckout.paid_at.is_not(None), ShopCheckout.paid_at >= now - timedelta(hours=p["window_hours"]),
        ShopCheckout.paid_at <= now - timedelta(minutes=p["after_minutes"]))))
    if not paid:
        return [Gauge(key="pay.notify_missing", label="付款通知没到", value=0, unit="笔", link="/admin/channels")]
    got = set(db.scalars(select(ShopNotification.out_trade_no).where(
        ShopNotification.kind == "pay", ShopNotification.out_trade_no.in_([c.out_trade_no for c in paid]))))
    missing = [c for c in paid if c.out_trade_no not in got]
    nodes = sorted({c.pay_node for c in missing})
    return [Gauge(key="pay.notify_missing", label="付款通知没到", value=len(missing), unit="笔", link="/admin/channels",
                  detail=("网关：" + "、".join(nodes)) if nodes else "")]


def task_gauges(db: Session, app: Any) -> list[Gauge]:
    """底座的统一任务队列（07_底座可扩展合并之后才有；没有就不出数）。"""
    try:
        from app.core.tasks import metrics as task_metrics  # type: ignore[attr-defined]
    except ImportError:
        return []
    m = task_metrics(app.state.db)
    out = []
    for k in ("pending", "dead", "oldest_wait_sec"):
        if isinstance(m.get(k), (int, float)):
            out.append(Gauge(key=f"tasks.{k}", label=f"后台任务 {k}", value=float(m[k])))
    return out


# ---------------------------------------------------------------- todo

CHANNEL_KINDS = {
    "verify": ("待核对订单号", "urgent"), "paste": ("待贴发货文案", "urgent"), "problem": ("平台录单出问题", "urgent"),
    "completion": ("平台单很久没点「已完成」", "today"), "price": ("平台标价和设置对不上", "today"),
    "paid_no_code": ("付了钱没发出码", "urgent"), "bad_notify": ("对不上的支付通知", "today"), "refund_stuck": ("退款卡住", "urgent"),
}


def channel_todos(db: Session, app: Any) -> list[TodoGroup]:
    items = platforms_service.due(NodeCall(db, get_runtime(app).ctx, "system:ops")) + shop_due(db)["items"]
    by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for it in items:
        by[it.get("kind", "other")].append(it)
    out = []
    for kind, rows in by.items():
        label, level = CHANNEL_KINDS.get(kind, (kind, "today"))
        out.append(TodoGroup(kind=f"channels.{kind}", label=label, count=len(rows), link="/admin/channels", level=level,
                             latest=[_short(r.get("title", ""), 40) for r in rows[:5]]))
    return out


def invoice_todos(db: Session, app: Any) -> list[TodoGroup]:
    rows = list(db.scalars(select(InvoiceRequest).where(InvoiceRequest.flow_step == "pending").order_by(InvoiceRequest.requested_at)))
    return [TodoGroup(kind="invoices.pending", label="待开票", count=len(rows), link="/admin/invoices",
                      latest=[f"单号 {r.order_id:05d} {r.amount or ''}".strip() for r in rows[:5] if r.order_id])]


def overdue_todos(db: Session, app: Any) -> list[TodoGroup]:
    ds: DeliverySettings = getattr(app.state, "delivery_settings", None) or DeliverySettings()
    warn = float(getattr(ds, "DELIVERY_SLA_WARN_RATIO", 0.8))
    late = []
    for oid in sla.watching(db):
        o = db.get(Order, oid)
        if o is not None and sla.facts(db, o, warn_ratio=warn).state == "late":
            late.append(o)
    return [TodoGroup(kind="orders.late", label="过了承诺时间还没交第一版", count=len(late), link="/admin/orders", level="urgent",
                      latest=[f"#{o.id} {_short(o.title, 20)}" for o in late[:5]])]


def gather_todos(db: Session, app: Any) -> list[TodoGroup]:
    """聚人（模块 L）：等负责人看的转发截图、通过了但还没贴网盘链接、版权下架申请（48 小时内要撤）。"""
    from app.figures.models import DECISION_NEW, FigureTakedown
    from app.gather.models import FigureUnlock

    steps = dict(db.execute(select(FigureUnlock.flow_step, func.count()).where(
        FigureUnlock.flow_step.in_(("review", "wait_pack"))).group_by(FigureUnlock.flow_step)).all())
    takedowns = list(db.scalars(select(FigureTakedown).where(FigureTakedown.decision == DECISION_NEW).order_by(FigureTakedown.id)))
    return [
        TodoGroup(kind="gather.review", label="等你看的转发截图", count=int(steps.get("review", 0)), link="/admin/gather"),
        TodoGroup(kind="gather.wait_pack", label="核验过了、还没贴网盘链接", count=int(steps.get("wait_pack", 0)), link="/admin/gather"),
        TodoGroup(kind="figures.takedown", label="版权下架申请（48 小时内要撤）", count=len(takedowns), link="/admin/gather", level="urgent",
                  latest=[_short(t.holder or t.figures_text, 24) for t in takedowns[:5]]),
    ]


def outbox_todos(db: Session, app: Any) -> list[TodoGroup]:
    n = db.scalar(select(func.count()).select_from(Outbox).where(Outbox.status == "failed")) or 0
    return [TodoGroup(kind="conversations.failed", label="发给客人没发出去的消息", count=int(n), link="/admin/conversations")]


# ---------------------------------------------------------------- suggestion

def figure_suggestions(db: Session, start: datetime, end: datetime) -> list[SuggestionGroup]:
    def rows(model: Any) -> list[Any]:
        return list(db.scalars(select(model).where(model.created_at >= start, model.created_at < end).order_by(model.id.desc())))

    fb, rq, sb, st = rows(FigureFeedback), rows(FigureRequest), rows(FigureSubmission), rows(SiteFeedback)
    return [
        SuggestionGroup(kind="feedback", label="标签反馈", count=len(fb), link="/admin/figures/feedback",
                        latest=[f"图 {r.figure_id} {FEEDBACK_REASONS.get(r.reason, r.reason)}" + (f"：{_short(r.note, 20)}" if r.note else "")
                                for r in fb[:5]]),
        SuggestionGroup(kind="requests", label="提需求", count=len(rq), link="/admin/figures/requests", latest=[_short(r.want) for r in rq[:5]]),
        SuggestionGroup(kind="submissions", label="投图", count=len(sb), link="/admin/figures/submissions",
                        latest=[_short(r.source) for r in sb[:5]]),
        SuggestionGroup(kind="site", label="网站意见", count=len(st), link="/admin/figures/site", latest=[_short(r.content) for r in st[:5]]),
    ]


# ---------------------------------------------------------------- external

def externals(app: Any) -> list[ExternalTarget]:
    s = app.state.settings
    shop: ShopSettings = getattr(app.state, "shop_settings", None) or ShopSettings()
    from app.channels.settings import ChannelsSettings

    ch: ChannelsSettings = getattr(app.state, "channels_settings", None) or ChannelsSettings()
    return [
        ExternalTarget(key="deepseek", label="DeepSeek（助手）", url=s.LLM_BASE_URL or "https://api.deepseek.com", configured=bool(s.LLM_BASE_URL)),
        ExternalTarget(key="wechatpay", label="微信支付", url=shop.WECHATPAY_API_BASE, configured=bool(shop.WECHATPAY_MCHID)),
        ExternalTarget(key="alipay", label="支付宝", url=shop.ALIPAY_GATEWAY, configured=bool(shop.ALIPAY_APP_ID)),
        ExternalTarget(key="wecom", label="微信客服", url=ch.WECOM_API_BASE, configured=bool(s.WECOM_CORPID)),
    ]


# ---------------------------------------------------------------- lifecycle

def lifecycle_rows(db: Session, items: list[Any]) -> list[LifecycleRow]:
    now = utcnow()
    out = []
    for it in items:
        if it.days is None or it.key not in ("materials", "watermark", "finals", "chat"):
            out.append(LifecycleRow(key=it.key, label=it.label, days=it.days, expired=None, note=it.how))
            continue
        cut = now - timedelta(days=it.days)
        if it.key == "chat":
            n = db.scalar(select(func.count()).select_from(Message).where(Message.created_at < cut)) or 0
        else:
            q = select(func.count()).select_from(FileRecord).join(Order, FileRecord.order_id == Order.id).where(
                or_(Order.finished_at < cut, Order.voided_at < cut))
            if it.key == "materials":
                q = q.where(FileRecord.role == "material")
            elif it.key == "watermark":
                q = q.where(or_(FileRecord.role == "page", FileRecord.purpose == PREVIEW_KIND))
            else:
                q = q.where(FileRecord.role == "deliverable", FileRecord.purpose != PREVIEW_KIND)
            n = db.scalar(q) or 0
        out.append(LifecycleRow(key=it.key, label=it.label, days=it.days, expired=int(n), note=it.how))
    return out


def register_all() -> None:
    sources.register("gauge", "watermark", watermark_gauges)
    sources.register("gauge", "capacity", capacity_gauges)
    sources.register("gauge", "pay", pay_gauges)
    sources.register("gauge", "tasks", task_gauges)
    sources.register("todo", "channels", channel_todos)
    sources.register("todo", "invoices", invoice_todos)
    sources.register("todo", "overdue", overdue_todos)
    sources.register("todo", "outbox", outbox_todos)
    sources.register("todo", "gather", gather_todos)
    sources.register("suggestion", "figures", figure_suggestions)
    sources.register("external", "business", externals)
    sources.register("lifecycle", "intake", lifecycle_rows)
