"""invoice.issue 出票（上传开好的发票、标记已开）。"""

from __future__ import annotations

from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.invoices import service
from app.invoices.checks import InvoiceCheckFailed
from app.invoices.models import InvoiceRequest
from app.invoices.models_io import IssueIn, IssueOut


def handler(call: NodeCall, data: IssueIn) -> NodeResult:
    inv = call.db.get(InvoiceRequest, data.invoice_id)
    if inv is None:
        return NodeResult(exit="invalid", output=IssueOut(invoice_id=data.invoice_id), detail="没有这张申请")
    try:
        saved = service.issue(call.db, call.ctx, inv, files=[(f.filename, f.data) for f in data.files], amount=data.amount,
                              invoice_no=data.invoice_no, note=data.note, by=data.by)
    except InvoiceCheckFailed as e:
        exit_ = "blocked" if e.field == "gate" else "invalid"
        return NodeResult(exit=exit_, output=IssueOut(invoice_id=inv.id), detail=str(e))
    return NodeResult(exit="issued", output=IssueOut(invoice_id=inv.id, amount=inv.amount, file_ids=[f.id for f in saved]))


CARD = NodeCard(
    id="invoice.issue",
    name="出票",
    description="财务在开票软件里开好以后，负责人在后台上传发票文件（PDF、OFD、XML，可以几种一起），标记已开，客人就能下载。"
                "标记前再过一遍关口：订单已完成、没退款、开票金额不超过实付 − 已退。",
    category="财务",
    tech=["后台接口 POST /api/admin/invoices/{id}/issue（multipart）", "app/core/storage.py 存文件（只在后端用，不对外给路径）",
          "检查 app/invoices/checks.py（require_invoice_file 按内容认类型、require_amount_within_paid）"],
    input_model=IssueIn,
    output_model=IssueOut,
    exits=[
        NodeExit(key="issued", label="开好了（流程到已开票，通知客人）", kind="ok"),
        NodeExit(key="blocked", label="这单现在不能开（没完成、退款了、在退款中）", kind="fail"),
        NodeExit(key="invalid", label="文件或金额不对、这张不在待开票", kind="fail"),
    ],
    config=["file_types：收哪几种文件（pdf、ofd、xml）", "file_max_mb：单个文件多大（默认 10）", "item_name、tax_rate：只在复制给财务的信息里显示"],
    emits=["invoice.issued（带出票用时 hours，周报用）"],
    listens=["无"],
    replaceable=["手动上传（默认）", "以后接第三方开票接口自动开票：换这个节点，客人页面和流程不改"],
    failure="任何一条检查不过就整笔不存（文件、金额、状态都不动），错误三件写回后台；同一张已开的再点出票返回 invalid，不重复记。",
    owner="开票",
    status="要新做",
)
register(CARD, handler)
