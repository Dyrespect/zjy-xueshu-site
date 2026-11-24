"""order.claim 认领。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.intake import orders
from app.intake.models import Customer


class ClaimIn(BaseModel):
    customer_id: int = Field(description="交码的会话（intake_customers.id）")
    code: str = Field(min_length=1, max_length=200, description="客人发来的码，原样；夹在一句话里也行")
    channel: Literal["web", "wecom"] = "web"
    wechat_external_userid: str = Field(default="", max_length=128)


class ClaimOut(BaseModel):
    result: str = Field(description="ok | not_found | used | void | expired | wrong | legacy | locked")
    code: str = ""
    order_id: int | None = None
    kind: str = Field(default="", description="base 基础码（一单）| addon 加购码（挂到在走的单）")
    sku_name: str = ""
    detail: str = Field(default="", description="给助手看的一句：为什么用不上")
    locked_until: datetime | None = None
    fails_left: int | None = None
    claimed_by: int | None = Field(default=None, description="码已被认领时认领它的会话，只给入口模块用")


def handler(call: NodeCall, data: ClaimIn) -> NodeResult:
    customer = call.db.get(Customer, data.customer_id)
    if customer is None:
        return NodeResult(exit="fail", output=ClaimOut(result="not_found"), detail="没有这个会话")
    r = orders.claim(call.db, call.ctx, customer, data.code, channel=data.channel,
                     wechat_external_userid=data.wechat_external_userid, by=call.by)
    out = ClaimOut(**{k: getattr(r, k) for k in ClaimOut.model_fields})
    if r.ok:
        return NodeResult(exit="ok", output=out)
    if r.locked_until is not None:
        return NodeResult(exit="wait", output=out, detail="错太多次，锁着")
    return NodeResult(exit="fail", output=out, detail=r.detail or r.result)


CARD = NodeCard(
    id="order.claim",
    name="认领",
    description="会话交出激活码：基础码绑到这一单（码池的码现建一单），会话里还没挂单的消息挂上，订单进「已认领」；"
                "加购码挂到这个人最近活跃的那单。同一会话再交同一枚码算成功；两个人同时交同一枚码只成一个。",
    category="订单",
    tech=["SQLAlchemy 带条件的 UPDATE（第一条语句，原子）", "intake_code_redemptions（code 唯一）", "流程引擎（发 claimed、changed）"],
    input_model=ClaimIn,
    output_model=ClaimOut,
    exits=[NodeExit(key="ok", label="认领上了", kind="ok"),
           NodeExit(key="fail", label="码不对、用过、作废、过期、现在用不上、旧档位", kind="fail"),
           NodeExit(key="wait", label="1 小时错 5 次，锁 1 小时", kind="wait")],
    config=["无（锁的次数和时长写在 codes.py：1 小时 5 次、锁 1 小时）"],
    emits=["intake.code_redeemed", "intake.code_failed", "intake.order_claimed", "intake.addon_added", "intake.stage"],
    listens=["无"],
    replaceable=["第一期由接单助手在调模型之前先认领；入口模块（D）的 entry.route、兑换网页接手后都调这个节点"],
    failure="幂等（认领记录 code 唯一、同一会话再交算成功）；没领到不改库只记一次尝试；码不对、用过、作废、过期算错，"
            "货号对不上、旧码不算错。",
    owner="A",
    status="要改",
)
register(CARD, handler)
