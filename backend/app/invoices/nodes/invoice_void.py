"""invoice.void 作废（可以作废重开）。"""

from __future__ import annotations

from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.invoices import service
from app.invoices.checks import InvoiceCheckFailed
from app.invoices.models import InvoiceRequest
from app.invoices.models_io import CloseOut, VoidIn


def handler(call: NodeCall, data: VoidIn) -> NodeResult:
    inv = call.db.get(InvoiceRequest, data.invoice_id)
    if inv is None:
        return NodeResult(exit="fail", output=CloseOut(invoice_id=data.invoice_id), detail="没有这张申请")
    if len(data.reason.strip()) < 2:
        return NodeResult(exit="fail", output=CloseOut(invoice_id=inv.id), detail="作废要写原因（客人会看到）")
    try:
        service.close(call.db, call.ctx, inv, "voided", reason=data.reason.strip(), by=data.by)
    except InvoiceCheckFailed as e:
        return NodeResult(exit="fail", output=CloseOut(invoice_id=inv.id, step=inv.flow_step), detail=str(e))
    out = CloseOut(invoice_id=inv.id, step=inv.flow_step, note="作废了，客人可以重新申请")
    if data.reopen:
        try:
            exit_, new, note = service.reopen(call.db, call.ctx, inv, fields=data.fields.model_dump() if data.fields else None,
                                              by=data.by)
        except InvoiceCheckFailed as e:
            out.note = f"作废了；重开没成：{e.public()}"
            return NodeResult(exit="ok", output=out, detail=out.note)
        out.new_invoice_id = new.id if new else None
        out.note = f"作废了，重开了一张（{note}）" if new else f"作废了；重开没成：{note}"
    return NodeResult(exit="ok", output=out, detail=out.note)


CARD = NodeCard(
    id="invoice.void",
    name="作废发票",
    description="开错了（抬头、金额不对，或开票后又退了款）把这张作废；勾「重开」就照原信息（或改过的）新建一张进待开票。"
                "红冲、作废本身由财务在开票软件里做，这里只是让系统和客人知道。",
    category="财务",
    tech=["后台接口 POST /api/admin/invoices/{id}/void", "流程引擎（事件 voided → 已作废，进来就通知客人）"],
    input_model=VoidIn,
    output_model=CloseOut,
    exits=[NodeExit(key="ok", label="作废了（重开的话带新那张的号）", kind="ok"),
           NodeExit(key="fail", label="没写原因、或这张不是已开票", kind="fail")],
    config=["notice_voided：通知客人的话"],
    emits=["invoice.voided", "invoice.submitted（重开的那张）"],
    listens=["无"],
    replaceable=["暂无"],
    failure="只有「已开票」的能作废；作废成功但重开没过关口（比如退了款）时，作废照样算，重开那张不建，原因写回后台。",
    owner="开票",
    status="要新做",
)
register(CARD, handler)
