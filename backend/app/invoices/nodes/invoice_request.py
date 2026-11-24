"""invoice.request 申请发票。"""

from __future__ import annotations

from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.intake.models import Order
from app.invoices import service
from app.invoices.checks import InvoiceCheckFailed
from app.invoices.models_io import RequestIn, RequestOut


def handler(call: NodeCall, data: RequestIn) -> NodeResult:
    if not data.confirmed:
        return NodeResult(exit="invalid", output=RequestOut(field="confirmed"),
                          detail="提交前请核对一遍抬头和税号（开出后改不了），核对无误再提交")
    fields = data.fields.model_dump()
    try:
        if data.order_id is None:
            if data.source != "checkout" or not data.checkout_token:
                return NodeResult(exit="invalid", output=RequestOut(), detail="没说是哪一单")
            inv = service.prefill(call.db, checkout_token=data.checkout_token, data=fields, by=data.by)
            return NodeResult(exit="prefilled", output=RequestOut(invoice_id=inv.id, step="", stage="", note="已预填，付款后挂到这一单"))
        order = call.db.get(Order, data.order_id)
        if order is None:
            return NodeResult(exit="not_eligible", output=RequestOut(), detail="找不到这一单")
        exit_, inv, note = service.create_for_order(call.db, call.ctx, order, fields, source=data.source, by=data.by,
                                                    admin=data.source == "admin", checkout_token=data.checkout_token)
    except InvoiceCheckFailed as e:
        return NodeResult(exit="invalid", output=RequestOut(field=e.field), detail=e.public())
    out = RequestOut(invoice_id=inv.id if inv else None, step=inv.flow_step if inv else "", stage=inv.stage if inv else "", note=note)
    return NodeResult(exit=exit_, output=out, detail=note)


CARD = NodeCard(
    id="invoice.request",
    name="申请发票",
    description="收客人填的发票信息（抬头、税号、邮箱；专票再加开户行、账号、地址、电话），校验格式、要求先核对一遍，存成申请。"
                "订单还没完成就存成草稿，完成后自动进「待开票」；下单页付款前填的先预填，付款后挂到这一单。一单只能有一张在办的申请。",
    category="财务",
    tech=["FastAPI 接口 /api/invoices/*（下单页、付款页、交付页）、/api/admin/invoices/manual（后台录入）",
          "SQLAlchemy 表 invoice_requests（active_order_id 唯一键）", "流程引擎 app/intake/flow.py（对象 invoice，流程 invoice_basic）",
          "校验 app/invoices/checks.py（税号国标校验位、邮箱）"],
    input_model=RequestIn,
    output_model=RequestOut,
    exits=[
        NodeExit(key="requested", label="进了待开票（订单已完成）", kind="ok"),
        NodeExit(key="drafted", label="存成草稿，等订单完成", kind="wait"),
        NodeExit(key="prefilled", label="付款前预填，还没挂上订单", kind="wait"),
        NodeExit(key="exists", label="这单已经有在办的申请（返回那一张）", kind="ok"),
        NodeExit(key="not_eligible", label="这单不能申请（平台单、退了款、网上暂不受理）", kind="fail"),
        NodeExit(key="invalid", label="填的不对或没核对（带字段）", kind="fail"),
    ],
    config=["enabled：网上受不受理", "eligible_platforms：哪些渠道的单客人能自己申请（默认只有 web）",
            "special_enabled、allow_personal、allow_remark、required_normal、required_special：哪些发票、哪些字段必填",
            "apply_window_days：完成后多久内能申请（0 不限）"],
    emits=["invoice.submitted", "invoice.prefilled", "invoice.prefill_dropped", "invoice.stage（引擎记）"],
    listens=["无"],
    replaceable=["来源可换：下单页预填、付款页、交付页、后台录入（同一个节点，source 区分）",
                 "以后平台单也让客人申请：改设置 eligible_platforms，不改节点"],
    failure="字段不对返回 invalid（带字段名，客人改了再交），不存；同一单并发两张，唯一键挡住后一张返回 exists；"
            "同一个付款单的预填再交一次是覆盖（幂等）。",
    owner="开票",
    status="要新做",
)
register(CARD, handler)
