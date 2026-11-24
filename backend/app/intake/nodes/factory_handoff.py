"""factory.handoff 交接工厂。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.intake import handoff, service
from app.intake.flow import StageError
from app.intake.models import Order


class HandoffIn(BaseModel):
    order_id: int
    via: Literal["flow", "call"] = Field(default="call", description="flow：引擎进「制作中」时调；call：后台「现在开工」")


class HandoffOut(BaseModel):
    folder: str = ""
    mode: str = ""
    due_hours: int | None = None


def handler(call: NodeCall, data: HandoffIn) -> NodeResult:
    o = call.db.get(Order, data.order_id)
    if o is None:
        return NodeResult(exit="fail", detail="没有这单")
    if data.via == "call":
        try:
            service.start_now(call.db, call.ctx, o)
        except (ValueError, StageError) as e:
            return NodeResult(exit="fail", detail=str(e))
        return NodeResult(exit="ok", output=HandoffOut(folder=o.handoff_folder, due_hours=o.due_hours))
    if o.started_at is not None:
        return NodeResult(exit="ok", output=HandoffOut(folder=o.handoff_folder, due_hours=o.due_hours), detail="已经交接过")
    service.prepare_handoff(call.db, o)
    h = handoff.handoff_order(call.db, call.ctx, o)
    return NodeResult(exit="ok", output=HandoffOut(folder=h.folder, mode=h.mode, due_hours=o.due_hours))


CARD = NodeCard(
    id="factory.handoff",
    name="交接工厂",
    description="开工那一刻把这单交给 PPT 工厂：材料 + 要求.md（档位、页数上限、时限、客户原话、老客户摘要）+ 聊天记录，"
                "直接写进工厂 inbox，或打成交接包等 Mac 来领；同时给制作方写一条开单说明。",
    category="制作",
    tech=["app/intake/handoff.py", "pull 模式：交接包存平台存储，Mac 上 scripts/factory_pull.py 凭令牌来领",
          "direct 模式：直接写 FACTORY_INBOX", "制作方接口 /api/intake/production"],
    input_model=HandoffIn,
    output_model=HandoffOut,
    exits=[NodeExit(key="ok", label="交接了", kind="ok"), NodeExit(key="fail", label="交接不了", kind="fail")],
    config=["HANDOFF_MODE、FACTORY_INBOX、FACTORY_PULL_TOKEN（.env）", "page_rule_text"],
    emits=["intake.handoff", "intake.production_message"],
    listens=["无"],
    replaceable=["以后接 API 做单的小进程，换成调同样接口；交接包格式不变"],
    failure="交接过的不再交（幂等）；写 inbox 失败抛错，调用方事务回滚，订单留在「收资料」，下一分钟的排期检查再试。",
    owner="A（以后归 E）",
    status="已有",
)
register(CARD, handler)
