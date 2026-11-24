"""按清单收资料（intake.collect 节点的实现，纯函数）：照这单货号的资料清单算还缺什么、齐没齐、有没有超档。

清单在设置 `checklists`（模块 D 定的格式，docs/任务单/07_入口_设计.md 附录 B）。第一期模块 A 建壳，
D 接手填清单逻辑。「齐」= 必填项都有；篇数没超篇数档（超了 over_band）；时长没超时长档（超了 over_tier）。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.intake import materials, pricing
from app.intake.config_store import BizConfig, ChecklistItem
from app.intake.rules import OrderFacts, duration_ok, effective_papers, required_materials


class ItemState(BaseModel):
    key: str
    label: str
    required: bool
    done: bool
    detail: str = ""


class CollectOut(BaseModel):
    items: list[ItemState] = Field(default_factory=list)
    complete: bool = False
    ask_text: str = Field(default="", description="还缺的必填项，一句话问完")
    blocker: str = Field(default="", description="'' | over_band | over_tier | legacy")
    blocker_detail: str = ""


def _fact(item: ChecklistItem, facts: OrderFacts) -> tuple[bool, str]:
    k = item.key
    if k == "occasion":
        return bool(facts.occasion), facts.occasion
    if k == "duration_min":
        if facts.duration_min is None:
            return False, ""
        if facts.duration_default and not facts.duration_confirmed:
            return False, f"按默认 {facts.duration_min} 分钟问了，客户还没点头"
        return duration_ok(facts), f"{facts.duration_min} 分钟"
    if k == "present_date":
        return facts.present_date is not None, facts.present_date.isoformat() if facts.present_date else ""
    if k == "school":
        return bool(facts.school), facts.school
    if k == "requirements":
        return bool(facts.requirement_quotes or facts.structure_req), ""
    if k == "topic":
        return bool(facts.title or facts.requirement_quotes), facts.title
    v = getattr(facts, k, None)
    return bool(v), str(v or "")


def _files(item: ChecklistItem, facts: OrderFacts, cfg: BizConfig) -> tuple[bool, str, str]:
    """返回 (齐没齐, 说明, 给客人的叫法)。缺主材料时点名缺的那几样，叫法用设置里资料清单的原话（app/intake/materials.py）。"""
    have = {f.purpose for f in facts.files if f.purpose}
    if item.purposes_from == "occasions.required":
        req = required_materials(facts, cfg)
        if req is None:
            return False, "先要知道场合", f"{item.label}（看场合）"
        if facts.occasion == "其他":
            return bool(facts.files), "其他场合：收到东西就行", item.label
        missing = [p for p in req if p not in have]
        names = materials.missing_names(cfg, facts.occasion, missing, find_refs=facts.find_refs)
        return not missing, ("还缺：" + "、".join(missing)) if missing else "都收到了", "、".join(names) or item.label
    if item.purposes:
        ok = any(p in have for p in item.purposes)
        return ok, "", item.label
    return bool(facts.files), "", item.label


def evaluate(facts: OrderFacts, cfg: BizConfig) -> CollectOut:
    checklist = cfg.checklists.for_order(facts.sku, facts.addons)
    items: list[ItemState] = []
    asks: list[str] = []
    for it in checklist.items:
        if it.kind == "files":
            done, detail, name = _files(it, facts, cfg)
        else:
            done, detail = _fact(it, facts)
            name = it.label
        items.append(ItemState(key=it.key, label=it.label, required=it.required, done=done, detail=detail))
        if it.required and not done:
            asks.append(name)
    blocker, why = "", ""
    p = pricing.parse_sku(facts.sku)
    if p is not None and p.kind == "legacy":
        blocker, why = "legacy", "旧档位的码，要负责人处理"
    else:
        t, b = cfg.tier(facts.tier_key), cfg.band(facts.band_key)
        papers, _ = effective_papers(facts)
        if b is not None and papers and papers > b.max_papers:
            blocker, why = "over_band", f"买的是{b.name}，这单要讲 {papers} 篇"
        elif t is not None and facts.duration_min is not None and facts.duration_min > t.max_minutes:
            need = pricing.tier_for_minutes(cfg, facts.duration_min)
            blocker, why = "over_tier", (f"买的是{t.name}档（{t.max_minutes} 分钟以内），这单讲 {facts.duration_min} 分钟"
                                         + (f"，要{need.name}档" if need else ""))
    ask = ("还要：" + "、".join(asks)) if asks else ""
    return CollectOut(items=items, complete=not asks and not blocker, ask_text=ask, blocker=blocker, blocker_detail=why)
