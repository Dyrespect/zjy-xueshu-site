"""order.void 作废。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.intake import orders
from app.intake.flow import StageError
from app.intake.models import Order


class VoidIn(BaseModel):
    order_id: int
    code_action: Literal["return", "void"] = Field(description="return 撤单（码退回还能用，只许开工前）| void 退款（码作废）")
    why: str = Field(default="", max_length=200)


class StageOut(BaseModel):
    order_id: int
    stage: str
    progress: str = ""


def handler(call: NodeCall, data: VoidIn) -> NodeResult:
    o = call.db.get(Order, data.order_id)
    if o is None:
        return NodeResult(exit="fail", detail="没有这单")
    try:
        orders.void_order(call.db, call.ctx, o, code_action=data.code_action, by=call.by, why=data.why)
    except (StageError, ValueError) as e:
        return NodeResult(exit="fail", detail=str(e))
    return NodeResult(exit="ok", output=StageOut(order_id=o.id, stage=o.stage, progress=orders.progress(call.db, o)))


CARD = NodeCard(
    id="order.void",
    name="作废",
    description="退款或撤单：订单停在作废时的进度，不再排期、交接、发最终版。客人开工前撤单，码退回还能再用；"
                "平台退款，码作废。已完成之后不能作废（走平台售后，不自动补发）。",
    category="订单",
    tech=["SQLAlchemy", "流程引擎（发 voided；流程里已完成之后的步骤没有这条连线）", "飞书通知"],
    input_model=VoidIn,
    output_model=StageOut,
    exits=[NodeExit(key="ok", label="作废了", kind="ok"),
           NodeExit(key="fail", label="已完成之后、已经作废、开工后想退码", kind="fail")],
    config=["无"],
    emits=["intake.order_voided", "intake.code_returned", "admin.code_voided", "intake.stage"],
    listens=["无"],
    replaceable=["平台退款信号（模块 C 的适配器）、后台按钮、助手的撤单工具都调这一个"],
    failure="已经作废的再作废返回 fail，不重复改码；开工后正在做的单作废时给制作方留一句「停工」。",
    owner="A",
    status="要新做",
)
register(CARD, handler)
