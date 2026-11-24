"""deliver.sla 时限看门。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.core.events import record_event
from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.delivery import sla, versions
from app.intake import service
from app.intake.models import Order


class SlaIn(BaseModel):
    order_id: int
    at_publish: bool = Field(default=False, description="第 1 版刚发布时调一次：交晚了记下来（加急没做到记「退加急费」）")


class SlaOut(BaseModel):
    order_id: int
    due_at: datetime | None = None
    used_ratio: float = 0.0
    state: str = "ok"


def handler(call: NodeCall, data: SlaIn) -> NodeResult:
    db = call.db
    o = db.get(Order, data.order_id)
    if o is None:
        return NodeResult(exit="ok", output=SlaOut(order_id=data.order_id))
    f = sla.facts(db, o, warn_ratio=versions.settings().DELIVERY_SLA_WARN_RATIO)
    out = SlaOut(order_id=o.id, due_at=f.due_at, used_ratio=f.used_ratio, state=f.state)
    if f.state == "ok" or o.stage == "void":
        return NodeResult(exit="ok", output=out)
    when = versions.fmt_when(f.due_at)
    if f.state == "warn":
        if not sla.already(db, o.id, "delivery.sla_warned"):
            record_event(db, "delivery.sla_warned", f"order:{o.id}", {"due_at": f.due_at.isoformat(), "used": f.used_ratio, "by": call.by})
            call.ctx.notifier.send(f"#{o.id} 时限用掉 {round(f.used_ratio * 100)}%，还没交第一版水印版（{when}前要交）", link="/admin/orders", level="digest", kind="交付时限快到", who=f"order:{o.id}")
            if o.started_at is not None:
                service.add_production_message(db, o, "to_maker", "补充要求", f"提醒：这单{when}前要交第一版（时限用掉 "
                                               f"{round(f.used_ratio * 100)}%）。做好就 production_cli.py deliver。", author="system")
        return NodeResult(exit="warn", output=out)
    if not sla.already(db, o.id, "delivery.late"):
        record_event(db, "delivery.late", f"order:{o.id}", {"due_at": f.due_at.isoformat(), "used": f.used_ratio, "rush": o.rush,
                                                            "published_at": f.first_published_at.isoformat() if f.first_published_at else None,
                                                            "by": call.by})
        call.ctx.notifier.send(f"#{o.id} 过了承诺时间（{when}）{'才交第一版' if f.first_published_at else '还没交第一版'}"
                               f"{'，这单是加急，要退加急费' if o.rush else ''}", link="/admin/orders", level="digest", kind="过了承诺时间", who=f"order:{o.id}")
        if o.rush and not sla.already(db, o.id, "delivery.rush_missed"):
            record_event(db, "delivery.rush_missed", f"order:{o.id}", {"due_at": f.due_at.isoformat(), "by": call.by})
            service.add_need(o, "退加急费", f"加急没在 {o.due_hours} 小时内交第一版（{when}前），按规矩退加急费")
    return NodeResult(exit="late", output=out)


CARD = NodeCard(
    id="deliver.sla",
    name="时限看门",
    description="从开工算，快到承诺时间（开工后几小时交第一版水印版）还没交就提醒（飞书 + 制作方会话）；超时记下来，"
                "加急没做到给负责人记一条「退加急费」。只读订单，不改状态。",
    category="运营",
    tech=["交付后台圈 app/delivery/tick.py（每 15 秒看一遍在做第一版的单）", "飞书通知（core.notify）", "制作方会话", "版本表第 1 版的发布时间"],
    input_model=SlaIn,
    output_model=SlaOut,
    exits=[NodeExit(key="ok", label="没事", kind="ok"), NodeExit(key="warn", label="用掉 80% 还没交", kind="wait"),
           NodeExit(key="late", label="过了时限", kind="fail")],
    config=["订单上的 due_hours（开工时按货号和加急定）", "DELIVERY_SLA_WARN_RATIO：0.8（我的建议）"],
    emits=["delivery.sla_warned", "delivery.late", "delivery.rush_missed"],
    listens=["intake.stage（进制作中开始计时）"],
    replaceable=["提醒对象可换（飞书、制作方会话、两边都发）；以后接自动退加急费"],
    failure="每单每种提醒只发一次（查事件表）；只读订单，失败了下一圈再看。",
    owner="E",
    status="已有",
)
register(CARD, handler)
