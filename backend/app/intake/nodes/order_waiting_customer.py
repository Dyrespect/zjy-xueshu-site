"""order.waiting_customer 在等客人看水印版的单（只读）。

模块 B 加的薄壳（11-18，渠道与支付）：契约第四节第 4 条写 B 调 orders.orders_waiting_customer，
但 check.py 不许 shop import app.intake.orders，所以包成节点。逻辑全在 orders.orders_waiting_customer，没改。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.intake import orders


class WaitingIn(BaseModel):
    platforms: list[str] = Field(min_length=1, description="哪些渠道的单（web、fk、manual……）")
    idle_since: datetime = Field(description="最近一版水印版交出时间早于这个才算")


class WaitingOut(BaseModel):
    order_ids: list[int] = Field(default_factory=list)


def handler(call: NodeCall, data: WaitingIn) -> NodeResult:
    return NodeResult(exit="ok", output=WaitingOut(order_ids=orders.orders_waiting_customer(
        call.db, platforms=data.platforms, idle_since=data.idle_since)))


CARD = NodeCard(
    id="order.waiting_customer",
    name="等客人确认的单",
    description="找出在「已交水印版」、最近一版交出得够久、没有没处理完的改稿、没暂停的单——超时自动确认用。只读。",
    category="订单",
    tech=["SQLAlchemy 只读查询（intake_orders、intake_revisions），app/intake/orders.py 的 orders_waiting_customer"],
    input_model=WaitingIn,
    output_model=WaitingOut,
    exits=[NodeExit(key="ok", label="查到了（可能是空的）", kind="ok")],
    config=["无"],
    emits=["无"],
    listens=["无"],
    replaceable=["暂无"],
    failure="只读，随便重试。",
    owner="A（B 包的壳）",
    status="要新做",
)
register(CARD, handler)
