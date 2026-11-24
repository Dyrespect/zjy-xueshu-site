"""invoice.notify 通知客人（开好、驳回、作废）。"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select

from app.core.db import utcnow
from app.core.events import record_event
from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, has_handler, register, run_node
from app.intake.models import Customer, Order
from app.intake.service import create_outbox
from app.invoices import service
from app.invoices.config import load_config
from app.invoices.models import InvoiceNotice, InvoiceRequest
from app.invoices.models_io import NotifyIn, NotifyOut

KIND_OF_STEP = {"issued": "issued", "rejected": "rejected", "blocked": "rejected", "voided": "voided"}
SUBJECTS = {"issued": "你的发票开好了", "rejected": "你的发票申请没开成", "voided": "你的发票作废了"}


def _text(template: str, values: dict[str, str]) -> str:
    return template.format_map(defaultdict(str, values)).strip()


def handler(call: NodeCall, data: NotifyIn) -> NodeResult:
    db = call.db
    inv = db.get(InvoiceRequest, data.invoice_id)
    kind = KIND_OF_STEP.get(inv.flow_step if inv else "", "")
    if inv is None or not kind:
        return NodeResult(exit="skipped", output=NotifyOut(invoice_id=data.invoice_id), detail="这一步不用通知")
    if db.scalar(select(InvoiceNotice.id).where(InvoiceNotice.invoice_id == inv.id, InvoiceNotice.kind == kind)) is not None:
        return NodeResult(exit="skipped", output=NotifyOut(invoice_id=inv.id, kind=kind), detail="通知过了")
    cfg = load_config(db)
    order = db.get(Order, inv.order_id) if inv.order_id else None
    url = call.ctx.delivery_url(order) if order is not None and hasattr(call.ctx, "delivery_url") else ""
    template = {"issued": cfg.notice_issued, "rejected": cfg.notice_rejected, "voided": cfg.notice_voided}[kind]
    text = _text(template, {"order_no": service.order_no(inv.order_id), "amount": inv.amount, "reason": inv.reason or "", "url": url})
    subject = f"{SUBJECTS[kind]}（单号 {service.order_no(inv.order_id)}）"
    now = utcnow()
    out = NotifyOut(invoice_id=inv.id, kind=kind)

    # 邮件：有人登记了 notify.email 就用它；没有就进「待发」，负责人在后台复制去发
    if inv.email:
        status, detail = "pending", "还没有发邮件的服务，进了待发"
        if has_handler("notify.email"):
            r = run_node("notify.email", call, {"to": inv.email, "subject": subject, "text": text})
            status, detail = ("sent", "") if r.exit in ("ok", "sent") else ("pending", f"发邮件没成：{r.detail}"[:300])
        db.add(InvoiceNotice(invoice_id=inv.id, kind=kind, channel="email", status=status, target=inv.email, subject=subject,
                             text=text, detail=detail, created_at=now, sent_at=now if status == "sent" else None))
        out.email = status
    else:
        out.email = "skipped"

    # 站内：这单认领过会话就走订单中枢的发件接口（网页聊天 / 微信客服，发件员发）；没认领的跳过
    customer = db.get(Customer, order.customer_id) if order is not None and order.customer_id else None
    if customer is not None:
        ob = create_outbox(db, call.ctx, customer, order, text=text, category="交付", author="system",
                           reasons=[f"发票通知（invoice:{inv.id}，{kind}）"])
        db.add(InvoiceNotice(invoice_id=inv.id, kind=kind, channel="chat", status="queued", target=f"customer:{customer.id}",
                             subject=subject, text=text, detail=f"outbox:{ob.id}", created_at=now))
        out.chat = "queued"
    else:
        out.chat = "skipped"
    db.flush()
    record_event(db, "invoice.notified", f"invoice:{inv.id}", {"order_id": inv.order_id, "kind": kind, "email": out.email,
                                                              "chat": out.chat, "by": call.by})
    if out.email == "pending":
        exit_ = "queued"  # 邮件等负责人手动发
    elif out.email == "sent" or out.chat == "queued":
        exit_ = "sent"
    else:
        exit_ = "skipped"
    return NodeResult(exit=exit_, output=out)


CARD = NodeCard(
    id="invoice.notify",
    name="通知客人发票进度",
    description="发票开好、被驳回、作废时告诉客人：站内（网页聊天 / 微信客服里发一句带交付页链接的话）和邮件。"
                "邮件服务还没有，先进「待发」，负责人在后台复制去发；交付页上的进度本来就实时能看。",
    category="运营",
    tech=["订单中枢的发件接口 app/intake/service.create_outbox（发件员发到网页聊天 / 微信客服）",
          "邮件：节点 notify.email（还没人做；登记了自动用）", "表 invoice_notices（待发的在后台「发票 → 待发通知」）"],
    input_model=NotifyIn,
    output_model=NotifyOut,
    exits=[NodeExit(key="sent", label="发出去了（或进了订单中枢的待发）", kind="ok"),
           NodeExit(key="queued", label="有一样进了待发，等负责人手动发", kind="wait"),
           NodeExit(key="skipped", label="不用发（通知过了、没有渠道）", kind="ok")],
    config=["notice_issued、notice_rejected、notice_voided：发给客人的话（{order_no}、{amount}、{reason}、{url}）"],
    emits=["invoice.notified"],
    listens=["无（流程进「已开票」「没开成」「已作废」时引擎调它）"],
    replaceable=["邮件：notify.email（以后接 SMTP 或云邮件）", "站内：模块 D 的入口发件节点（entry.webchat / entry.wecom）上线后换过去"],
    failure="同一张同一种通知只发一次（查 invoice_notices）；邮件发不出去进待发，不影响流程往下走。",
    owner="开票",
    status="要新做",
)
register(CARD, handler)
