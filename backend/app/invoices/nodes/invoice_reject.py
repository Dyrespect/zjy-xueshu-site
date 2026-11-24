"""invoice.reject 驳回。"""

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
    if len(data.reason.strip()) < 2:
        return NodeResult(exit="fail", output=CloseOut(invoice_id=inv.id), detail="驳回要写原因（客人会看到，照着改了重新申请）")
    try:
        service.close(call.db, call.ctx, inv, "rejected", reason=data.reason.strip(), by=data.by)
    except InvoiceCheckFailed as e:
        return NodeResult(exit="fail", output=CloseOut(invoice_id=inv.id, step=inv.flow_step), detail=str(e))
    return NodeResult(exit="ok", output=CloseOut(invoice_id=inv.id, step=inv.flow_step, note="驳回了，客人会看到原因"))


CARD = NodeCard(
    id="invoice.reject",
    name="驳回发票申请",
    description="信息不对（抬头和税号对不上、单位名称不全）或这单不该开时，负责人写原因驳回；客人在交付页看到原因，改好后能重新申请。",
    category="财务",
    tech=["后台接口 POST /api/admin/invoices/{id}/reject", "流程引擎（事件 rejected → 没开成，进来就通知客人）"],
    input_model=CloseIn,
    output_model=CloseOut,
    exits=[NodeExit(key="ok", label="驳回了", kind="ok"), NodeExit(key="fail", label="没写原因、或这张已经开了 / 关了", kind="fail")],
    config=["notice_rejected：通知客人的话"],
    emits=["invoice.rejected"],
    listens=["无"],
    replaceable=["暂无"],
    failure="只有「等订单完成」「待开票」的能驳回；重复点返回 fail，不重复通知。",
    owner="开票",
    status="要新做",
)
register(CARD, handler)
