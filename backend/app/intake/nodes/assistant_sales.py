"""assistant.sales 接单助手（业务员 + 客服）。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.intake import service
from app.intake.models import Customer


class SalesIn(BaseModel):
    customer_id: int = Field(description="哪个会话要助手回一趟")
    delay: float = Field(default=0.0, ge=0, le=600, description="几秒后跑（连发几条合成一趟）")


class SalesOut(BaseModel):
    queued: bool
    mode: Literal["serve", "visitor_qa", ""] = Field(default="", description="serve 有在走的单；visitor_qa 没认领，只问答")


def handler(call: NodeCall, data: SalesIn) -> NodeResult:
    c = call.db.get(Customer, data.customer_id)
    if c is None or c.human_takeover:
        return NodeResult(exit="skipped", output=SalesOut(queued=False), detail="没有这个会话，或者负责人在接")
    service.enqueue_job(call.db, c, delay=data.delay)
    mode = "serve" if service.current_order(call.db, c) is not None else "visitor_qa"
    return NodeResult(exit="queued", output=SalesOut(queued=True, mode=mode))


CARD = NodeCard(
    id="assistant.sales",
    name="接单助手",
    description="业务员加客服：读代码拼的「现在的情况」，只判断和说话，动作走登记好的工具。没认领的会话只问答（问价、讲交付什么、"
                "发付款方式），不收资料；有在走的单就记信息、登记材料、跟进度、转告制作方、收修改。客人发来的激活码在调模型之前先认领。",
    category="对话",
    tech=["PydanticAI（工具调用）", "DeepSeek（兼容 OpenAI 的接口，地址和模型在配置里）", "工人 app/intake/worker.py 领任务",
          "提示词 app/intake/prompts/规矩.md"],
    input_model=SalesIn,
    output_model=SalesOut,
    exits=[NodeExit(key="queued", label="排进工人队列", kind="ok"),
           NodeExit(key="skipped", label="负责人在接（我来接），不跑", kind="ok")],
    config=["visitor_daily_limit、visitor_global_daily_limit：没认领的会话每天回几条", "approval：哪几类回复先给后台看",
            "faq、welcome_text、deliver_text、notes_text、payment"],
    emits=["intake.bot_run", "intake.tool_called", "intake.outbox_created"],
    listens=["客人新消息", "制作方新消息"],
    replaceable=["模型换只改配置；没认领时的问答可以换成只回固定话术（不调模型）"],
    failure="模型挂了（超时、出错）工人 20 秒后再试一次，都失败发飞书；每一趟留记录（intake_bot_runs）能回放。",
    owner="A（访客问答的规格 D 定）",
    status="已有",
)
register(CARD, handler)
