"""intake.collect 按清单收资料（第一期模块 A 建壳，模块 D 接手填清单逻辑）。"""

from __future__ import annotations

from pydantic import BaseModel

from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.intake import collect, service
from app.intake.config_store import load_config
from app.intake.models import Order


class CollectIn(BaseModel):
    order_id: int


def handler(call: NodeCall, data: CollectIn) -> NodeResult:
    o = call.db.get(Order, data.order_id)
    if o is None:
        return NodeResult(exit="blocked", output=collect.CollectOut(blocker="legacy", blocker_detail="没有这单"))
    out = collect.evaluate(service.order_facts(call.db, o), load_config(call.db))
    if out.blocker:
        return NodeResult(exit="blocked", output=out, detail=out.blocker_detail)
    return NodeResult(exit="complete" if out.complete else "missing", output=out, detail=out.ask_text)


CARD = NodeCard(
    id="intake.collect",
    name="按清单收资料",
    description="认领之后照这单货号的资料清单算还缺什么、一条里问完；齐了让 gate.ready 开工；篇数或时长超出货号、"
                "旧档位码这类转负责人。只算，不改库。",
    category="对话",
    tech=["Python 纯函数（app/intake/collect.py）", "设置 checklists（模块 D 定的格式）"],
    input_model=CollectIn,
    output_model=collect.CollectOut,
    exits=[NodeExit(key="complete", label="齐了", kind="ok"),
           NodeExit(key="missing", label="还缺（ask_text 一句话问完）", kind="wait"),
           NodeExit(key="blocked", label="超档、旧档位，要负责人", kind="fail")],
    config=["checklists：每个货号一张资料清单（默认一张、加购替换、个别货号覆盖）", "occasions：各场合必需材料",
            "paper_bands、duration_tiers：篇数、时长上限"],
    emits=["无"],
    listens=["无（被 gate.ready、接单助手调）"],
    replaceable=["清单来源（按货号 / 按场合模板）；「问卷、访谈类不接」以后可以换专门的判断节点"],
    failure="纯函数、没有副作用，随便重试。",
    owner="D（第一期 A 建壳）",
    status="要改",
)
register(CARD, handler)
