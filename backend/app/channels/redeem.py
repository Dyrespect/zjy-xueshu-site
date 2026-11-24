"""兑换网页（entry.redeem_page 背后的实现）：客人从平台发货内容点开 /c/{CODE}。

- 码能用：显示货号和按钮（留在网页做 / 用微信客服继续）；不能用说清楚为什么；已认领的、是这个浏览器的人显示进度，
  不是的只说「认领过了」，不给货号、进度、单号（入口设计检查 C10）。
- 按钮来自入口登记处（entries.all_specs()）：加一个入口不改这里；微信客服没开时那个按钮不出现。
- 「留在网页做」= 当场认领（order.claim 幂等）再跳 /chat/<key>；同一浏览器再点直接跳聊天。
- 按 IP 限流（防撞库）；查码只读、不算撞库次数。
- 认领前先登录（docs/任务单/12_登录与正规化_设计.md 第七节）：要登录时（后台开关开着、这台设备有登录方式）没登录不让认领（401）；
  登录了，「这码是不是你的」按账号算（换了设备也认得），认领用这个人的网页门（L5），匿名的人认领过的并进来（L6），
  别的账号认领过的拒绝（L7，不给任何那单的信息）。
"""

from __future__ import annotations

import secrets
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.channels import entries, inbound, login, memory
from app.channels.entry_config import EntryConfig, load_entry_config
from app.core.events import record_event
from app.core.nodes import NodeCall, run_node
from app.intake import brief, codes, service
from app.intake.config_store import load_config
from app.intake.models import STAGE_LABELS, Customer, Order

KEY_RE_LEN = (16, 64)

State = Literal["invalid", "not_found", "void", "expired", "unclaimed", "yours", "taken", "taken_joinable", "addon", "legacy"]


class RedeemAction(BaseModel):
    entry: str = Field(description="哪个入口：entry.webchat / entry.wecom；retry 重新输入；brief 去需求卡（09 需求引导）")
    kind: Literal["claim_web", "link", "chat", "retry"]
    label: str
    url: str | None = None
    hint: str = ""
    primary: bool = False


class BuyPlaceOut(BaseModel):
    label: str
    text: str = ""
    url: str = ""


class RedeemOut(BaseModel):
    state: State
    code: str = Field(default="", description="规范写法；认不出时空")
    code_tail: str = ""
    sku_name: str = ""
    hours: int | None = None
    progress: str = ""
    stage_label: str = ""
    actions: list[RedeemAction] = Field(default_factory=list)
    buy: list[BuyPlaceOut] = Field(default_factory=list)
    code_hint: str = ""
    site_url: str = ""
    login_required: bool = Field(default=False, description="认领前要先登录（页面先出登录框）")
    logged_in: bool = False
    login_label: str = Field(default="", description="已登录的账号：微信 / 手机 138****5678")


class ClaimWebOut(BaseModel):
    key: str
    chat_path: str
    state: str = ""
    brief_path: str = Field(default="", description="需求卡还没确认时给：认领完先去点选需求（09 需求引导），再回聊天")


class RedeemRefused(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def web_session(db: Session, key: str | None) -> Customer | None:
    if not key or not (KEY_RE_LEN[0] <= len(key) <= KEY_RE_LEN[1]) or not all(ch.isalnum() or ch in "-_" for ch in key):
        return None
    return db.scalar(select(Customer).where(Customer.channel == "web", Customer.external_id == key))


def _base(ecfg: EntryConfig) -> dict[str, Any]:
    return {"buy": [BuyPlaceOut(**b.model_dump()) for b in ecfg.buy_places], "code_hint": ecfg.code_hint, "site_url": ecfg.site_url}


def page_meta(db: Session) -> RedeemOut:
    """/c（还没输入码）：只给「激活码从哪来、在哪买」。"""
    return RedeemOut(state="invalid", **_base(load_entry_config(db)))


def _entry_actions(db: Session, ecfg: EntryConfig, available: list[str], code: str, *, web: RedeemAction | None,
                   with_wecom: bool = True) -> list[RedeemAction]:
    out: list[RedeemAction] = []
    for spec in entries.all_specs():
        if spec.node_id not in ecfg.redeem_entries:
            continue
        if spec.resume == "claim_here":
            if web is not None:
                out.append(web)
        elif spec.resume == "link" and with_wecom and spec.node_id in available and spec.resume_link is not None:
            url = spec.resume_link(db, code)
            if url:
                out.append(RedeemAction(entry=spec.node_id, kind="link", label=spec.label, url=url, hint=spec.hint))
    if out:
        out[0].primary = True
    return out


def _mine(db: Session, me: Customer | None, person_id: int | None, customer_id: int | None) -> bool:
    """这枚码认领的会话是不是「我」的：登录了按账号（所有门），没登录按这个浏览器的聊天会话（原来的规则）。"""
    if not customer_id:
        return False
    if person_id is not None:
        return login.owns(db, person_id, customer_id)
    return me is not None and customer_id in inbound._session_ids(db, me)


def view(call: NodeCall, raw: str, web_key: str | None, available: list[str], *, person_id: int | None = None,
         login_required: bool = False, login_label: str = "") -> RedeemOut:
    out = _view(call, raw, web_key, available, person_id)
    out.login_required, out.logged_in, out.login_label = login_required, person_id is not None, login_label
    return out


def _view(call: NodeCall, raw: str, web_key: str | None, available: list[str], person_id: int | None) -> RedeemOut:
    db = call.db
    cfg, ecfg = load_config(db), load_entry_config(db)
    base = _base(ecfg)
    code = codes.normalize_code(raw or "")
    if not code:
        return RedeemOut(state="invalid", actions=[RedeemAction(entry="retry", kind="retry", label="重新输入")], **base)
    lk = run_node("code.lookup", call, {"code": code}).output
    tail = code[-4:]
    me = web_session(db, web_key)
    if person_id is not None:  # 登录了：认领到这个账号（12 号设计第七节）
        claim_web = RedeemAction(entry="entry.webchat", kind="claim_web", label="认领到我的账号",
                                 hint="认领后先点选需求，再交资料；换手机、换电脑登录同一个账号都能找到这一单。")
    else:
        claim_web = RedeemAction(entry="entry.webchat", kind="claim_web", label="留在网页做",
                                 hint=entries.spec_by_node("entry.webchat").hint if entries.spec_by_node("entry.webchat") else "")
    if lk.state == "not_found":
        out = RedeemOut(state="not_found", code=code, code_tail=tail,
                        actions=[RedeemAction(entry="retry", kind="retry", label="重新输入")], **base)
    elif lk.state in ("void", "expired"):
        out = RedeemOut(state=lk.state, code=code, code_tail=tail,
                        actions=[RedeemAction(entry="entry.webchat", kind="chat", label="问一下助手", url="/chat", primary=True)], **base)
    elif lk.state in ("paid", "unused_pool"):
        out = RedeemOut(state="unclaimed", code=code, code_tail=tail, sku_name=lk.sku_name, hours=lk.std_hours,
                        actions=_entry_actions(db, ecfg, available, code, web=claim_web), **base)
    elif lk.state == "claimed":
        owner = db.get(Customer, lk.customer_id) if lk.customer_id else None
        mine = _mine(db, me, person_id, lk.customer_id)
        if mine and owner is not None:
            order = db.get(Order, lk.order_id) if lk.order_id else None
            chat_key = _chat_key(db, me, person_id, owner)
            chat = (RedeemAction(entry="entry.webchat", kind="chat", label="回到聊天", url=f"/chat/{chat_key}") if chat_key
                    else RedeemAction(entry="entry.webchat", kind="claim_web", label="在网页继续"))
            acts = _entry_actions(db, ecfg, available, code, web=chat)
            todo = _brief_action(db, order)
            if todo is not None:  # 需求卡还没确认：放最前面（09 需求引导）
                for a in acts:
                    a.primary = False
                acts.insert(0, todo)
            out = RedeemOut(state="yours", code=code, code_tail=tail, sku_name=lk.sku_name, hours=lk.std_hours,
                            progress=_progress(call, order), stage_label=STAGE_LABELS.get(order.stage, "") if order else "",
                            actions=acts, **base)
        else:
            has_web = owner is not None and _owner_has_web(db, owner)
            op = memory.person_of(db, owner.person_id) if owner is not None else None
            owner_logged = op is not None and login.has_login(db, op.id)
            if person_id is not None and owner is not None and not owner_logged:
                join = RedeemAction(entry="entry.webchat", kind="claim_web", label="记到我的账号",
                                    hint="这枚码之前没登录认领过：拿着码的就是这单的人，记过来以后换设备也能看到。")
                out = RedeemOut(state="taken_joinable", code=code, code_tail=tail,
                                actions=_entry_actions(db, ecfg, available, code, web=join), **base)
            elif not has_web and not owner_logged:
                join = RedeemAction(entry="entry.webchat", kind="claim_web", label="在网页继续",
                                    hint="这枚码是在微信里认领的：在网页继续，两边的对话算同一单。")
                out = RedeemOut(state="taken_joinable", code=code, code_tail=tail,
                                actions=_entry_actions(db, ecfg, available, code, web=join), **base)
            else:
                out = RedeemOut(state="taken", code=code, code_tail=tail,
                                actions=_entry_actions(db, ecfg, available, code, web=None), **base)
    elif lk.state == "addon":
        has_order = me is not None and service.current_order(db, me) is not None
        chat = RedeemAction(entry="entry.webchat", kind="claim_web" if has_order else "chat", label="去聊天里用",
                            url=None if has_order else (f"/chat/{me.external_id}" if me else "/chat"))
        out = RedeemOut(state="addon", code=code, code_tail=tail, sku_name=lk.sku_name,
                        actions=_entry_actions(db, ecfg, available, code, web=chat), **base)
    else:  # legacy
        out = RedeemOut(state="legacy", code=code, code_tail=tail, sku_name=lk.sku_name,
                        actions=[RedeemAction(entry="entry.webchat", kind="claim_web", label="去聊天", primary=True)], **base)
    record_event(db, "entry.redeem_viewed", "", {"state": out.state, "code_tail": tail})
    return out


def _chat_key(db: Session, me: Customer | None, person_id: int | None, owner: Customer) -> str:
    """回聊天用哪个会话：这个浏览器的（是这个人的）→ 这个人最近的网页会话 → 认领那个会话（是网页的话）。"""
    if me is not None and (person_id is None or login.owns(db, person_id, me.id)):
        return me.external_id
    if person_id is not None:
        webs = [d for d in memory.doors(db, person_id) if d.channel == "web"]
        if webs:
            return max(webs, key=lambda d: (d.last_activity_at or d.created_at, d.id)).external_id
    return owner.external_id if owner.channel == "web" else ""


def _brief_action(db: Session, order: Order | None) -> RedeemAction | None:
    """需求卡还没确认的单：兑换页上给一个去点选需求的按钮（地址 /b/{交付令牌}，只给这单主人的浏览器）。"""
    if order is None or not brief.editable(order) or brief.confirmed(db, order):
        return None
    s = brief.load_settings(db)
    return RedeemAction(entry="brief", kind="chat", label=s.text("entry_label") or s.text("page_title"),
                        url=brief.brief_path(order), hint=s.text("entry_hint"), primary=True)


def _brief_path(db: Session, order_id: int | None) -> str:
    order = db.get(Order, order_id) if order_id else None
    return brief.brief_path(order) if _brief_action(db, order) is not None else ""


def _owner_has_web(db: Session, owner: Customer) -> bool:
    if owner.channel == "web":
        return True
    p = memory.person_of(db, owner.person_id)
    return p is not None and any(d.channel == "web" for d in memory.doors(db, p.id))


def _progress(call: NodeCall, order: Order | None) -> str:
    from app.channels.texts import customer_progress

    if order is None:
        return ""
    collect = run_node("intake.collect", call, {"order_id": order.id}).output if order.stage in ("claimed", "collecting") else None
    return customer_progress(order, collect)


def claim_web(call: NodeCall, raw: str, web_key: str | None, *, person_id: int | None = None,
              login_required: bool = False) -> ClaimWebOut:
    """「留在网页做」/「在网页继续」：当场认领（或把这个浏览器并进码的主人）再跳聊天。不能用的抛 RedeemRefused。
    要先登录时没登录 401；登录了走 _claim_logged_in（认领到这个账号）。"""
    db = call.db
    cfg = load_config(db)
    code = codes.normalize_code(raw or "")
    if not code:
        raise RedeemRefused(409, cfg.text("claim_not_found"))
    if person_id is None and login_required:
        raise RedeemRefused(401, "先登录，再认领：登录以后这单记在你的账号下，换手机、换电脑都能找到")
    lk = run_node("code.lookup", call, {"code": code}).output
    me = web_session(db, web_key)
    from app.channels.texts import text as entry_text

    if person_id is not None:
        return _claim_logged_in(call, code, lk, me, person_id)

    if lk.state == "not_found":
        raise RedeemRefused(409, entry_text(cfg, "claim_not_found"))
    if lk.state in ("void", "expired"):
        raise RedeemRefused(409, entry_text(cfg, f"claim_{lk.state}"))
    if lk.state == "addon" and (me is None or service.current_order(db, me) is None):
        raise RedeemRefused(409, entry_text(cfg, "claim_addon_no_order", sku_name=lk.sku_name))
    if lk.state == "claimed":
        owner = db.get(Customer, lk.customer_id) if lk.customer_id else None
        mine = me is not None and lk.customer_id in inbound._session_ids(db, me)
        if mine:  # 同一个浏览器（同一个人）再点：直接回聊天（需求卡没确认先去需求卡），不再认领、不再发话
            return ClaimWebOut(key=me.external_id, chat_path=f"/chat/{me.external_id}", state="yours",
                               brief_path=_brief_path(db, lk.order_id))
        if owner is not None and _owner_has_web(db, owner):
            raise RedeemRefused(409, entry_text(cfg, "claim_taken"))
    if me is None:
        me = service.get_or_create_customer(db, "web", secrets.token_urlsafe(24), source="redeem")
    result = inbound.RouteOut(rule="redeem_page", action="claim")
    inbound.do_claim(call, me, code, result=result, welcome=False)
    after = run_node("code.lookup", call, {"code": code}).output
    owned = after.state == "claimed" and after.customer_id in inbound._session_ids(db, me)
    if not owned and not (lk.state == "legacy"):
        raise RedeemRefused(409, entry_text(cfg, "claim_taken" if after.state == "claimed" else "claim_not_found"))
    record_event(db, "entry.redeem_claimed_web", f"customer:{me.id}", {"code_tail": code[-4:], "state": lk.state,
                                                                       "result": result.claim_result})
    return ClaimWebOut(key=me.external_id, chat_path=f"/chat/{me.external_id}", state=lk.state,
                       brief_path=_brief_path(db, after.order_id if after.state == "claimed" else None))


def _claim_logged_in(call: NodeCall, code: str, lk: Any, me: Customer | None, person_id: int) -> ClaimWebOut:
    """登录了的认领（12 号设计 L5–L7）。"""
    from app.channels.texts import text as entry_text
    from app.channels.models import Person

    db = call.db
    cfg = load_config(db)
    person = db.get(Person, person_id)
    if person is None:
        raise RedeemRefused(401, "登录过期了，重新登录")
    if lk.state == "not_found":
        raise RedeemRefused(409, entry_text(cfg, "claim_not_found"))
    if lk.state in ("void", "expired"):
        raise RedeemRefused(409, entry_text(cfg, f"claim_{lk.state}"))
    if lk.state == "claimed":
        owner = db.get(Customer, lk.customer_id) if lk.customer_id else None
        if owner is None:
            raise RedeemRefused(409, entry_text(cfg, "claim_taken"))
        state, person = login.adopt_door(db, person, owner, by="customer")  # 是我的 → mine；匿名的 → 并过来（L6）
        if state not in ("mine", "adopted"):
            raise RedeemRefused(409, entry_text(cfg, "claim_taken"))  # 别的账号的（L7）：不给任何那单的信息
        door = login.web_door_for(db, person, me, by="customer")
        record_event(db, "entry.redeem_claimed_web", f"customer:{door.id}", {"code_tail": code[-4:], "state": "joined_login"})
        return ClaimWebOut(key=door.external_id, chat_path=f"/chat/{door.external_id}", state="yours",
                           brief_path=_brief_path(db, lk.order_id))
    door = login.web_door_for(db, person, me, by="customer")
    if lk.state == "addon" and service.current_order(db, door) is None:
        raise RedeemRefused(409, entry_text(cfg, "claim_addon_no_order", sku_name=lk.sku_name))
    result = inbound.RouteOut(rule="redeem_page", action="claim")
    inbound.do_claim(call, door, code, result=result, welcome=False)
    after = run_node("code.lookup", call, {"code": code}).output
    owned = after.state == "claimed" and login.owns(db, person.id, after.customer_id or 0)
    if not owned and lk.state != "legacy" and lk.state != "addon":
        raise RedeemRefused(409, entry_text(cfg, "claim_taken" if after.state == "claimed" else "claim_not_found"))
    record_event(db, "entry.redeem_claimed_web", f"customer:{door.id}", {"code_tail": code[-4:], "state": lk.state,
                                                                         "result": result.claim_result, "login": True})
    return ClaimWebOut(key=door.external_id, chat_path=f"/chat/{door.external_id}", state=lk.state,
                       brief_path=_brief_path(db, after.order_id if after.state == "claimed" else None))
