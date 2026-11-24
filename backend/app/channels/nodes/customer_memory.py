"""customer.memory 客户与记忆。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.channels import memory
from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.intake.models import Customer, Order


class MemoryIn(BaseModel):
    action: Literal["link", "refresh", "view", "pick_session", "consume"]
    session_id: int | None = None
    order_id: int | None = None
    code: str = ""


class MemoryOut(BaseModel):
    person_id: int | None = None
    merged_from: list[int] = Field(default_factory=list)
    preferences: dict[str, Any] = Field(default_factory=dict)
    brief: str = ""
    session_id: int | None = Field(default=None, description="pick_session：给这单发话该用哪个会话")
    detail: str = ""


def handler(call: NodeCall, data: MemoryIn) -> NodeResult:
    db = call.db
    if data.action == "consume":
        n = memory.consume_events(db)
        return NodeResult(exit="noop" if not n else "linked", output=MemoryOut(detail=f"刷新了 {n} 个人"))
    if data.action == "pick_session":
        o = db.get(Order, data.order_id) if data.order_id else None
        c = memory.pick_session(db, o) if o is not None else None
        return NodeResult(exit="noop", output=MemoryOut(session_id=c.id if c else None, person_id=c.person_id if c else None))
    c = db.get(Customer, data.session_id) if data.session_id else None
    if c is None:
        return NodeResult(exit="refused", output=MemoryOut(detail="没有这个会话"), detail="没有这个会话")
    if data.action == "link":
        r = memory.link(db, c, data.code, by=call.by or "customer.memory")
        out = MemoryOut(person_id=r.person_id, merged_from=r.merged_from, detail=r.detail)
        return NodeResult(exit=r.exit, output=out, detail=r.detail)
    p = memory.ensure_person(db, c)
    if data.action == "refresh":
        prefs = memory.refresh(db, p.id)
        return NodeResult(exit="linked", output=MemoryOut(person_id=p.id, preferences=prefs, brief=memory.memory_brief(prefs)))
    prefs = dict(p.preferences or {})
    return NodeResult(exit="noop", output=MemoryOut(person_id=p.id, preferences=prefs, brief=c.memory_brief or ""))


CARD = NodeCard(
    id="customer.memory",
    name="客户与记忆",
    description="网页、微信是两个门，用同一枚激活码把门合成同一个客户；按事实记偏好（学校、模板、语言、常讲多久、组里要求原话、"
                "上次成品摘要），下次带给助手（【老客户记得的】）和做 PPT 的人（开单说明）。记忆不开新单、不代替付款。",
    category="对话",
    tech=["SQLAlchemy 表 channels_people、channels_memory_cursor", "会话的 person_id、memory_brief、handoff_brief 经 orders.set_customer_memory 写",
          "读事件表按游标消费（后台圈每 30 秒）", "不调模型，摘要由代码拼（app/channels/memory.py）"],
    input_model=MemoryIn,
    output_model=MemoryOut,
    exits=[NodeExit(key="linked", label="这个门挂上了（或刷新了）", kind="ok"),
           NodeExit(key="merged", label="两个客户并成一个", kind="ok"),
           NodeExit(key="refused", label="这个人已经有这种门、且不是这一个", kind="fail"),
           NodeExit(key="noop", label="本来就是、或只读", kind="ok")],
    config=["memory_brief 最多 600 字、handoff_brief 最多 1000 字、带最近 2 单、原话最多 5 条每条 60 字（都是我的建议，写在 memory.py）"],
    emits=["customer.linked", "customer.merged", "customer.link_refused", "customer.memory_updated", "intake.customer_memory"],
    listens=["intake.order_claimed", "intake.stage（到 completed、delivered、void）", "intake.order_completed",
             "intake.final_released", "delivery.revision"],
    replaceable=["摘要拼法可换（以后换模型摘要，写进记忆前要 Edison 看过）", "合并规则可换成更严的「只认同一个微信」"],
    failure="合并在一个事务里；同一对再合并 = noop；事件按游标消费，处理失败不前进游标、下次重试。",
    owner="D",
    status="要新做",
)
register(CARD, handler)
