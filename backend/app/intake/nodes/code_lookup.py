"""code.lookup 查码（只读）。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.intake import orders


class LookupIn(BaseModel):
    code: str = Field(min_length=1, max_length=64, description="客人给的码，原样（大小写、空格、横线都行）")


class LookupOut(BaseModel):
    state: str = Field(description="not_found | unused_pool | paid | claimed | void | expired | addon | legacy")
    code: str = ""
    sku: str = ""
    sku_name: str = ""
    std_hours: int | None = None
    order_id: int | None = None
    customer_id: int | None = Field(default=None, description="认领它的会话；只给入口模块判断是不是同一个人，不给客人看")
    stage: str = ""
    progress: str = ""


def handler(call: NodeCall, data: LookupIn) -> NodeResult:
    r = orders.lookup_code(call.db, data.code)
    return NodeResult(exit="ok", output=LookupOut(**r.__dict__))


CARD = NodeCard(
    id="code.lookup",
    name="查码",
    description="看一枚激活码现在是什么情况：不存在、码池里没卖出、已付款等认领、已认领（谁、到哪一步）、作废、过期、加购码、旧档位码。"
                "兑换网页和「同一个人再交已认领的码」用。只读，不算撞库次数。",
    category="订单",
    tech=["SQLAlchemy 只读查询（intake_activation_codes、intake_code_redemptions、intake_orders）"],
    input_model=LookupIn,
    output_model=LookupOut,
    exits=[NodeExit(key="ok", label="查到了（state 说明是哪种）", kind="ok")],
    config=["无"],
    emits=["无"],
    listens=["无"],
    replaceable=["暂无"],
    failure="只读，随便重试。兑换页要自己限流（防撞库），这里不计次数。",
    owner="A",
    status="要新做",
)
register(CARD, handler)
