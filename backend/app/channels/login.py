"""登录身份、会话和「归到谁名下」（docs/任务单/12_登录与正规化_设计.md 第五节）。

账号就是入口模块已有的「客户」channels_people；网页聊天、微信客服会话是这个人的「门」，订单挂在门上。这里加的是：
- 登录身份 channels_logins（wx = 服务号 openid、phone = 手机号），L1：有就是那个人，没有就新建一个人挂上；
- 会话：签名 cookie 在 app/core/access.py；这里登记「找到现在的人」「某个门是不是这个人的」给底座的守卫用；
- 合并（L2–L8）：匿名的门在登录时归过来；绑手机号碰到另一个人就合人；认领用哪个门；取消关注删 openid。
原来「码是钥匙、门满不收」（memory.link）照旧管不登录的情况；登录了认的是验证过的身份，合人走 merge_people。
openid、手机号不进日志和事件（规矩 22、23）：事件里只放人 id、登录方式、打码的手机号。
"""

from __future__ import annotations

import re
import secrets

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.channels import memory
from app.channels.models import Contact, Login, Person
from app.core import access
from app.core.db import utcnow
from app.core.events import record_event
from app.intake import orders, service
from app.intake.models import Customer

KINDS = ("wx", "phone")
METHOD_LABELS = {"wx": "微信", "qr": "微信扫码", "sms": "手机号", "email": "邮箱"}
_PHONE_RE = re.compile(r"1[3-9]\d{9}")


# ---------------------------------------------------------------- 手机号

def normalize_phone(raw: str) -> str | None:
    """只认中国大陆手机号：去掉空格、横杠、+86 / 86 前缀后是 1[3-9] 开头 11 位 → E.164（+8613812345678）；不是就 None。"""
    s = re.sub(r"[\s\-()]", "", raw or "")
    if s.startswith("+86"):
        s = s[3:]
    elif s.startswith("86") and len(s) == 13:
        s = s[2:]
    return f"+86{s}" if _PHONE_RE.fullmatch(s) else None


def mask_phone(phone: str) -> str:
    """138****5678（日志、事件、页面上只用这个）。"""
    d = (phone or "")[-11:]
    return f"{d[:3]}****{d[-4:]}" if len(d) == 11 else "***"


# ---------------------------------------------------------------- 身份 → 人

def _canonical(db: Session, person_id: int | None) -> Person | None:
    return memory.person_of(db, person_id)


def identity(db: Session, kind: str, value: str) -> Login | None:
    return db.scalar(select(Login).where(Login.kind == kind, Login.value == value))


def logins_of(db: Session, person_id: int) -> list[Login]:
    return list(db.scalars(select(Login).where(Login.person_id == person_id).order_by(Login.id)))


def has_login(db: Session, person_id: int | None) -> bool:
    return bool(person_id) and db.scalar(select(Login.id).where(Login.person_id == person_id).limit(1)) is not None


def phone_of(db: Session, person_id: int) -> str:
    row = db.scalar(select(Login).where(Login.person_id == person_id, Login.kind == "phone").limit(1))
    return row.value if row is not None else ""


def new_person(db: Session) -> Person:
    p = Person(preferences={}, session_epoch=0, created_at=utcnow(), updated_at=utcnow())
    db.add(p)
    db.flush()
    return p


def login_as(db: Session, kind: str, value: str, *, method: str) -> Person:
    """L1：用某个微信 / 手机号登录。有这个身份 → 那个人（顺着并走的痕迹）；没有 → 新建一个人挂上。"""
    if kind not in KINDS or not value:
        raise ValueError("登录身份不对")
    row = identity(db, kind, value)
    created = row is None
    if row is None:
        p = new_person(db)
        row = Login(person_id=p.id, kind=kind, value=value, created_at=utcnow())
        db.add(row)
    p = _canonical(db, row.person_id)
    if p is None:  # 人被删了（不该发生）：身份挂到新人上
        p = new_person(db)
    if row.person_id != p.id:
        row.person_id = p.id
    row.last_login_at = utcnow()
    db.flush()
    record_event(db, "customer.login", f"person:{p.id}", {"method": method, "new": created})
    return p


# ---------------------------------------------------------------- 合人

def merge_people(db: Session, a: Person, b: Person, *, by: str, why: str) -> Person:
    """两个人确定是同一个人（都验证过）：保留较早的 id，门、登录身份、邮箱全挪过去，偏好按字段取新的，被并的留痕。"""
    if a.id == b.id:
        return a
    keep, drop = (a, b) if a.id < b.id else (b, a)
    for d in memory.doors(db, drop.id):
        orders.set_customer_memory(db, d.id, person_id=keep.id, by=by)
    phones_keep = {x.value for x in logins_of(db, keep.id) if x.kind == "phone"}
    for x in logins_of(db, drop.id):
        if x.kind == "phone" and phones_keep:  # 手机号一个人只留一个：留着 keep 的（调用方要换号会自己处理）
            db.delete(x)
        else:
            x.person_id = keep.id
    mine = {c.email for c in db.scalars(select(Contact).where(Contact.person_id == keep.id))}
    for c in db.scalars(select(Contact).where(Contact.person_id == drop.id)):
        if c.email in mine:
            db.delete(c)
        else:
            c.person_id = keep.id
    keep.preferences = memory.merge_prefs(drop.preferences or {}, keep.preferences or {}, drop.updated_at, keep.updated_at)
    keep.session_epoch = max(keep.session_epoch or 0, drop.session_epoch or 0)
    drop.merged_into_id = keep.id
    drop.updated_at = keep.updated_at = utcnow()
    db.flush()
    record_event(db, "customer.merged", f"person:{keep.id}", {"from": [drop.id], "to": keep.id, "why": why, "by": by})
    memory.refresh(db, keep.id, by=by)
    return keep


def adopt_door(db: Session, person: Person, door: Customer | None, *, by: str) -> tuple[str, Person]:
    """L2 / L3 / L6：把一个门归到登录的人名下。门的人没有登录身份（匿名）→ 那个匿名的人整个并过来；
    已经是这个人的 → mine；是别的有登录身份的人的 → other（不并，不露别人的任何信息）。"""
    if door is None:
        return "none", person
    owner = _canonical(db, door.person_id)
    if owner is not None and owner.id == person.id:
        return "mine", person
    if owner is None:
        orders.set_customer_memory(db, door.id, person_id=person.id, by=by)
        record_event(db, "customer.linked", f"customer:{door.id}", {"person": person.id, "channel": door.channel, "by": by})
        memory.refresh(db, person.id, by=by)
        return "adopted", person
    if has_login(db, owner.id):
        return "other", person
    return "adopted", merge_people(db, person, owner, by=by, why="登录后把这台设备 / 这枚码的单归到名下")


def web_door_for(db: Session, person: Person, browser_door: Customer | None, *, by: str) -> Customer:
    """L5：认领用哪个门。浏览器的门是这个人的（或匿名、刚归过来）→ 用它；否则这个人最近的网页门；都没有 → 建一个。"""
    if browser_door is not None and browser_door.channel == "web":
        state, person = adopt_door(db, person, browser_door, by=by)
        if state in ("mine", "adopted"):
            return browser_door
    webs = [d for d in memory.doors(db, person.id) if d.channel == "web"]
    if webs:
        return max(webs, key=lambda d: (d.last_activity_at or d.created_at, d.id))
    c = service.get_or_create_customer(db, "web", secrets.token_urlsafe(24), source="login")
    orders.set_customer_memory(db, c.id, person_id=person.id, by=by)
    return c


def bind_phone(db: Session, person: Person, phone: str, *, by: str) -> tuple[Person, bool]:
    """L4：已登录的人绑手机号。这个号是另一个人的 → 两边都验证过，合人；这个人原来有别的号 → 换成新号。返回（人, 有没有合人）。"""
    row = identity(db, "phone", phone)
    merged = False
    if row is not None:
        other = _canonical(db, row.person_id)
        if other is not None and other.id != person.id:
            for old in [x for x in logins_of(db, person.id) if x.kind == "phone"]:
                db.delete(old)  # 留验证过的这个新号（在 other 身上）
            db.flush()
            person = merge_people(db, person, other, by=by, why="绑手机号：这个号之前登录过")
            merged = True
        row = identity(db, "phone", phone)
        if row is not None and row.person_id != person.id:
            row.person_id = person.id
    else:
        for old in [x for x in logins_of(db, person.id) if x.kind == "phone"]:
            db.delete(old)
        db.flush()
        db.add(Login(person_id=person.id, kind="phone", value=phone, created_at=utcnow(), last_login_at=utcnow()))
    person.phone_prompt_at = None
    db.flush()
    record_event(db, "customer.phone_bound", f"person:{person.id}", {"phone": mask_phone(phone), "merged": merged, "by": by})
    return person, merged


def forget_wx(db: Session, value: str, *, by: str) -> int | None:
    """L8：服务号取消关注 → 删掉这个 openid 的登录身份、这个人所有设备的会话失效（官方：收到取消关注「需要删除该用户的所有信息」）。
    订单、发票这些交易记录照法定期限留着。返回受影响的人 id。"""
    row = identity(db, "wx", value)
    if row is None:
        return None
    p = _canonical(db, row.person_id)
    db.delete(row)
    db.flush()
    if p is not None:
        bump_epoch(db, p)
        record_event(db, "customer.wx_forgotten", f"person:{p.id}", {"by": by})
    return p.id if p is not None else None


def bump_epoch(db: Session, person: Person) -> None:
    """所有设备都退出：会话代数 +1（并进这个人的那些旧人也一起，免得拿旧人 id 的 cookie 还能用）。"""
    ids, todo = {person.id}, [person.id]
    while todo:
        kids = list(db.scalars(select(Person.id).where(Person.merged_into_id.in_(todo))))
        todo = [k for k in kids if k not in ids]
        ids.update(todo)
    db.execute(update(Person).where(Person.id.in_(ids)).values(session_epoch=Person.session_epoch + 1, updated_at=utcnow()))
    db.flush()
    db.refresh(person)


# ---------------------------------------------------------------- 给底座的守卫登记（app/core/access.py）

def _resolve(db: Session, person_id: int, epoch: int) -> int | None:
    raw = db.get(Person, person_id)
    if raw is None or (raw.session_epoch or 0) != epoch:
        return None
    p = _canonical(db, person_id)
    return p.id if p is not None else None


def owns(db: Session, person_id: int, customer_id: int) -> bool:
    door = db.get(Customer, customer_id)
    if door is None:
        return False
    p = _canonical(db, door.person_id)
    return p is not None and p.id == person_id


access.set_customer_resolver(_resolve, owns)


def person(db: Session, me: access.CurrentCustomer) -> Person:
    p = db.get(Person, me.person_id)
    if p is None:
        raise LookupError("没有这个人")
    return p
