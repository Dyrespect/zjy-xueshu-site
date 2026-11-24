"""invoice.sweep 定时看一眼。"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.core.db import utcnow
from app.core.events import Event, record_event
from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.intake.models import Order
from app.invoices import service
from app.invoices.checks import fmt
from app.invoices.facts import paid_facts, shop_refunds
from app.invoices.models import InvoiceRequest
from app.invoices.models_io import SweepIn, SweepOut


def handler(call: NodeCall, data: SweepIn) -> NodeResult:
    db, now = call.db, data.now or utcnow()
    out = SweepOut()
    # 1. 等订单完成的草稿：订单完成了（或退款处理完了）就再过一遍关口
    for inv in list(db.scalars(select(InvoiceRequest).where(InvoiceRequest.flow_step == "waiting"))):
        service.recheck(db, call.ctx, inv, by=call.by)
        if inv.flow_step == "waiting":
            out.still_waiting += 1
        else:
            out.promoted += 1
    # 2. 开票以后又退了款（或申请退款）的：提醒负责人作废（每张只提醒一次）
    recent = list(db.scalars(select(InvoiceRequest).where(InvoiceRequest.flow_step == "issued",
                                                          InvoiceRequest.issued_at >= now - timedelta(days=400))))
    refunds = shop_refunds(db, {i.order_id for i in recent if i.order_id})
    warned = {e.subject for e in db.scalars(select(Event).where(Event.type == "invoice.refund_after_issue"))}
    for inv in recent:
        order = db.get(Order, inv.order_id) if inv.order_id else None
        if order is None or f"invoice:{inv.id}" in warned:
            continue
        f = paid_facts(db, order, refunds)
        if f.fully_refunded or f.refund_pending or f.refunded > (service.money(inv.refunded_snapshot) or 0):
            out.refund_after_issue.append(inv.id)
            record_event(db, "invoice.refund_after_issue", f"invoice:{inv.id}", {
                "order_id": order.id, "refunded": fmt(f.refunded), "pending": f.refund_pending, "by": call.by})
            call.ctx.notifier.send(f"单号 {service.order_no(order.id)} 开了发票（{inv.amount} 元）以后又退了款或在退款："
                                   "去后台「发票」把这张作废（需要的话作废重开），并让财务红冲", link="/admin/invoices", level="urgent", kind="开票后退款", who=f"order:{order.id}")
    # 3. 下单页预填了、过了几天还没付款挂上订单的：删掉
    out.prefills_dropped = service.drop_stale_prefills(db, days=data.prefill_ttl_days, now=now)
    return NodeResult(exit="ok", output=out)


CARD = NodeCard(
    id="invoice.sweep",
    name="发票定时看一眼",
    description="每隔一阵（默认 10 分钟）看一遍：等订单完成的发票草稿，订单完成了就推进到「待开票」；开了票又退款的提醒负责人作废；"
                "下单页预填了但几天没付款的删掉。客人打开页面、负责人打开后台时也会顺手推一下，不用干等。",
    category="触发",
    tech=["FastAPI lifespan 里的定时任务（app/invoices/router.py）", "后台按钮 POST /api/admin/invoices/sweep", "飞书通知（core.notify）"],
    input_model=SweepIn,
    output_model=SweepOut,
    exits=[NodeExit(key="ok", label="看完了", kind="ok"), NodeExit(key="fail", label="这一轮出错（下一轮再来）", kind="fail")],
    config=["INVOICE_TIMER_ENABLED、INVOICE_TIMER_INTERVAL_SEC（.env）", "INVOICE_PREFILL_TTL_DAYS：预填留几天（默认 7）"],
    emits=["invoice.refund_after_issue", "invoice.prefill_expired", "invoice.stage（引擎记）"],
    listens=["无（订单中枢没有订阅机制，定时看订单的 completed_at、退款事件）"],
    replaceable=["以后订单中枢有了事件订阅（intake.order_completed）就改成收到事件就推，定时只兜底"],
    failure="一轮出错整轮回滚、下一轮再来；推进、提醒都幂等（草稿只在「等订单完成」才动，开票后退款每张只提醒一次）。",
    owner="开票",
    status="要新做",
)
register(CARD, handler)
