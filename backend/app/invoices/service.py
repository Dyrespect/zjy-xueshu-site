"""开票的业务函数（节点、接口共用；节点文件之间不互相 import，共用的都放这里）。设计第五节。

发票申请是能走流程的对象 invoice（流程 flows/invoice_basic.json，订单中枢的引擎驱动；flow_step / stage 只有引擎写）。
这里管：校验和存申请、付款前预填挂到订单上、驳回 / 作废 / 撤回、存发票文件、给页面的视图。
在办的申请占着这单（active_order_id 唯一），每次走完流程都按状态同步一次（sync_active）。
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.events import record_event
from app.intake import flow
from app.intake.models import Order
from app.invoices.checks import InvoiceCheckFailed, clean_fields, fmt, money, require_amount_within_paid, require_invoice_file
from app.invoices.config import FIELD_LABELS, InvoiceConfig, load_config
from app.invoices.facts import PLATFORM_NAMES, judge
from app.invoices.models import (
    ACTIVE_STAGES,
    FLOW_KEY,
    KIND_LABELS,
    SOURCE_LABELS,
    TITLE_KIND_LABELS,
    InvoiceFile,
    InvoiceNotice,
    InvoiceRequest,
)

# 发票申请登记成能走流程的对象；流程文件夹登记给引擎（契约第四节第 4 条「L 聚人」那条路）
flow.register_subject(flow.SubjectSpec("invoice", InvoiceRequest, None, stage_event="invoice.stage", by_id="invoice_id"))
flow.register_flow_dir(Path(__file__).parent / "flows")

CUSTOMER_FIELDS = ("title", "tax_id", "email", "bank_name", "bank_account", "address", "phone", "remark")
STEP_NOTES = {
    "waiting": "已填好，订单完成（确认收货）后自动提交开票",
    "pending": "已提交，等待开票",
    "issued": "发票开好了",
    "rejected": "没开成",
    "blocked": "没开成",
    "voided": "这张发票作废了",
    "cancelled": "已撤回",
}


def order_no(order_id: int | None) -> str:
    return f"{order_id:05d}" if order_id else ""


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def sync_active(inv: InvoiceRequest) -> None:
    """在办的（等订单完成 / 待开票 / 已开票）占着这单；驳回、作废、撤回后让出来，可以重新申请。"""
    inv.active_order_id = inv.order_id if inv.order_id and inv.stage in ACTIVE_STAGES else None


def active_for(db: Session, order_id: int) -> InvoiceRequest | None:
    return db.scalar(select(InvoiceRequest).where(InvoiceRequest.active_order_id == order_id))


def history_for(db: Session, order_id: int) -> list[InvoiceRequest]:
    return list(db.scalars(select(InvoiceRequest).where(InvoiceRequest.order_id == order_id).order_by(InvoiceRequest.id.desc())))


def files_of(db: Session, invoice_id: int) -> list[InvoiceFile]:
    return list(db.scalars(select(InvoiceFile).where(InvoiceFile.invoice_id == invoice_id).order_by(InvoiceFile.id)))


# ---------------------------------------------------------------- 申请

def validate(cfg: InvoiceConfig, data: dict[str, Any]) -> tuple[str, str, dict[str, str]]:
    """（发票类型, 抬头类型, 规整后的字段）。专票没开、个人抬头没开都在这里拦。"""
    kind = data.get("kind") or "normal"
    title_kind = data.get("title_kind") or "unit"
    see = "docs/任务单/07_开票_设计.md 第四节"
    if kind not in cfg.kinds():
        raise InvoiceCheckFailed("现在只开电子普通发票", "发票类型选「电子普通发票」；要专票请联系负责人", see, field="kind")
    if title_kind not in ("unit", "personal") or (title_kind == "personal" and not cfg.allow_personal):
        raise InvoiceCheckFailed("现在只开单位抬头", "抬头填单位全称、税号填单位的统一社会信用代码", see, field="title_kind")
    fields = clean_fields(data, kind=kind, title_kind=title_kind, required=cfg.required(kind, title_kind),
                          allow_remark=cfg.allow_remark)
    return kind, title_kind, fields


def _new(order: Order | None, *, kind: str, title_kind: str, fields: dict[str, str], source: str, by: str,
         checkout_token: str = "", reopened_from: int | None = None) -> InvoiceRequest:
    now = utcnow()
    return InvoiceRequest(
        flow_key=FLOW_KEY, order_id=order.id if order else None, platform=(order.platform or "") if order else "",
        checkout_token_hash=token_hash(checkout_token) if checkout_token else "", source=source, kind=kind,
        title_kind=title_kind, confirmed_at=now, by=by[:32], reopened_from=reopened_from, created_at=now, updated_at=now,
        **{k: fields.get(k, "") for k in CUSTOMER_FIELDS})


def start_flow(db: Session, ctx: Any, inv: InvoiceRequest, *, by: str, why: str) -> None:
    flow.start(db, ctx, inv, FLOW_KEY, by=by, why=why)
    sync_active(inv)
    db.flush()


def emit(db: Session, ctx: Any, inv: InvoiceRequest, event: str, *, by: str, why: str = "") -> bool:
    moved = flow.emit(db, ctx, inv, event, by=by, why=why)
    sync_active(inv)
    db.flush()
    return moved


def _claim_slot(db: Session, inv: InvoiceRequest, order_id: int) -> bool:
    """先占住这单的「一次申请」（active_order_id 唯一）再进流程。并发时后到的撞唯一键：整笔回滚，返回 False。
    （SQLite 的 SAVEPOINT 在 pysqlite 下不可靠，所以不用 begin_nested；调用方的这笔事务只做这一件事。）"""
    inv.active_order_id = order_id
    if inv.id is None:
        db.add(inv)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return False
    return True


def create_for_order(db: Session, ctx: Any, order: Order, data: dict[str, Any], *, source: str, by: str,
                     admin: bool = False, checkout_token: str = "", reopened_from: int | None = None) -> tuple[str, InvoiceRequest | None, str]:
    """给一单建申请并放进流程。返回（出口, 申请, 说明）：requested / drafted / exists / not_eligible。字段不对抛 InvoiceCheckFailed。"""
    cfg = load_config(db)
    if not cfg.enabled and not admin:
        return "not_eligible", None, "现在网上暂不受理发票申请，请联系负责人"
    kind, title_kind, fields = validate(cfg, data)
    have = active_for(db, order.id)
    if have is not None:
        return "exists", have, "这单已经申请过发票了；要改先撤回（开出前）或等负责人作废后重新申请"
    v = judge(db, order, cfg, admin=admin)
    if v.exit == "blocked":
        return "not_eligible", None, v.reason
    inv = _new(order, kind=kind, title_kind=title_kind, fields=fields, source=source, by=by, checkout_token=checkout_token,
               reopened_from=reopened_from)
    if not _claim_slot(db, inv, order.id):
        return "exists", active_for(db, order.id), "这单已经申请过发票了"
    start_flow(db, ctx, inv, by=by, why=SOURCE_LABELS.get(source, source))
    record_event(db, "invoice.submitted", f"invoice:{inv.id}", {
        "order_id": order.id, "platform": order.platform, "source": source, "kind": kind, "stage": inv.stage, "by": by})
    return ("requested" if inv.flow_step == "pending" else "drafted"), inv, STEP_NOTES.get(inv.flow_step, "")


def prefill(db: Session, *, checkout_token: str, data: dict[str, Any], by: str = "customer") -> InvoiceRequest:
    """下单页：付款前先填好（还没有订单）。同一个付款单再填一次就覆盖。字段不对抛 InvoiceCheckFailed。"""
    cfg = load_config(db)
    kind, title_kind, fields = validate(cfg, data)
    h = token_hash(checkout_token)
    inv = db.scalar(select(InvoiceRequest).where(InvoiceRequest.checkout_token_hash == h, InvoiceRequest.order_id.is_(None),
                                                 InvoiceRequest.flow_step == ""))
    if inv is None:
        inv = _new(None, kind=kind, title_kind=title_kind, fields=fields, source="checkout", by=by, checkout_token=checkout_token)
        db.add(inv)
    else:
        inv.kind, inv.title_kind, inv.confirmed_at, inv.updated_at = kind, title_kind, utcnow(), utcnow()
        for k in CUSTOMER_FIELDS:
            setattr(inv, k, fields.get(k, ""))
    db.flush()
    record_event(db, "invoice.prefilled", f"invoice:{inv.id}", {"kind": kind, "by": by})
    return inv


def bind_prefill(db: Session, ctx: Any, *, checkout_token: str, order: Order, by: str = "customer") -> InvoiceRequest | None:
    """付款页拿到激活码后：把这个付款单的预填挂到这单上、放进流程（订单没完成就是草稿）。没有预填返回 None。"""
    inv = db.scalar(select(InvoiceRequest).where(InvoiceRequest.checkout_token_hash == token_hash(checkout_token),
                                                 InvoiceRequest.order_id.is_(None), InvoiceRequest.flow_step == ""))
    if inv is None:
        return None
    have = active_for(db, order.id)
    if have is not None:  # 这单在交付页已经申请过了：预填作废
        record_event(db, "invoice.prefill_dropped", f"invoice:{inv.id}", {"order_id": order.id, "kept": have.id, "by": by})
        db.delete(inv)
        db.flush()
        return have
    cfg = load_config(db)
    v = judge(db, order, cfg)
    if v.exit == "blocked":
        record_event(db, "invoice.prefill_dropped", f"invoice:{inv.id}", {"order_id": order.id, "why": v.reason, "by": by})
        db.delete(inv)
        db.flush()
        return None
    inv.order_id, inv.platform = order.id, order.platform or ""
    if not _claim_slot(db, inv, order.id):
        return active_for(db, order.id)
    start_flow(db, ctx, inv, by=by, why="下单页预填，付款后挂上订单")
    record_event(db, "invoice.submitted", f"invoice:{inv.id}", {
        "order_id": order.id, "platform": order.platform, "source": "checkout", "kind": inv.kind, "stage": inv.stage, "by": by})
    return inv


def mark_requested(inv: InvoiceRequest) -> None:
    """进「待开票」那一刻（invoice.gate 放行时调）：出票用时从这里算。"""
    inv.requested_at = inv.requested_at or utcnow()
    inv.reason = ""


def recheck(db: Session, ctx: Any, inv: InvoiceRequest, *, by: str) -> bool:
    """草稿的订单完成了（或退款处理完了）：重新过关口。只有在「等订单完成」这一步才动。"""
    if inv.flow_step != "waiting":
        return False
    before = inv.flow_step
    emit(db, ctx, inv, "recheck", by=by, why="重新看能不能开")
    return inv.flow_step != before


def refresh_order(db: Session, ctx: Any, order_id: int, *, by: str) -> None:
    """页面打开、后台列表时顺手推一下这单的草稿（定时任务也会推，这里让客人不用等）。"""
    inv = active_for(db, order_id)
    if inv is not None and inv.flow_step == "waiting":
        recheck(db, ctx, inv, by=by)


# ---------------------------------------------------------------- 驳回、作废、撤回

_CLOSE = {"rejected": ("rejected", ("waiting", "pending")), "voided": ("voided", ("issued",)),
          "withdraw": ("cancelled", ("waiting", "pending"))}


def close(db: Session, ctx: Any, inv: InvoiceRequest, event: str, *, reason: str, by: str) -> None:
    """驳回（rejected）、作废（voided）、撤回（withdraw）。这一步不收这个动作抛 InvoiceCheckFailed。"""
    to, allowed = _CLOSE[event]
    labels = {"rejected": "驳回", "voided": "作废", "withdraw": "撤回"}
    if inv.flow_step not in allowed:
        raise InvoiceCheckFailed(f"这张申请现在是「{flow.stage_label(inv) if inv.flow_step else '预填'}」，不能{labels[event]}",
                                 {"rejected": "只有还没开的能驳回", "voided": "只有开好的能作废", "withdraw": "开出之前才能撤回；开好了的请联系负责人作废"}[event],
                                 "docs/任务单/07_开票_设计.md 第五节")
    inv.reason = reason[:300]
    inv.closed_at = utcnow()
    if not emit(db, ctx, inv, event, by=by, why=reason):
        raise InvoiceCheckFailed("流程没接这个动作", "看流程文件 invoices/flows/invoice_basic.json", "docs/任务单/07_开票_设计.md 第五节")
    record_event(db, f"invoice.{to}", f"invoice:{inv.id}", {"order_id": inv.order_id, "reason": reason[:300], "by": by,
                                                          "hours_open": hours_between(inv.requested_at, inv.closed_at)})


def hours_between(a: datetime | None, b: datetime | None) -> float | None:
    if a is None or b is None:
        return None
    return round((b - a).total_seconds() / 3600, 2)


def reopen(db: Session, ctx: Any, old: InvoiceRequest, *, fields: dict[str, Any] | None, by: str) -> tuple[str, InvoiceRequest | None, str]:
    """作废重开：照原来的（或改过的）信息新建一张，放进流程。"""
    order = db.get(Order, old.order_id) if old.order_id else None
    if order is None:
        return "not_eligible", None, "原来那张没挂订单"
    data = {"kind": old.kind, "title_kind": old.title_kind, **{k: getattr(old, k) for k in CUSTOMER_FIELDS}, **(fields or {})}
    return create_for_order(db, ctx, order, data, source="admin", by=by, admin=True, reopened_from=old.id)


def update_fields(db: Session, inv: InvoiceRequest, data: dict[str, Any], *, by: str) -> InvoiceRequest:
    """后台在开出前改信息（客人在聊天里说抬头写错了）。"""
    if inv.flow_step not in ("waiting", "pending"):
        raise InvoiceCheckFailed("开出以后不能改信息", "作废重开（重开时可以改）", "docs/任务单/07_开票_设计.md 第五节")
    cfg = load_config(db)
    merged = {"kind": inv.kind, "title_kind": inv.title_kind, **{k: getattr(inv, k) for k in CUSTOMER_FIELDS}, **data}
    kind, title_kind, fields = validate(cfg, merged)
    before = {k: getattr(inv, k) for k in ("kind", "title_kind", *CUSTOMER_FIELDS)}
    inv.kind, inv.title_kind, inv.updated_at = kind, title_kind, utcnow()
    for k in CUSTOMER_FIELDS:
        setattr(inv, k, fields.get(k, ""))
    after = {k: getattr(inv, k) for k in ("kind", "title_kind", *CUSTOMER_FIELDS)}
    changed = [k for k in before if before[k] != after[k]]
    record_event(db, "invoice.edited", f"invoice:{inv.id}", {"fields": changed, "before": {k: before[k] for k in changed},
                                                            "after": {k: after[k] for k in changed}, "by": by})
    return inv


# ---------------------------------------------------------------- 出票

def issue(db: Session, ctx: Any, inv: InvoiceRequest, *, files: list[tuple[str, bytes]], amount: str | None, invoice_no: str,
          note: str, by: str) -> list[InvoiceFile]:
    """上传开好的发票、标记已开。先再过一遍关口（已完成、没退款）和金额（不超过实付 − 已退）。不对抛 InvoiceCheckFailed。"""
    see = "docs/任务单/07_开票_设计.md 第五节 invoice.issue"
    if inv.flow_step != "pending":
        raise InvoiceCheckFailed(f"这张申请现在是「{flow.stage_label(inv) if inv.flow_step else '预填'}」，不能出票", "只有「待开票」的能出票", see)
    cfg = load_config(db)
    order = db.get(Order, inv.order_id) if inv.order_id else None
    v = judge(db, order, cfg, admin=True)
    if v.exit != "open":
        e = v.fail or InvoiceCheckFailed(v.reason or "这单现在不能开票", "按页面上的提示处理完再开", see)
        e.field = "gate"  # 节点按它分出口：关口不让开（blocked）和填的不对（invalid）
        raise e
    f = v.facts
    want = money(amount) if amount not in (None, "") else f.max_amount
    if f.max_amount is None:  # 查不到实付（后台手动开单）：只能手填，上限按手填的、记下来
        if want is None:
            require_amount_within_paid(None, None)
        max_amount = want
    else:
        max_amount = f.max_amount
    amt = require_amount_within_paid(want, max_amount)
    if not files:
        raise InvoiceCheckFailed("没有传发票文件", "从开票软件下载开好的发票（PDF，最好连 OFD 或 XML 一起）传上来", see)
    if len(files) > 5:
        raise InvoiceCheckFailed(f"一次传了 {len(files)} 个文件", "一张发票最多传 5 个文件（同一张票的 PDF、OFD、XML）", see)
    checked = [(name, data, require_invoice_file(name, data, allowed=cfg.file_types, max_mb=cfg.file_max_mb)) for name, data in files]
    saved: list[InvoiceFile] = []
    for name, data, kind in checked:
        key = ctx.storage.save(data, folder=f"invoices/{inv.order_id or 'none'}", filename=name)
        row = InvoiceFile(invoice_id=inv.id, filename=Path(name).name[:160], kind=kind, size=len(data),
                          sha256=hashlib.sha256(data).hexdigest(), storage_key=key, by=by[:32], created_at=utcnow())
        db.add(row)
        saved.append(row)
    now = utcnow()
    inv.amount, inv.paid_snapshot, inv.refunded_snapshot = fmt(amt), fmt(f.paid), fmt(f.refunded)
    inv.invoice_no, inv.issue_note, inv.issued_at, inv.reason = invoice_no.strip()[:32], note.strip()[:200], now, ""
    db.flush()
    if not emit(db, ctx, inv, "issued", by=by, why="上传发票、标记已开"):
        raise InvoiceCheckFailed("流程没接「issued」", "看流程文件 invoices/flows/invoice_basic.json", see)
    record_event(db, "invoice.issued", f"invoice:{inv.id}", {
        "order_id": inv.order_id, "platform": inv.platform, "amount": inv.amount, "files": [r.kind for r in saved],
        "hours": hours_between(inv.requested_at, now), "by": by})
    return saved


# ---------------------------------------------------------------- 给页面的视图

def customer_note(inv: InvoiceRequest) -> str:
    base = STEP_NOTES.get(inv.flow_step, "")
    if inv.flow_step in ("rejected", "blocked", "voided") and inv.reason:
        return f"{base}：{inv.reason}"
    return base


def view(db: Session, inv: InvoiceRequest, *, file_url: Any = None) -> dict[str, Any]:
    """给客人页面的一张申请（只给这单的主人看：交付页令牌、或付款页令牌 + 激活码）。不含存储路径。"""
    issued = inv.flow_step == "issued"
    files = files_of(db, inv.id) if issued else []
    return {
        "id": inv.id, "step": inv.flow_step or "prefill", "stage": inv.stage or "prefill",
        "stage_label": flow.stage_label(inv) if inv.flow_step else "已预填",
        "note": customer_note(inv) if inv.flow_step else "已预填，付款后挂到这一单",
        "kind": inv.kind, "kind_label": KIND_LABELS.get(inv.kind, inv.kind), "title_kind": inv.title_kind,
        "title_kind_label": TITLE_KIND_LABELS.get(inv.title_kind, inv.title_kind),
        **{k: getattr(inv, k) for k in CUSTOMER_FIELDS},
        "amount": inv.amount, "invoice_no": inv.invoice_no, "reason": inv.reason,
        "created_at": inv.created_at, "requested_at": inv.requested_at, "issued_at": inv.issued_at, "closed_at": inv.closed_at,
        "can_withdraw": inv.flow_step in ("waiting", "pending"),
        "files": [{"id": f.id, "name": f.filename, "kind": f.kind, "size": f.size, "url": file_url(f) if file_url else ""} for f in files],
    }


def panel(db: Session, order: Order, *, file_url: Any = None) -> dict[str, Any]:
    """交付页 / 付款页的发票一块：这单能不能申请、在办的那张、以前的（驳回、作废、撤回的原因）。"""
    cfg = load_config(db)
    current = active_for(db, order.id)
    past = [i for i in history_for(db, order.id) if current is None or i.id != current.id]
    v = judge(db, order, cfg)
    platform = order.platform or "legacy"
    eligible = cfg.enabled and platform in cfg.eligible_platforms
    can_apply = current is None and eligible and v.exit != "blocked"
    why_not = ""
    if current is None and not can_apply:
        why_not = v.reason if eligible else (
            f"这单是在{PLATFORM_NAMES.get(platform, platform)}下的，发票请在下单的平台申请" if cfg.enabled else "")
    return {
        "enabled": cfg.enabled, "eligible": eligible, "can_apply": can_apply, "why_not": why_not,
        "order_no": order_no(order.id), "completed": order.completed_at is not None,
        "apply_note": v.reason if v.exit == "wait" else "",
        "current": view(db, current, file_url=file_url) if current else None,
        "history": [view(db, i, file_url=None) | {"files": []} for i in past[:5] if i.flow_step],
        "config": public_config(cfg),
    }


def public_config(cfg: InvoiceConfig) -> dict[str, Any]:
    return {
        "enabled": cfg.enabled, "kinds": [{"key": k, "label": KIND_LABELS[k], "required": cfg.required(k)} for k in cfg.kinds()],
        "allow_personal": cfg.allow_personal, "allow_remark": cfg.allow_remark, "labels": FIELD_LABELS,
        "notice": cfg.customer_notice, "promise": cfg.promise_text, "seller_name": cfg.seller_name, "item_name": cfg.item_name,
    }


def copy_text(inv: InvoiceRequest, cfg: InvoiceConfig | None = None) -> str:
    """后台「复制抬头信息」：贴进开票软件或发给财务。"""
    lines = [f"发票类型：{KIND_LABELS.get(inv.kind, inv.kind)}", f"抬头：{inv.title}"]
    if inv.tax_id:
        lines.append(f"纳税人识别号：{inv.tax_id}")
    for k, label in (("address", "地址"), ("phone", "电话"), ("bank_name", "开户行"), ("bank_account", "账号")):
        if getattr(inv, k):
            lines.append(f"{label}：{getattr(inv, k)}")
    if cfg is not None and cfg.item_name:
        lines.append(f"项目：{cfg.item_name}")
    if inv.remark:
        lines.append(f"备注：{inv.remark}")
    lines.append(f"收票邮箱：{inv.email}")
    lines.append(f"单号：{order_no(inv.order_id)}")
    return "\n".join(lines)


def mask_email(email: str) -> str:
    name, _, host = email.partition("@")
    return f"{name[:2]}***@{host}" if host else email[:2] + "***"


# ---------------------------------------------------------------- 定时：过期预填

def drop_stale_prefills(db: Session, *, days: int, now: datetime | None = None) -> int:
    cut = (now or utcnow()) - timedelta(days=days)
    rows = list(db.scalars(select(InvoiceRequest).where(InvoiceRequest.order_id.is_(None), InvoiceRequest.flow_step == "",
                                                        InvoiceRequest.created_at < cut)))
    for r in rows:
        db.delete(r)
    if rows:
        record_event(db, "invoice.prefill_expired", "invoice:prefill", {"count": len(rows), "by": "system:invoice_sweep"})
    return len(rows)


def record_download(db: Session, inv: InvoiceRequest, f: InvoiceFile, *, by: str) -> None:
    record_event(db, "invoice.downloaded", f"invoice:{inv.id}", {"order_id": inv.order_id, "file_id": f.id, "kind": f.kind, "by": by})


def notices_for(db: Session, invoice_id: int) -> list[InvoiceNotice]:
    return list(db.scalars(select(InvoiceNotice).where(InvoiceNotice.invoice_id == invoice_id).order_by(InvoiceNotice.id)))

