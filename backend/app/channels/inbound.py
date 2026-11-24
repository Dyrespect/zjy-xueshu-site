"""入站分流（entry.route 节点背后的实现）：客人每发一条先到这里，按规则表（app/channels/flows/entry_default.json）走。

- 有激活码 → order.claim 认领 → customer.memory 合门 → entry.notice 认领结果 + 资料清单（固定话术，不调模型）；
- 有在走的已认领单 → 交给助手（assistant.sales）收资料；文件这时才取；
- 没认领的只给访客问答，每天有上限（会话、全站、网页同一 IP），超了回一句固定的话（当天一次）；
- 没认领时发的文件不收、不下载（微信不调 media/get，网页拒传）。
节点之间只走 run_node；订单的事只走订单中枢的节点和函数（契约第四节第 4 条）。
"""

from __future__ import annotations

import re
from datetime import datetime, time
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.channels import entries, route_rules
from app.channels.entry_config import EntryConfig, load_entry_config
from app.channels.entry_types import InboundMessage, OutboundMessage
from app.core.events import record_event
from app.core.nodes import NodeCall, run_node
from app.intake import clock, codes, materials, service
from app.intake.config_store import BizConfig, load_config
from app.intake.models import Customer, Message, Order, Outbox

CONFIRM_PHRASES = ("确认收货", "确认", "确认收到", "已确认收货")
FILE_KINDS = ("file", "image", "voice", "video")
_PUNCT = re.compile(r"[\s，,。.!！~～?？、；;：:]+")


class RouteOut(BaseModel):
    rule: str = Field(description="命中规则表的哪一条")
    action: str = ""
    order_id: int | None = None
    code: str = ""
    claim_result: str = Field(default="", description="认领时：order.claim 的结果")
    message_id: int | None = Field(default=None, description="存下来的那条客人消息")
    outbox_ids: list[int] = Field(default_factory=list, description="排进待发的回复")
    welcome_outbox_ids: list[int] = Field(default_factory=list, description="要用欢迎语凭证发的（微信进入事件）")
    fetch_file: bool = Field(default=False, description="放行了：入口现在去取文件、交给订单中枢存")
    reply_text: str = Field(default="", description="网页拒收文件时给页面的一句")


# ---------------------------------------------------------------- 访客额度

def _day_start() -> datetime:
    return datetime.combine(clock.today(), time(0), tzinfo=clock.TZ)


def visitor_quota_left(db: Session, cfg: BizConfig, ecfg: EntryConfig, customer: Customer, ip: str) -> bool:
    """没认领的会话今天还能不能问（只算没挂单的客人消息；这一条还没存，所以 +1 后不超就行）。
    网页同一 IP 每天几条由网页入口用底座限流器数好，放在 InboundMessage.ip_quota_ok 里带进来。"""
    start = _day_start()
    mine = db.scalar(select(func.count()).select_from(Message).where(
        Message.customer_id == customer.id, Message.direction == "in", Message.order_id.is_(None),
        Message.created_at >= start)) or 0
    if cfg.visitor_daily_limit and mine + 1 > cfg.visitor_daily_limit:
        return False
    if cfg.visitor_global_daily_limit:
        everyone = db.scalar(select(func.count()).select_from(Message).where(
            Message.direction == "in", Message.order_id.is_(None), Message.created_at >= start)) or 0
        if everyone + 1 > cfg.visitor_global_daily_limit:
            return False
    return True


# ---------------------------------------------------------------- 事实

def find_code(msg: InboundMessage) -> str:
    raw = msg.entered_with if msg.kind == "enter" else msg.text
    if not raw:
        return ""
    for piece in re.split(r"[，,。;；\n&=]+", raw):
        code = codes.normalize_code(piece)
        if code:
            return code
    return codes.normalize_code(raw) or ""


def confirm_said(text: str, phrases: tuple[str, ...] | list[str] = CONFIRM_PHRASES) -> bool:
    t = _PUNCT.sub("", text or "")
    return bool(t) and t in phrases


def extra_content(text: str, code: str) -> bool:
    """消息里除了码还有别的话（「激活码 X，组会 15 分钟」）：认领后再叫助手处理那部分。"""
    t = (text or "").upper()
    for v in (code, code.replace("-", ""), code[4:]):
        if v:
            t = t.replace(v, "")
    t = re.sub(r"激活码|兑换码|我的码|码是|你好|您好|在吗|PSY|[\s\W_]+", "", t)
    return len(t) >= 4


def facts_for(db: Session, call: NodeCall, msg: InboundMessage, customer: Customer, order: Order | None,
              cfg: BizConfig, ecfg: EntryConfig) -> route_rules.Facts:
    code = find_code(msg)
    code_new = False
    if code:
        lk = run_node("code.lookup", call, {"code": code}).output
        mine = set(_session_ids(db, customer))
        code_new = not (lk.state == "claimed" and lk.customer_id in mine and order is not None and lk.order_id == order.id)
    self_confirm = bool(order) and "customer" in cfg.delivery.sources(order.platform or "legacy")
    quota = False
    if order is None and msg.kind not in ("enter", *FILE_KINDS):
        quota = msg.ip_quota_ok and visitor_quota_left(db, cfg, ecfg, customer, msg.ip)
    return route_rules.Facts(
        kind=msg.kind, entry=msg.entry, code=code, code_new=code_new, has_order=order is not None,
        stage=order.stage if order else "", confirm_said=msg.kind == "text" and confirm_said(msg.text, ecfg.confirm_phrases),
        self_confirm=self_confirm, visitor_quota_left=quota)


def _session_ids(db: Session, customer: Customer) -> list[int]:
    if customer.person_id is None:
        return [customer.id]
    return list(db.scalars(select(Customer.id).where(Customer.person_id == customer.person_id))) or [customer.id]


# ---------------------------------------------------------------- 动作

def _store_text(db: Session, ctx: Any, c: Customer, msg: InboundMessage) -> Message | None:
    text = msg.text if msg.kind == "text" else (msg.text or f"[客户发了{msg.kind}，这边看不了内容]")
    return service.receive_text(db, ctx, c, text, channel_msgid=msg.channel_msgid or None, at=msg.at,
                                claim=False, run_bot=False)


def _queue(call: NodeCall, c: Customer, out: OutboundMessage, *, result: RouteOut, welcome: bool = False) -> None:
    spec = entries.spec_for(c.channel)
    if spec is None or not out.text.strip():
        return
    sent = run_node(spec.node_id, call, out).output
    if sent is not None and sent.outbox_id:
        (result.welcome_outbox_ids if welcome else result.outbox_ids).append(sent.outbox_id)


def _notice(call: NodeCall, c: Customer, template: str, *, order_id: int | None = None, code: str = "",
            extra: dict[str, Any] | None = None, purpose: str = "claim", dedupe: str = "") -> OutboundMessage:
    res = run_node("entry.notice", call, {"session_id": c.id, "template": template, "order_id": order_id, "code": code,
                                          "extra": extra or {}, "purpose": purpose, "dedupe_key": dedupe})
    return res.output.message


def _ask_assistant(call: NodeCall, c: Customer, ctx: Any) -> None:
    delay = float(getattr(getattr(ctx, "settings", None), "INTAKE_DEBOUNCE_SECONDS", 0) or 0)
    run_node("assistant.sales", call, {"customer_id": c.id, "delay": delay})


def do_claim(call: NodeCall, c: Customer, code: str, *, result: RouteOut, welcome: bool) -> None:
    """认领 + 合门 + 认领结果那句话（成功时带资料清单）。"""
    db = call.db
    claim = run_node("order.claim", call, {
        "customer_id": c.id, "code": code, "channel": c.channel if c.channel in ("web", "wecom") else "web",
        "wechat_external_userid": c.external_id if c.channel == "wecom" else ""})
    out = claim.output
    result.claim_result = out.result if out is not None else claim.exit
    result.order_id = out.order_id if out is not None else None
    purpose = "welcome" if welcome else "claim"
    msg: OutboundMessage | None = None
    if claim.exit == "ok" and out.kind == "addon":
        order = db.get(Order, out.order_id) if out.order_id else None
        cfg = load_config(db)
        from app.channels.texts import sku_name_of

        msg = _notice(call, c, "claim_addon_ok", order_id=out.order_id, code=out.code, purpose=purpose,
                      extra={"sku_name": out.sku_name, "order_sku": sku_name_of(cfg, order) if order else ""},
                      dedupe=f"addon:{out.code}")
    elif claim.exit == "ok" and out.detail:  # 这个会话（这个人）早就认领过这枚码
        run_node("customer.memory", call, {"action": "link", "session_id": c.id, "code": out.code})
        msg = _notice(call, c, "claim_yours", order_id=out.order_id, code=out.code, purpose=purpose)
    elif claim.exit == "ok":
        run_node("customer.memory", call, {"action": "link", "session_id": c.id, "code": out.code})
        msg = _notice(call, c, "claim_ok", order_id=out.order_id, code=out.code, purpose=purpose,
                      dedupe=f"claim:{out.order_id}")
        order = db.get(Order, out.order_id) if out.order_id else None
        # 场合已经知道：认领那句话里带全了这个场合的资料清单（一条装不下改发了短版的不算），后面不再重发
        if order is not None and order.occasion and msg is not None and \
                materials.occasion_text(load_config(db), order.occasion, with_rule=False).split("\n")[0] in msg.text:
            if not materials.listed(db, order.id, order.occasion):
                materials.mark_listed(db, order.id, order.occasion, via="claim")
    elif out is not None and out.result == "used":
        link = run_node("customer.memory", call, {"action": "link", "session_id": c.id, "code": out.code})
        if link.exit in ("merged", "linked", "noop") and link.output is not None and link.output.person_id \
                and _same_person(db, c, out.claimed_by):
            msg = _notice(call, c, "claim_yours", order_id=out.order_id, code=out.code, purpose=purpose)
        else:
            msg = _notice(call, c, "claim_taken", code=out.code, purpose=purpose)
    else:
        r = out.result if out is not None else "not_found"
        template = {"not_found": "claim_not_found", "void": "claim_void", "expired": "claim_expired", "locked": "claim_locked",
                    "legacy": "claim_legacy"}.get(r, "claim_wrong")
        extra: dict[str, Any] = {"detail": out.detail if out is not None else ""}
        if out is not None and out.locked_until is not None:
            extra["until"] = f"{clock.local_now(out.locked_until):%H:%M}"
        if r == "wrong" and service.current_order(db, c) is None:
            lk = run_node("code.lookup", call, {"code": code}).output
            if lk.state == "addon":
                template, extra = "claim_addon_no_order", {"sku_name": lk.sku_name}
        if claim.exit == "wait":
            template = "claim_locked"
        if r == "legacy":
            call.ctx.notifier.send(f"{service.display_name(c)} 交了一枚旧档位的码 {code}，要你处理", link=f"/admin/conversations/{c.id}", level="urgent", kind="转人工", who=f"customer:{c.id}")
        msg = _notice(call, c, template, code=code, extra=extra, purpose=purpose)
    if msg is not None:
        _queue(call, c, msg, result=result, welcome=welcome)


def _same_person(db: Session, c: Customer, owner_id: int | None) -> bool:
    if owner_id is None:
        return False
    return owner_id in _session_ids(db, c)


def visitor_limited(call: NodeCall, c: Customer, *, result: RouteOut) -> None:
    db = call.db
    told = db.scalar(select(func.count()).select_from(Outbox).where(
        Outbox.customer_id == c.id, Outbox.category == "访客上限", Outbox.created_at >= _day_start())) or 0
    record_event(db, "entry.visitor_limited", f"customer:{c.id}", {"told": bool(told), "by": "entry.route"})
    if not told:
        _queue(call, c, _notice(call, c, "visitor_limited", purpose="limit"), result=result)


def route(call: NodeCall, msg: InboundMessage) -> tuple[str, RouteOut]:
    """返回（出口, 输出）。出口见 entry.route 的说明卡。"""
    db, ctx = call.db, call.ctx
    c = db.get(Customer, msg.session_id)
    if c is None:
        return "ignored", RouteOut(rule="none", action="ignore")
    if msg.channel_msgid and service.is_duplicate(db, c, msg.channel_msgid):
        return "ignored", RouteOut(rule="duplicate", action="ignore")
    cfg, ecfg = load_config(db), load_entry_config(db)
    order = service.current_order(db, c)
    facts = facts_for(db, call, msg, c, order, cfg, ecfg)
    rule = route_rules.pick(route_rules.load_table(ecfg.entry_flow), facts)
    out = RouteOut(rule=rule.id, action=rule.go, order_id=order.id if order else None, code=facts.code)
    record_event(db, "entry.routed", f"customer:{c.id}", {"rule": rule.id, "action": rule.go, "kind": msg.kind,
                                                          "entry": msg.entry, "code_tail": facts.code[-4:]})
    go = rule.go
    if go == "claim":
        welcome = msg.kind == "enter" and bool(msg.welcome_token)
        if msg.kind != "enter":
            m = _store_text(db, ctx, c, msg)
            out.message_id = m.id if m else None
        do_claim(call, c, facts.code, result=out, welcome=welcome)
        if msg.kind != "enter" and out.claim_result == "ok" and extra_content(msg.text, facts.code):
            _ask_assistant(call, c, ctx)
        return ("claimed" if out.claim_result == "ok" else "claim_failed"), out
    if go == "welcome":
        if msg.welcome_token:
            _queue(call, c, _notice(call, c, "welcome_plain", purpose="welcome", dedupe=f"welcome:{msg.welcome_token[-12:]}"),
                   result=out, welcome=True)
        return "ignored", out
    if go == "confirm" and order is not None:
        m = _store_text(db, ctx, c, msg)
        out.message_id = m.id if m else None
        res = run_node("confirm.receipt", call, {"order_id": order.id, "source": "customer",
                                                  "evidence": {"via": msg.entry, "message": out.message_id}})
        if res.exit == "completed":
            return "confirm", out
        _ask_assistant(call, c, ctx)  # 这个渠道不认、或状态不对：交给助手解释
        return "serve", out
    if go == "confirm_on_platform" and order is not None:
        m = _store_text(db, ctx, c, msg)
        out.message_id = m.id if m else None
        _queue(call, c, _notice(call, c, "confirm_on_platform", order_id=order.id, purpose="delivery",
                                dedupe=f"confirm_platform:{order.id}:{order.delivery_round}"), result=out)
        return "confirm", out
    if go == "serve":
        if msg.kind in FILE_KINDS:
            out.fetch_file = True  # 入口去取文件，交给订单中枢 receive_file（它会叫助手）
            return "serve", out
        m = _store_text(db, ctx, c, msg)
        out.message_id = m.id if m else None
        _ask_assistant(call, c, ctx)
        return "serve", out
    if go == "file_refused":
        out.reply_text = load_config(db).text("file_refused")
        record_event(db, "entry.file_refused", f"customer:{c.id}", {"entry": msg.entry, "kind": msg.kind,
                                                                    "name": msg.file_name[:120], "size": msg.file_size})
        if msg.entry != "entry.webchat":  # 网页：上传接口直接回 409 + 这句，不记消息
            got = service.receive_file(db, ctx, c, filename=msg.file_name or f"{msg.kind}文件", data=b"",
                                       kind="voice" if msg.kind == "voice" else ("image" if msg.kind == "image" else "file"),
                                       channel_msgid=msg.channel_msgid or None, at=msg.at)
            if got is not None:
                out.message_id = got[0].id
        return "file_refused", out
    if go == "visitor_qa":
        m = _store_text(db, ctx, c, msg)
        out.message_id = m.id if m else None
        _ask_assistant(call, c, ctx)
        return "visitor_qa", out
    if go == "visitor_limited":
        m = _store_text(db, ctx, c, msg)
        out.message_id = m.id if m else None
        visitor_limited(call, c, result=out)
        return "visitor_limited", out
    return "ignored", out
