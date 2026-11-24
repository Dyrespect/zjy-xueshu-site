"""order.signal 平台信号（已完成、申请退款、退款、退款关闭）。

模块 C 加的薄壳（11-18，渠道与支付）：契约第四节第 4 条写 C 调 orders.apply_signal，
但 check.py 不许 platforms import app.intake.orders，所以包成节点。逻辑全在 orders.apply_signal，没改。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.intake import orders
from app.intake.adapters import PlatformSignal


class SignalOut(BaseModel):
    order_id: int | None = None
    stage: str = ""
    hold_reason: str = ""
    progress: str = Field(default="", description="这单现在的进度（一句话）")


def handler(call: NodeCall, data: PlatformSignal) -> NodeResult:
    o = orders.apply_signal(call.db, call.ctx, data, by=call.by)
    if o is None:
        return NodeResult(exit="no_order", output=SignalOut(), detail="没有对应的单（码还没认领的退款已经把码作废）")
    return NodeResult(exit="applied", output=SignalOut(order_id=o.id, stage=o.stage, hold_reason=o.hold_reason or "",
                                                       progress=orders.progress(call.db, o)))


CARD = NodeCard(
    id="order.signal",
    name="平台信号",
    description="平台那边一单有了变化：已完成（来得早先记下）、申请退款（先暂停）、真退了（已完成之前作废、码作废）、"
                "退款申请关了（恢复）。人工录单的渠道由负责人在后台点。",
    category="订单",
    tech=["app/intake/orders.py 的 apply_signal（流程引擎 emit、暂停、作废）", "调用方：平台渠道节点 channel.xhs、channel.xianyu（模块 C）"],
    input_model=PlatformSignal,
    output_model=SignalOut,
    exits=[NodeExit(key="applied", label="对上单了，照规矩处理（渠道不认的来源只记一笔）", kind="ok"),
           NodeExit(key="no_order", label="平台单号没对上单", kind="fail")],
    config=["delivery.confirm_sources_by_platform：平台的已完成认不认", "refund_block_after：退款作废几次不再发码"],
    emits=["intake.order_held", "intake.order_released", "intake.order_voided", "intake.platform_completed", "intake.signal_ignored"],
    listens=["无"],
    replaceable=["暂无"],
    failure="幂等：同一个信号再来，暂停的不重复暂停、作废的不再作废（记 signal_ignored）。",
    owner="A（C 包的壳）",
    status="要新做",
)
register(CARD, handler)
