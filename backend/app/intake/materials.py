"""资料清单（Edison 11-19：「关键还是要做之前要跟他讲清楚，我们要拿到一些什么资料」）。

对客人说的字只有一个来源：设置里各场合的 must / nice（BizConfig.occasions）和 materials（每个场合都要说的几样、几句引导）。
下面这几处都从这里拼，不各写一份：
- 官网价目页、下单页「下单前准备好这些」：site_view → sku.catalog → /api/shop/catalog
- 小鱼售前客人问「要准备什么」：occasion_text(head="visitor")（bot.send_materials 原样发）
- 认领那句话：claim_parts（entry.notice 的 claim_ok，{materials}）
- 场合定了以后一次发全：occasion_text(head="order")（service.send_materials_list、小鱼 record_info 记下场合时）
- 缺了点名要：missing_names（intake.collect 的 ask_text、小鱼「现在的情况」）
除 listed / mark_listed（读写事件记录）外都是纯函数。
"""

from __future__ import annotations

from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.events import Event, record_event
from app.intake.config_store import BizConfig, MaterialLine

LISTED_EVENT = "intake.materials_listed"
BULLET = "· "


def name_of(cfg: BizConfig, occasion: str) -> str:
    rule = cfg.rule(occasion)
    return rule.label(occasion) if rule is not None else occasion


def must_lines(cfg: BizConfig, occasion: str, *, find_refs: bool = False) -> list[MaterialLine]:
    """这个场合必须发的。买了「帮我找文献」：登记成论文的那几样换成「要我们找的文献方向和关键词」（论文我们找）。"""
    rule = cfg.rule(occasion)
    if rule is None:
        return []
    lines = list(rule.must)
    if find_refs and any(m.purpose == "论文" for m in lines):
        lines = [m for m in lines if m.purpose != "论文"]
        if cfg.materials.find_refs_line is not None:
            lines.insert(0, cfg.materials.find_refs_line)
    return lines


def missing_names(cfg: BizConfig, occasion: str, missing_purposes: list[str], *, find_refs: bool = False) -> list[str]:
    """还缺的用途 → 客人听得懂的叫法（必须发的那几样的原话）；设置里没写的用途就用用途名。"""
    lines = must_lines(cfg, occasion, find_refs=find_refs)
    out: list[str] = []
    for p in missing_purposes:
        hit = [m.text for m in lines if m.purpose == p]
        out += hit or [p]
    return list(dict.fromkeys(out))


def required_keys(cfg: BizConfig, sku: str = "", addons: list[str] | set[str] = ()) -> set[str]:
    """每个场合都要说的几样里，哪几样是必需的：看资料清单（checklists）里同 key 的那一项（开工判断照它挡）。"""
    return {i.key for i in cfg.checklists.for_order(sku, addons).items if i.required}


def _line(m: MaterialLine, mark: str = "") -> str:
    return f"{BULLET}{m.text}" + (f"：{m.use}" if m.use.strip() else "") + mark


def blocks(cfg: BizConfig, occasion: str, *, find_refs: bool = False, have: set[str] | None = None,
           done_keys: set[str] | None = None, req_keys: set[str] | None = None) -> str:
    """「必须发的 / 有的话更好」两段（分行写）。have：收到的文件用途（标「收到了」）；done_keys：说过的几样（不再列）。"""
    g = cfg.materials
    rule = cfg.rule(occasion)
    have, done = have or set(), done_keys or set()
    req = required_keys(cfg) if req_keys is None else req_keys
    mark = g.received_mark
    must = [_line(m, mark if m.purpose and m.purpose in have else "") for m in must_lines(cfg, occasion, find_refs=find_refs)
            if not (m.key and m.key in done)]
    nice = [_line(m, mark if m.purpose and m.purpose in have else "") for m in (rule.nice if rule else [])]
    for c in g.common:
        if c.key and c.key in done:
            continue
        (must if c.key in req else nice).append(_line(c))
    parts = []
    if rule is not None and not rule.must and g.other_text.strip():  # 没有固定清单的场合（其他）
        parts.append(g.other_text.strip())
    if must:
        parts.append("\n".join([g.must_title, *must]))
    if nice:
        parts.append("\n".join([g.nice_title, *nice]))
    return "\n\n".join(parts)


def occasion_text(cfg: BizConfig, occasion: str, *, head: Literal["order", "visitor", ""] = "order", find_refs: bool = False,
                  have: set[str] | None = None, done_keys: set[str] | None = None, req_keys: set[str] | None = None,
                  with_rule: bool = True) -> str:
    """一个场合要的资料，完整一遍：开头一句 + 两段 + 「资料齐了才开工」。场合不认识返回空。"""
    if cfg.rule(occasion) is None:
        return ""
    g = cfg.materials
    tpl = {"order": g.order_head, "visitor": g.visitor_head}.get(head, "")
    first = tpl.replace("{name}", name_of(cfg, occasion)).strip() if cfg.occasions[occasion].must else ""
    body = blocks(cfg, occasion, find_refs=find_refs, have=have, done_keys=done_keys, req_keys=req_keys)
    parts = [p for p in (first, body, g.start_rule.strip() if with_rule else "") if p]
    return "\n\n".join(parts)


def shown_occasions(cfg: BizConfig) -> list[str]:
    """官网和总览列哪几个场合、什么顺序（materials.order；空着就列有必须发的那几个）。"""
    keys = [k for k in cfg.materials.order if k in cfg.occasions]
    return keys or [k for k, r in cfg.occasions.items() if r.must]


def overview_text(cfg: BizConfig, *, done_keys: set[str] | None = None, req_keys: set[str] | None = None) -> str:
    """场合还不知道时：按场合各一行主材料（必须发的一样的场合并成一行），再一句每个场合都要说的，最后问场合。"""
    g = cfg.materials
    groups: dict[str, list[str]] = {}
    for k in shown_occasions(cfg):
        rule = cfg.occasions[k]
        groups.setdefault("、".join(m.text for m in rule.must), []).append(rule.label(k))
    lines = [g.overview_head.strip()] + [f"{BULLET}{'、'.join(names)}：{what}" for what, names in groups.items() if what]
    done = done_keys or set()
    req = required_keys(cfg) if req_keys is None else req_keys
    need = [c.text for c in g.common if c.key not in done and c.key in req]
    nice = [c.text for c in g.common if c.key not in done and c.key not in req]
    if need or nice:
        tail = ("另外都要说一声：" + "、".join(need)) if need else ""
        if nice:
            tail += ("；" if tail else "另外") + "、".join(nice) + "有的话也说"
        lines.append(tail + "。")
    if g.overview_tail.strip():
        lines.append(g.overview_tail.strip())
    return "\n".join(x for x in lines if x)


def claim_parts(cfg: BizConfig, *, occasion: str, find_refs: bool, have: set[str], done_keys: set[str],
                req_keys: set[str]) -> dict[str, str]:
    """认领那句话（claim_ok）要的占位符：{materials} 是分行写好的整段；{required_list} / {optional_list} 给后台改过的旧模板用
    （也是分行的，不再挤在一行）。"""
    if occasion and cfg.rule(occasion) is not None:
        materials = occasion_text(cfg, occasion, head="order", find_refs=find_refs, have=have, done_keys=done_keys,
                                  req_keys=req_keys, with_rule=False)
        rule = cfg.occasions[occasion]
        mark = cfg.materials.received_mark
        must = [_line(m, mark if m.purpose in have else "") for m in must_lines(cfg, occasion, find_refs=find_refs)]
        nice = [_line(m) for m in rule.nice]
    else:
        materials = overview_text(cfg, done_keys=done_keys, req_keys=req_keys)
        must = [f"{BULLET}{cfg.occasions[k].label(k)}：{'、'.join(m.text for m in cfg.occasions[k].must)}"
                for k in shown_occasions(cfg)]
        nice = []
    must += [_line(c) for c in cfg.materials.common if c.key in req_keys and c.key not in done_keys]
    nice += [_line(c) for c in cfg.materials.common if c.key not in req_keys and c.key not in done_keys]
    return {"materials": materials, "required_list": ("\n" + "\n".join(must)) if must else "都有了",
            "optional_list": ("\n" + "\n".join(nice)) if nice else "没有"}


def site_view(cfg: BizConfig) -> dict[str, Any]:
    """官网价目页、下单页「下单前准备好这些」那一块要的数据（只有对客的字，没有核对用途、没有给模型的说明）。"""
    g = cfg.materials
    req = required_keys(cfg)
    occ = []
    for k in shown_occasions(cfg):
        r = cfg.occasions[k]
        occ.append({"key": k, "name": r.label(k), "must": [{"text": m.text, "use": m.use} for m in r.must],
                    "nice": [{"text": m.text, "use": m.use} for m in r.nice]})
    return {
        "title": g.site_title, "lead": g.site_lead, "must_title": g.must_title.rstrip("：:"),
        "nice_title": g.nice_title.rstrip("：:"), "common_title": g.common_title, "rule": g.start_rule,
        "common": [{"text": c.text, "use": c.use, "required": c.key in req} for c in g.common],
        "occasions": occ,
    }


# ---------------------------------------------------------------- 发过没有（事件记录，不加表）

def listed(db: Session, order_id: int, occasion: str) -> bool:
    """这单这个场合的资料清单发过没有（认领那句话里带全了也算）。"""
    return occasion in listed_occasions(db, order_id)


def listed_occasions(db: Session, order_id: int) -> set[str]:
    rows = db.scalars(select(Event).where(Event.type == LISTED_EVENT, Event.subject == f"order:{order_id}"))
    return {str((e.content or {}).get("occasion") or "") for e in rows} - {""}


def mark_listed(db: Session, order_id: int, occasion: str, *, via: str) -> None:
    record_event(db, LISTED_EVENT, f"order:{order_id}", {"occasion": occasion, "via": via})
