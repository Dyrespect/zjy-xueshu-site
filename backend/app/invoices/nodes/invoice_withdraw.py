"""invoice.withdraw 客人撤回。"""

from __future__ import annotations

from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.invoices import service
from app.invoices.checks import InvoiceCheckFailed
from app.invoices.models import InvoiceRequest
from app.invoices.models_io import CloseIn, CloseOut


def handler(call: NodeCall, data: CloseIn) -> NodeResult:
    inv = call.db.get(InvoiceRequest, data.invoice_id)
    if inv is None:
        return NodeResult(exit="fail", output=CloseOut(invoice_id=data.invoice_id), detail="没有这张申请")
    try:
        service.close(call.db, call.ctx, inv, "withdraw", reason=data.reason.strip() or "客人撤回", by=data.by)
    except InvoiceCheckFailed as e:
        return NodeResult(exit="fail", output=CloseOut(invoice_id=inv.id, step=inv.flow_step), detail=e.public())
    return NodeResult(exit="ok", output=CloseOut(invoice_id=inv.id, step=inv.flow_step, note="撤回了，可以改好重新申请"))


CARD = NodeCard(
    id="invoice.withdraw",
    name="撤回发票申请",
    description="开出之前，客人发现抬头或税号填错了，可以自己在交付页（或付款页）撤回，改好重新申请；开好以后不能撤回，要负责人作废。",
    category="财务",
    tech=["客人接口 POST /api/invoices/order/{令牌}/withdraw、/api/invoices/checkout/{令牌}/withdraw", "流程引擎（事件 withdraw → 已撤回）"],
    input_model=CloseIn,
    output_model=CloseOut,
    exits=[NodeExit(key="ok", label="撤回了", kind="ok"), NodeExit(key="fail", label="已经开了或已经关了", kind="fail")],
    config=["无"],
    emits=["invoice.cancelled"],
    listens=["无"],
    replaceable=["暂无"],
    failure="只有「等订单完成」「待开票」的能撤回；接口先校验这张申请属于这单。重复点返回 fail。",
    owner="开票",
    status="要新做",
)
register(CARD, handler)
