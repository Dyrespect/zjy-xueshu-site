"""gate.ready 能不能开工。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.intake import service
from app.intake.models import Order


class GateIn(BaseModel):
    order_id: int
    via: Literal["flow", "call"] = Field(default="call", description="flow：引擎进到「开工判断」这一步时调；call：别的模块说「事实变了，再判断一次」")
    announce: bool = Field(default=True, description="排上时要不要给客人发「排上啦」")


class GateOut(BaseModel):
    decision: str = Field(description="start | wait")
    detail: str = ""
    stage: str = ""


def handler(call: NodeCall, data: GateIn) -> NodeResult:
    o = call.db.get(Order, data.order_id)
    if o is None:
        return NodeResult(exit="wait", output=GateOut(decision="wait", detail="没有这单"))
    if data.via == "flow":
        decision, detail = service.gate_check(call.db, call.ctx, o, announce=data.announce)
        return NodeResult(exit=decision, output=GateOut(decision=decision, detail=detail, stage=o.stage), detail=detail)
    service.refresh_status(call.db, call.ctx, o, announce=data.announce)
    decision = "start" if o.started_at else "wait"
    return NodeResult(exit=decision, output=GateOut(decision=decision, stage=o.stage))


CARD = NodeCard(
    id="gate.ready",
    name="能不能开工",
    description="代码判断，不让模型判断：资料齐（按清单，问 intake.collect）、时长定了、货号装得下、赶得上汇报日、有名额。"
                "都齐就排队（定开工日、承诺几小时交、加急能不能做）；排到今天且当天名额没满就开工。",
    category="关口",
    tech=["Python 纯函数（app/intake/rules.py）", "run_node('intake.collect')", "SQLAlchemy（排期）", "飞书通知"],
    input_model=GateIn,
    output_model=GateOut,
    exits=[NodeExit(key="start", label="开工（进制作中，交接工厂）", kind="ok"),
           NodeExit(key="wait", label="还不能开工（缺什么 / 排在哪天）", kind="wait")],
    config=["daily_quota：每天开工几单", "buffer_days：交付至少比汇报早几天", "queue_horizon_days：排期最远看几天",
            "rush_daily_quota：每天几单加急", "work_start_hour：以后某天开工从几点算",
            "duration_tiers：标准 / 加急时限", "find_refs_extra_hours"],
    emits=["intake.order_queued", "intake.stage"],
    listens=["changed（收到材料、信息改了、加购了、每分钟的排期检查）"],
    replaceable=["以后按渠道或货号分的开工规则：在流程文件里给「开工判断」那一步换节点"],
    failure="判断本身没有副作用；排队那一下写库，在调用方事务里，失败回滚；付了加急但做不了（档位、名额、材料）"
            "按标准做，给负责人记一条「要退加急费」。",
    owner="A",
    status="要改",
)
register(CARD, handler)
