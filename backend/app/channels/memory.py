"""客户与记忆（customer.memory 节点背后的实现）。

- 网页一个会话、微信一个会话是两个「门」；用同一枚激活码把门合成同一个客户（channels_people），
  会话表的 person_id 经订单中枢的 orders.set_customer_memory 写（契约第二节第 2 条，不直接改表）。
- 合并规则（入口设计卡 6，我的建议）：码是钥匙，但门满了就不再收——
  1. 一个门拿着已认领的码进来，码的主人 P 还没有这种门 → 这个门并进 P；这个门原来属于别的客户 Q 的，Q 整个并进 P；
  2. P 已经有这种门、且不是这一个 → 拒绝；
  3. 保留较早的客户 id；偏好按字段取较新的；每次合并记 customer.merged。
- 偏好只按事实记（订单里的学校、语言、时长、模板、客户原话），不让模型写，不存材料内容；摘要由代码拼。
- 记忆不开新单、不代替付款：这里不碰订单。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.channels.models import MemoryCursor, Person
from app.core.db import utcnow
from app.core.events import Event, record_event
from app.intake import orders, pricing, service
from app.intake.config_store import load_config
from app.intake.models import Customer, FileRecord, Order, ProductionMessage

MEMORY_BRIEF_MAX = 600
HANDOFF_BRIEF_MAX = 1000
PAST_ORDERS = 2
QUOTES_MAX = 5
QUOTE_CHARS = 60
DONE_STAGES = ("completed", "delivered")
LISTEN = ("intake.order_claimed", "intake.order_completed", "intake.final_released", "delivery.revision", "intake.stage")


@dataclass
class LinkResult:
    exit: str  # linked | merged | refused | noop
    person_id: int | None = None
    merged_from: list[int] = field(default_factory=list)
    detail: str = ""


def person_of(db: Session, person_id: int | None) -> Person | None:
    """顺着「并走了」的痕迹找到现在的那个人。"""
    seen: set[int] = set()
    p = db.get(Person, person_id) if person_id else None
    while p is not None and p.merged_into_id and p.id not in seen:
        seen.add(p.id)
        p = db.get(Person, p.merged_into_id)
    return p


def ensure_person(db: Session, customer: Customer, *, by: str = "customer.memory") -> Person:
    p = person_of(db, customer.person_id)
    if p is not None:
        if customer.person_id != p.id:
            orders.set_customer_memory(db, customer.id, person_id=p.id, by=by)
        return p
    p = Person(preferences={}, created_at=utcnow(), updated_at=utcnow())
    db.add(p)
    db.flush()
    orders.set_customer_memory(db, customer.id, person_id=p.id, by=by)
    record_event(db, "customer.linked", f"customer:{customer.id}", {"person": p.id, "channel": customer.channel, "by": by})
    return p


def doors(db: Session, person_id: int) -> list[Customer]:
    return list(db.scalars(select(Customer).where(Customer.person_id == person_id).order_by(Customer.id)))


def link(db: Session, session: Customer, code: str, *, by: str = "customer.memory") -> LinkResult:
    """一个门拿着一枚已认领的码来：并进码的主人。码没认领过就只给这个门建一个人。"""
    from app.intake.orders import lookup_code

    lk = lookup_code(db, code)
    if lk.state != "claimed" or not lk.customer_id:
        p = ensure_person(db, session, by=by)
        return LinkResult("noop", p.id, detail="码还没认领，只给这个会话建了客户")
    owner = db.get(Customer, lk.customer_id)
    if owner is None:
        return LinkResult("noop", detail="认领它的会话不见了")
    target = ensure_person(db, owner, by=by)
    if owner.id == session.id:
        return LinkResult("linked", target.id)
    mine = person_of(db, session.person_id)
    if mine is not None and mine.id == target.id:
        return LinkResult("noop", target.id, detail="本来就是同一个人")
    have = doors(db, target.id)
    if any(d.channel == session.channel and d.id != session.id for d in have):
        record_event(db, "customer.link_refused", f"customer:{session.id}", {
            "person": target.id, "channel": session.channel, "code_tail": code[-4:], "by": by})
        return LinkResult("refused", target.id, detail=f"这枚码的主人已经有一个{_door_name(session.channel)}了")
    moving = doors(db, mine.id) if mine is not None else [session]
    if session not in moving:
        moving.append(session)
    taken = {d.channel for d in have}
    clash = [d for d in moving if d.channel in taken and d.id != session.id]
    if clash:
        record_event(db, "customer.link_refused", f"customer:{session.id}", {
            "person": target.id, "clash": [d.id for d in clash], "code_tail": code[-4:], "by": by})
        return LinkResult("refused", target.id, detail="两边都有同一种入口，合不了")
    # 保留较早的客户 id
    keep, drop = (target, mine) if mine is None or target.id < mine.id else (mine, target)
    movers = moving if keep is target else have
    for d in movers:
        orders.set_customer_memory(db, d.id, person_id=keep.id, by=by)
    merged_from: list[int] = []
    if drop is not None:
        keep.preferences = merge_prefs(drop.preferences or {}, keep.preferences or {}, drop.updated_at, keep.updated_at)
        drop.merged_into_id = keep.id
        drop.updated_at = utcnow()
        merged_from.append(drop.id)
    keep.updated_at = utcnow()
    db.flush()
    record_event(db, "customer.merged", f"person:{keep.id}", {
        "from": merged_from, "to": keep.id, "doors": [d.id for d in movers], "code_tail": code[-4:], "by": by})
    refresh(db, keep.id)
    return LinkResult("merged", keep.id, merged_from)


def _door_name(channel: str) -> str:
    return {"web": "网页聊天", "wecom": "微信客服"}.get(channel, channel)


def merge_prefs(a: dict[str, Any], b: dict[str, Any], a_at: datetime | None, b_at: datetime | None) -> dict[str, Any]:
    """按字段取较新的（b 比 a 新就以 b 为准；空的不覆盖有的）。"""
    def ts(d: datetime | None) -> float:
        return d.timestamp() if d is not None else 0.0

    newer, older = (b, a) if ts(b_at) >= ts(a_at) else (a, b)
    out = dict(older)
    for k, v in newer.items():
        if v not in (None, "", [], {}):
            out[k] = v
    return out


# ---------------------------------------------------------------- 偏好和两份摘要（代码拼，不调模型）

def _orders_of(db: Session, person_id: int) -> list[Order]:
    ids = [d.id for d in doors(db, person_id)]
    if not ids:
        return []
    return list(db.scalars(select(Order).where(Order.customer_id.in_(ids)).order_by(Order.id.desc())))


def _clip(s: str, n: int) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def preferences(db: Session, person_id: int) -> dict[str, Any]:
    cfg = load_config(db)
    all_orders = _orders_of(db, person_id)
    done = [o for o in all_orders if o.stage in DONE_STAGES]
    prefs: dict[str, Any] = {"school": "", "language": "", "usual_minutes": None, "template_file_id": None,
                             "template_name": "", "style_quotes": [], "last_orders": [], "orders_done": len(done)}
    for o in all_orders:  # 新的在前：取第一个有的
        if not prefs["school"] and o.school:
            prefs["school"] = o.school
        if not prefs["language"] and o.language:
            prefs["language"] = o.language
        if prefs["usual_minutes"] is None and o.duration_min and o.stage in DONE_STAGES:
            prefs["usual_minutes"] = o.duration_min
    for o in done:
        tpl = db.scalar(select(FileRecord).where(FileRecord.order_id == o.id, FileRecord.purpose == "模板")
                        .order_by(FileRecord.id.desc()).limit(1))
        if tpl is not None:
            prefs["template_file_id"], prefs["template_name"] = tpl.id, tpl.filename
            break
    quotes: list[str] = []
    for o in done:
        for q in (o.requirement_quotes or []):
            q = _clip(str(q), QUOTE_CHARS)
            if q and q not in quotes:
                quotes.append(q)
    prefs["style_quotes"] = quotes[:QUOTES_MAX]
    for o in done[:PAST_ORDERS]:
        note = db.scalar(select(ProductionMessage).where(
            ProductionMessage.order_id == o.id, ProductionMessage.direction == "to_sales",
            ProductionMessage.kind.in_(("成品", "进度"))).order_by(ProductionMessage.id.desc()).limit(1))
        when = o.finished_at or o.completed_at or o.delivered_at
        prefs["last_orders"].append({
            "order_id": o.id, "sku_name": pricing.sku_name(cfg, o.sku) if o.sku else "", "occasion": o.occasion,
            "title": _clip(o.title, 40), "minutes": o.duration_min, "pages": o.page_count,
            "delivered": when.date().isoformat() if when else "", "revisions": o.revision_used or 0,
            "maker_note": _clip(note.text, 120) if note is not None else "",
        })
    return prefs


def memory_brief(prefs: dict[str, Any]) -> str:
    """给助手：【老客户记得的】。照这些少问已知项；模板问一句还用不用上次那个。"""
    parts: list[str] = []
    for lo in prefs.get("last_orders", []):
        bits = [lo["sku_name"], lo["occasion"], f"《{lo['title']}》" if lo["title"] else "",
                f"{lo['minutes']} 分钟" if lo["minutes"] else "", f"改了 {lo['revisions']} 轮" if lo["revisions"] else ""]
        parts.append(f"{lo['delivered'] or '之前'}做过：" + "，".join(b for b in bits if b))
    if prefs.get("school"):
        parts.append(f"学校：{prefs['school']}")
    if prefs.get("language"):
        parts.append(f"语言：{prefs['language']}")
    if prefs.get("usual_minutes"):
        parts.append(f"上次讲 {prefs['usual_minutes']} 分钟")
    if prefs.get("template_name"):
        parts.append(f"上次发过模板「{prefs['template_name']}」")
    if prefs.get("style_quotes"):
        parts.append("组里要求原话：" + "".join(f"「{q}」" for q in prefs["style_quotes"]))
    return _clip("；".join(parts), MEMORY_BRIEF_MAX) if parts else ""


def handoff_brief(prefs: dict[str, Any]) -> str:
    """给制作方：进开单说明（订单中枢 handoff.render_requirements 读 customer.handoff_brief）。"""
    if not prefs.get("last_orders"):
        return ""
    lines = [f"老客户（做完过 {prefs.get('orders_done', 0)} 单）。"]
    for lo in prefs["last_orders"]:
        bits = [lo["sku_name"], lo["occasion"], f"《{lo['title']}》" if lo["title"] else "",
                f"{lo['minutes']} 分钟" if lo["minutes"] else "", f"{lo['pages']} 页" if lo["pages"] else "",
                f"改了 {lo['revisions']} 轮" if lo["revisions"] else "没改"]
        lines.append(f"上次（{lo['delivered'] or '之前'}，单 {lo['order_id']:05d}）：" + "，".join(b for b in bits if b) + "。")
        if lo.get("maker_note"):
            lines.append(f"当时交付的说明：{lo['maker_note']}")
    if prefs.get("style_quotes"):
        lines.append("客户说过的要求（原话）：" + "".join(f"「{q}」" for q in prefs["style_quotes"]))
    if prefs.get("template_name"):
        lines.append(f"上次用的模板：{prefs['template_name']}（文件 #{prefs['template_file_id']}）；这次先问客户还用不用，不自动套。")
    if prefs.get("school"):
        lines.append(f"学校：{prefs['school']}。")
    return _clip("\n".join(lines), HANDOFF_BRIEF_MAX)


def refresh(db: Session, person_id: int, *, by: str = "customer.memory") -> dict[str, Any]:
    p = person_of(db, person_id)
    if p is None:
        return {}
    prefs = preferences(db, p.id)
    p.preferences = prefs
    p.updated_at = utcnow()
    mb, hb = memory_brief(prefs), handoff_brief(prefs)
    for d in doors(db, p.id):
        if d.memory_brief != mb or d.handoff_brief != hb:
            orders.set_customer_memory(db, d.id, memory_brief=mb, handoff_brief=hb, by=by)
    record_event(db, "customer.memory_updated", f"person:{p.id}", {"orders_done": prefs.get("orders_done", 0), "by": by})
    return prefs


def pick_session(db: Session, order: Order) -> Customer | None:
    """给这单发话选哪个门：这个人最近说过话的门；微信窗口关着、他又有网页门，就发网页。"""
    owner = db.get(Customer, order.customer_id) if order.customer_id else None
    if owner is None:
        return None
    p = person_of(db, owner.person_id)
    candidates = doors(db, p.id) if p is not None else [owner]
    if not candidates:
        return owner
    candidates.sort(key=lambda c: c.last_customer_msg_at or c.created_at, reverse=True)
    top = candidates[0]
    if top.channel == "wecom" and not service.window_info(db, top)["can_send"]:
        web = next((c for c in candidates if c.channel == "web"), None)
        if web is not None:
            return web
    return top


# ---------------------------------------------------------------- 事件消费（后台圈调）

def consume_events(db: Session, *, limit: int = 200) -> int:
    """订单认领、完成、放最终版、改稿、到「已交付 / 作废」时刷新这个人的记忆。按游标消费，失败不前进。"""
    cur = db.get(MemoryCursor, "memory")
    if cur is None:
        last = db.scalar(select(func.max(Event.id))) or 0
        cur = MemoryCursor(name="memory", last_event_id=last)  # 第一次：从现在开始，不回头扫历史
        db.add(cur)
        db.flush()
        return 0
    rows = list(db.scalars(select(Event).where(Event.id > cur.last_event_id, Event.type.in_(LISTEN))
                           .order_by(Event.id).limit(limit)))
    newest = db.scalar(select(func.max(Event.id))) or cur.last_event_id
    people: set[int] = set()
    for ev in rows:
        if ev.type == "intake.stage" and (ev.content or {}).get("to") not in ("delivered", "void", "completed"):
            continue
        if not ev.subject.startswith("order:"):
            continue
        try:
            o = db.get(Order, int(ev.subject.split(":", 1)[1]))
        except ValueError:
            continue
        c = db.get(Customer, o.customer_id) if o is not None and o.customer_id else None
        if c is None:
            continue
        people.add(ensure_person(db, c).id)
    for pid in people:
        refresh(db, pid)
    cur.last_event_id = rows[-1].id if len(rows) == limit else newest
    return len(people)
