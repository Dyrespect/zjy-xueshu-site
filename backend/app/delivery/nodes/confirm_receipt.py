"""confirm.receipt 确认收货。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.core.events import record_event
from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.delivery import versions
from app.delivery.checks import DOC
from app.intake import orders
from app.intake.flow import StageError
from app.intake.models import Order


class ConfirmIn(BaseModel):
    order_id: int
    source: Literal["customer", "platform", "auto", "edison", "free", ""] = Field(
        default="", description="customer 客人点确认收货 | platform 平台已完成信号 | auto 超时 3 天 | edison 后台 | free 免费流程")
    via: Literal["flow", "call"] = Field(default="call", description="call：别的模块说「已完成了」；flow：引擎进「确认」这一步时记下来")
    evidence: dict = Field(default_factory=dict, description="平台消息号、点按钮的 IP、超时起算时间、负责人备注")


class ConfirmOut(BaseModel):
    order_id: int
    stage: str
    result: str = Field(default="", description="completed | recorded（平台信号来早了，先记下）| ignored（这个渠道不认这种来源）")
    platform_completed_at: str | None = None


def handler(call: NodeCall, data: ConfirmIn) -> NodeResult:
    db = call.db
    o = db.get(Order, data.order_id)
    if o is None:
        return NodeResult(exit="fail", detail="没有这单")
    if data.via == "flow":
        orders.record_completion(db, call.ctx, o, source=data.source, by=call.by)
        return NodeResult(exit="completed", output=ConfirmOut(order_id=o.id, stage=o.stage, result="completed"))
    source = data.source or "edison"
    if source == "free" and o.flow_key not in versions.settings().DELIVERY_FREE_FLOWS:
        call.ctx.notifier.send(f"#{o.id} 付费单被当成免费单要直接完成（{call.by}），没放行，查一下是哪里调的", link="/admin/orders", level="urgent", kind="系统异常", who=f"order:{o.id}")
        record_event(db, "intake.signal_ignored", f"order:{o.id}", {"kind": "completed", "source": "free", "flow": o.flow_key,
                                                                    "why": "付费流程不认 free", "by": call.by})
        return NodeResult(exit="fail", detail=f"付费单不能当免费单直接完成。怎么改：付费流程只认 customer / auto / platform / edison。"
                                              f"说明：{DOC} 第 4.5 节、第九节 E8")
    if source == "customer":
        record_event(db, "delivery.receipt_clicked", f"order:{o.id}", {"evidence": data.evidence, "by": call.by, "stage": o.stage})
    try:
        result = orders.mark_completed(db, call.ctx, o, source=source, by=call.by)
    except StageError as e:
        return NodeResult(exit="fail", detail=str(e))
    pc = o.platform_completed_at.isoformat() if o.platform_completed_at else None
    return NodeResult(exit=result, output=ConfirmOut(order_id=o.id, stage=o.stage, result=result, platform_completed_at=pc))


CARD = NodeCard(
    id="confirm.receipt",
    name="确认收货",
    description="把「客人确认了 / 平台说完成了 / 三天没回自动确认 / 负责人在后台点了」统一成一件事：订单到「已完成」，接着发最终版。"
                "哪个渠道认哪几种来源只看一张表（平台单客人自己点不算）；平台的「已完成」来得早（还没交水印版）先记成事实"
                " platform_completed_at，到发布水印版那一步直接放最终版。",
    category="关口",
    tech=["流程引擎（发 completed；进「确认」这一步时记下来源和时间）", "交付页「确认收货」按钮（POST /api/delivery/{token}/received）",
          "模块 B 的 3 天计时器（source=auto）", "平台信号（模块 C，source=platform）", "后台「平台已确认收货」（source=edison）"],
    input_model=ConfirmIn,
    output_model=ConfirmOut,
    exits=[NodeExit(key="completed", label="已完成，接着发最终版", kind="ok"),
           NodeExit(key="recorded", label="平台的已完成来早了，先记下（发布水印版时直接放最终版）", kind="wait"),
           NodeExit(key="ignored", label="这个渠道不认这种来源，订单不动", kind="fail"),
           NodeExit(key="fail", label="还没交水印版、平台单客人自己点不算、付费单用了 free", kind="fail")],
    config=["config.delivery.confirm_sources_by_platform：每个渠道认哪几种确认来源（只有这一张表，模块 B 的计时器也读它）",
            "config.auto_confirm_days：自有渠道每交一版水印版几天没回应视为确认（Edison 定 3 天；计时器归模块 B）",
            "DELIVERY_FREE_FLOWS：free 来源只许用在哪些流程"],
    emits=["intake.order_completed", "intake.platform_completed", "intake.signal_ignored", "delivery.receipt_clicked", "intake.stage"],
    listens=["无"],
    replaceable=["五种来源就是同一位置的五个实现：customer 自有按钮、auto 超时、platform 平台信号、edison 后台、free 免费流程"],
    failure="幂等：已经完成的再确认直接返回 completed，不重复发最终版；不在名单里的来源记 intake.signal_ignored、订单不动。",
    owner="E（节点、交付页按钮）；B 计时器、C 平台信号、D 聊天里的确认说法调它",
    status="已有",
)
register(CARD, handler)
