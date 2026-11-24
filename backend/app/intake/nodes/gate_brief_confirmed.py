"""gate.brief_confirmed 需求卡确认了没有（没确认不开工）。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.intake import brief
from app.intake.models import Order


class BriefGateIn(BaseModel):
    order_id: int
    via: Literal["flow", "call"] = Field(default="call", description="flow：引擎进「需求卡确认了没有」这一步时调；call：别的模块只问一句")


class BriefGateOut(BaseModel):
    confirmed: bool
    method: str = Field(default="", description="customer 客人点「对，开工」| proxy 负责人代确认")
    confirmed_at: datetime | None = None
    detail: str = ""


def handler(call: NodeCall, data: BriefGateIn) -> NodeResult:
    o = call.db.get(Order, data.order_id)
    if o is None:
        return NodeResult(exit="wait", output=BriefGateOut(confirmed=False, detail="没有这单"))
    b = brief.get(call.db, o)
    ok, detail = brief.condition(call.db, o)
    out = BriefGateOut(confirmed=ok, method=b.confirm_method if ok and b else "", confirmed_at=b.confirmed_at if ok and b else None,
                       detail=detail)
    return NodeResult(exit="confirmed" if ok else "wait", output=out, detail=detail)


CARD = NodeCard(
    id="gate.brief_confirmed",
    name="需求卡确认了没有",
    description="客人对着需求确认卡点了「对，开工」（或负责人在后台代客人确认、写明依据）才往开工判断走；没确认就停在收资料。"
                "只看库里的事实，不调模型；认领后 2 小时没确认由入口提醒一次，不自动开工。",
    category="关口",
    tech=["Python（app/intake/brief.py：确认卡按模板拼）", "表 intake_briefs", "设置 intake_kv.brief（题目、选项、默认值、样张）"],
    input_model=BriefGateIn,
    output_model=BriefGateOut,
    exits=[NodeExit(key="confirmed", label="确认了（往开工判断走）", kind="ok"),
           NodeExit(key="wait", label="还没确认（停在收资料，等客人点或负责人代确认）", kind="wait")],
    config=["brief.remind_after_hours：认领后几小时没确认提醒一次（2）", "brief.questions、brief.style：题目、选项、默认值、样张"],
    emits=["intake.stage（引擎记）"],
    listens=["brief_confirmed（客人点「对，开工」、负责人代确认）", "changed（收资料时事实变了）"],
    replaceable=["别的流程不要需求卡（比如免费领取）：流程文件里不放这一步"],
    failure="只读判断，没有副作用，随便重试；确认后又改了需求卡（版本变了）就算没确认，要重新确认。",
    owner="A（需求引导，09 方案）",
    status="要新做",
)
register(CARD, handler)
