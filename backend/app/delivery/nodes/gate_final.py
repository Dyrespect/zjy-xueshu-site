"""gate.final 最终版发放。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.delivery import versions
from app.delivery.checks import CheckFailed, require_final_allowed
from app.intake import flow, orders
from app.intake.flow import StageError
from app.intake.models import Order


class FinalIn(BaseModel):
    order_id: int
    via: Literal["flow", "call"] = Field(default="call", description="flow：引擎进「已完成」时调；call：后台点「发最终版」或制作方传了最终版")


class FinalOut(BaseModel):
    order_id: int = 0
    released: bool
    stage: str = ""
    file_ids: list[int] = Field(default_factory=list)


def _files(call: NodeCall, o: Order) -> list[int]:
    return [f.id for f in orders.deliverables_for_customer(call.db, o)] if o.finished_at else []


def handler(call: NodeCall, data: FinalIn) -> NodeResult:
    o = call.db.get(Order, data.order_id)
    if o is None:
        return NodeResult(exit="fail", detail="没有这单")
    try:
        require_final_allowed(stage=o.stage, completed_at=o.completed_at or o.finished_at, voided=o.stage == "void",
                              flow_step=o.flow_step)
    except CheckFailed as e:
        call.ctx.notifier.send(f"#{o.id} 有地方想在「{flow.stage_label(o)}」时发最终版，拦下了（{call.by}）", link="/admin/orders", level="urgent", kind="系统异常", who=f"order:{o.id}")
        return NodeResult(exit="fail", detail=str(e))
    if data.via == "flow":
        try:
            released = orders.release_final(call.db, call.ctx, o, by=call.by)  # 先过 require_completed；暂停中不发
        except StageError as e:
            return NodeResult(exit="fail", detail=str(e))
        if released:
            versions.mark_final_released(call.db, o)
        return NodeResult(exit="released" if released else "wait",
                          output=FinalOut(order_id=o.id, released=released, stage=o.stage, file_ids=_files(call, o)),
                          detail="" if released else "还没有最终版文件（或暂停中），叫制作方传了")
    try:
        orders.require_completed(o)
    except StageError as e:
        return NodeResult(exit="fail", detail=str(e))
    flow.emit(call.db, call.ctx, o, "final_ready", by=call.by, why="发最终版")
    released = o.stage == "delivered"
    return NodeResult(exit="released" if released else "wait",
                      output=FinalOut(order_id=o.id, released=released, stage=o.stage, file_ids=_files(call, o)))


CARD = NodeCard(
    id="gate.final",
    name="最终版发放",
    description="订单不是「已完成」就一个最终版文件都不给；到了就在交付页放出可编辑的 pptx、讲稿（和 PDF），"
                "聊天里发交付页链接和 20MB 以内的文件，订单进「已交付」。作废了的不发；还没有最终版文件就叫制作方传，传上来自动再发。",
    category="关口",
    tech=["checks.require_final_allowed + orders.release_final（先过 require_completed）", "待发 intake_outbox → 网页聊天 / 微信客服（≤20MB 发文件）",
          "交付页下载 GET /api/delivery/{token}/final/{file_id}（每次都重新查订单是否已完成）"],
    input_model=FinalIn,
    output_model=FinalOut,
    exits=[NodeExit(key="released", label="发了，已交付", kind="ok"),
           NodeExit(key="wait", label="还没有最终版文件（或暂停中）", kind="wait"),
           NodeExit(key="fail", label="不是已完成，不发", kind="fail")],
    config=["config.delivery.texts.final：放出最终版那句话"],
    emits=["intake.final_released", "intake.stage"],
    listens=["final_ready（最终版传上来了、后台点发最终版）"],
    replaceable=["关口条件不可换（付费流程只能是「已完成」）；放出方式可换：交付页下载（默认）、聊天发文件、以后网盘链接"],
    failure="关口在函数里（require_completed，check.py 第 12 条拦别处绕开）；下载接口不靠前端藏按钮，每次都查；"
            "发过一次进「已交付」，重复调不重复发。",
    owner="E",
    status="已有",
)
register(CARD, handler)
