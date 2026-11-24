"""invoice.gate 能不能开票（关口）。"""

from __future__ import annotations

from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.intake.models import Order
from app.invoices import service
from app.invoices.checks import fmt
from app.invoices.config import load_config
from app.invoices.facts import judge
from app.invoices.models import InvoiceRequest
from app.invoices.models_io import GateIn, GateOut


def handler(call: NodeCall, data: GateIn) -> NodeResult:
    inv = call.db.get(InvoiceRequest, data.invoice_id) if data.invoice_id else None
    order_id = inv.order_id if inv is not None else data.order_id
    order = call.db.get(Order, order_id) if order_id else None
    admin = data.admin or (inv is not None and inv.source == "admin")
    v = judge(call.db, order, load_config(call.db), admin=admin)
    f = v.facts
    out = GateOut(order_id=order_id, paid=fmt(f.paid) if f else "", refunded=fmt(f.refunded) if f else "",
                  max_amount=fmt(f.max_amount) if f else "", reason=v.reason, warnings=v.warnings)
    if inv is not None and data.via == "flow":  # 引擎调的：把结论记在申请上，客人和后台都看得到
        if v.exit == "open":
            service.mark_requested(inv)
        else:
            inv.reason = v.reason[:300]
    return NodeResult(exit=v.exit, output=out, detail=v.reason)


CARD = NodeCard(
    id="invoice.gate",
    name="能不能开票",
    description="代码判断这单现在能不能开票：订单到「已完成」（和发最终版同一个关口，不先开票后退款）、没退款也不在退款中、"
                "渠道在名单里、没过申请期限；算出最多能开多少（实付 − 已退，含加购、含税不另加税）。",
    category="关口",
    tech=["只读：intake_orders、intake_activation_codes、事件 shop.refund_requested / shop.refund_done（app/invoices/facts.py）",
          "检查 app/invoices/checks.py（require_completed、require_not_refunded）"],
    input_model=GateIn,
    output_model=GateOut,
    exits=[
        NodeExit(key="open", label="能开（进待开票）", kind="ok"),
        NodeExit(key="wait", label="先等着（订单没完成、在退款中）", kind="wait"),
        NodeExit(key="blocked", label="不能开（退了款、作废了、平台单、过了期限）", kind="fail"),
    ],
    config=["eligible_platforms：哪些渠道的单能开", "apply_window_days：完成后多久内能申请（0 不限）"],
    emits=["无（引擎记 invoice.stage）"],
    listens=["无（订单完成后由 invoice.sweep 或页面打开时发 recheck 再问一次）"],
    replaceable=["暂无（关口条件不换：付费单只能在已完成之后开）"],
    failure="只读，随便重试；查不到实付不拦（给出警告，开票时手填金额，仍不能超过客人真付的）。",
    owner="开票",
    status="要新做",
)
register(CARD, handler)
