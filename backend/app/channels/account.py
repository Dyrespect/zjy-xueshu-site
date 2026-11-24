"""账号和「我的订单」（/api/channels/account/*；12 号设计第五、七、十节）。

账号就是入口模块的「客户」（channels_people）；会话是 app/core/access.py 的签名 cookie（psy_sess，30 天）。登录方式在
login_web.py（微信里静默、电脑扫码、手机号）；这里是：
- /session：登没登录、怎么登的、这台设备能用哪些登录方式、该不该提示绑手机号（没登录也回，页面靠它决定出什么）；
- /logout：退出这台设备，或所有设备都退出（会话代数 +1）；
- /adopt：登录后把这台设备上匿名的聊天会话归到名下（L2 / L3）；
- /order-link：交付页、需求卡、聊天页顶上那一条「登录后记到你的账号」（GET 看关系，POST 记过来；L2 / L6）；
- /orders、/orders/{单号}：我的订单（守卫 owned_order：不是自己的单一律 404）；
- 邮箱（原来就有，配了邮件服务才开）：在聊天里绑邮箱；「订单号 + 邮箱验证码」登录——对了以后发同一个会话 cookie。
  令牌和过期不自己造：验证码挑战用 itsdangerous 签名，码只以 HMAC 放进签名里；订单号和邮箱对不上照样回「已发」。
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.channels import limits, login, mailer, memory, sms, web
from app.channels.login_web import methods_for
from app.channels.mailer import EMAIL_RE
from app.channels.models import Contact, Person
from app.channels.redeem import web_session
from app.channels.runtime import ChannelsRuntime, channels_dep
from app.channels.texts import customer_progress, sku_name_of
from app.core import access
from app.core.db import get_db, get_write_db, utcnow
from app.core.events import record_event
from app.core.net import client_ip, ua_kind
from app.core.nodes import NodeCall, run_node
from app.intake import brief, flow
from app.intake.config_store import load_config
from app.intake.models import STAGE_LABELS, Customer, Order

router = APIRouter(prefix="/account", tags=["channels"])

CODE_TTL = 600  # 邮箱验证码 10 分钟
PHONE_PROMPT_SNOOZE = timedelta(days=7)  # 点「先不绑」后 7 天内需求卡不再弹
Purpose = Literal["bind", "login"]


# ---------------------------------------------------------------- 当前客户、单子归属（守卫）

def owned_order(order_no: str, request: Request, db: Session = Depends(get_db)) -> Order:
    """/{order_no} 这类路由的守卫：要登录，且这单挂在当前客户的某个门上；不是一律 404（不说 403，不暴露存在）。"""
    me = access.require_customer(request, db)
    o = _order_by_no(db, order_no)
    access.require_owned(db, me, o.customer_id if o is not None else None)
    return o


def _order_by_no(db: Session, order_no: str) -> Order | None:
    digits = "".join(ch for ch in order_no or "" if ch.isdigit())
    if not digits or len(digits) > 9:
        return None
    o = db.get(Order, int(digits))
    return o if o is not None and o.flow_step else None


def _orders_of(db: Session, person_id: int) -> list[Order]:
    ids = [d.id for d in memory.doors(db, person_id)]
    if not ids:
        return []
    return [o for o in db.scalars(select(Order).where(Order.customer_id.in_(ids)).order_by(Order.id.desc())) if o.flow_step]


def _chat_key_of(db: Session, person_id: int) -> str:
    webs = [d for d in memory.doors(db, person_id) if d.channel == "web"]
    return max(webs, key=lambda d: (d.last_activity_at or d.created_at, d.id)).external_id if webs else ""


# ---------------------------------------------------------------- 会话

def account_label(method: str, phone: str) -> str:
    """账号那一行：手机号登录的「手机 138****5678」；微信登录的「微信」，绑了手机号再加「 · 手机 138****5678」。"""
    masked = f"手机 {login.mask_phone(phone)}" if phone else ""
    if method == "sms":
        return masked or "手机号"
    base = login.METHOD_LABELS.get(method, "已登录")
    return f"{base} · {masked}" if masked else base


class SessionOut(BaseModel):
    logged_in: bool
    method: str = ""  # wx / qr / sms / email
    label: str = ""  # 「微信」「手机 138****5678」
    phone: str = ""  # 打码的
    phone_bound: bool = False
    prompt_phone: bool = False  # 需求卡上该不该弹「绑手机号」
    methods: list[str] = Field(default_factory=list, description="这台设备能用的登录方式：wx / qr / sms")
    device: str = ""  # wechat / mobile / pc
    sms: bool = False
    email: bool = False  # 「订单号 + 邮箱」老入口开着没有
    login_required: bool = False  # 认领前要不要先登录
    chat_key: str = ""  # 这个人最近的网页聊天会话（换了设备也能回到聊天）


@router.get("/session", response_model=SessionOut, dependencies=[Depends(access.public)])
def session(request: Request, response: Response, rt: ChannelsRuntime = Depends(channels_dep),
            db: Session = Depends(get_write_db)) -> SessionOut:
    from app.channels.login_web import login_required

    me = access.current_customer(request, db)
    methods = methods_for(request, rt)
    out = SessionOut(logged_in=False, methods=methods, device=ua_kind(request.headers.get("user-agent", "")),
                     sms=sms.enabled(request), email=mailer.enabled(), login_required=login_required(request, rt, db))
    if me is None:
        if request.cookies.get(access.COOKIE_NAME):
            access.clear_session(response)  # 过期、退出了所有设备：顺手清掉
        return out
    p = db.get(Person, me.person_id)
    phone = login.phone_of(db, me.person_id)
    out.logged_in, out.method = True, me.method
    out.phone, out.phone_bound = (login.mask_phone(phone) if phone else ""), bool(phone)
    out.label = account_label(me.method, phone)
    snoozed = p is not None and p.phone_prompt_at is not None and utcnow() - p.phone_prompt_at < PHONE_PROMPT_SNOOZE
    out.prompt_phone = out.sms and not phone and not snoozed
    out.chat_key = _chat_key_of(db, me.person_id)
    if utcnow().timestamp() - me.issued_at > access.REFRESH_AFTER and p is not None:  # 每天第一次打开顺延 30 天
        access.issue_session(request, response, person_id=me.person_id, epoch=p.session_epoch or 0, method=me.method)
    return out


class LogoutIn(BaseModel):
    all: bool = False


class OkOut(BaseModel):
    ok: bool = True
    masked: str = ""
    state: str = ""
    message: str = ""


@router.post("/logout", response_model=OkOut)
def logout(body: LogoutIn, request: Request, response: Response, db: Session = Depends(get_db),
           me: access.CurrentCustomer = Depends(access.require_customer)) -> OkOut:
    if body.all:
        login.bump_epoch(db, login.person(db, me))
    record_event(db, "customer.logout", f"person:{me.person_id}", {"all": body.all})
    db.commit()
    access.clear_session(response)
    return OkOut(message="所有设备都退出了" if body.all else "退出了")


@router.post("/phone/skip", response_model=OkOut)
def phone_skip(db: Session = Depends(get_db), me: access.CurrentCustomer = Depends(access.require_customer)) -> OkOut:
    p = login.person(db, me)
    p.phone_prompt_at = utcnow()
    db.commit()
    return OkOut(message="好，先不绑；以后在「我的订单」里也能绑")


class AdoptIn(BaseModel):
    key: str | None = Field(default=None, max_length=64)


@router.post("/adopt", response_model=OkOut)
def adopt(body: AdoptIn, db: Session = Depends(get_db), me: access.CurrentCustomer = Depends(access.require_customer)) -> OkOut:
    """登录后：这台设备上存着的聊天会话是匿名的 → 归到我名下（L2）；是别人的（有登录身份）→ 不动、不说是谁的（L3）。"""
    door = web_session(db, body.key)
    state, _ = login.adopt_door(db, login.person(db, me), door, by="customer")
    db.commit()
    return OkOut(state="other" if state == "other" else state)


# ---------------------------------------------------------------- 「登录后记到你的账号」（交付页、需求卡、聊天页顶上那一条）

class LinkOut(BaseModel):
    state: Literal["login", "bind", "mine", "none"]
    methods: list[str] = Field(default_factory=list)


class LinkIn(BaseModel):
    token: str | None = Field(default=None, max_length=64)
    chat_key: str | None = Field(default=None, max_length=64)


def _door_of(db: Session, token: str | None, chat_key: str | None) -> Customer | None:
    if chat_key:
        return web_session(db, chat_key)
    if token and 16 <= len(token) <= 64 and all(ch.isalnum() or ch in "-_" for ch in token):
        o = db.scalar(select(Order).where(Order.delivery_token == token))
        return db.get(Customer, o.customer_id) if o is not None and o.customer_id else None
    return None


@router.get("/order-link", response_model=LinkOut, dependencies=[Depends(access.by_token)])
def order_link(request: Request, token: str | None = None, chat_key: str | None = None,
               rt: ChannelsRuntime = Depends(channels_dep), db: Session = Depends(get_db)) -> LinkOut:
    """这个令牌的单（或这个聊天）和当前登录的人什么关系：login 没登录（有登录方式才给）/ bind 匿名的、可以记过来 /
    mine 已经是我的 / none 别人的或用不上（不显示那一条，也不说是谁的）。"""
    door = _door_of(db, token, chat_key)
    methods = methods_for(request, rt)
    if door is None:
        return LinkOut(state="none")
    me = access.current_customer(request, db)
    if me is None:
        return LinkOut(state="login" if methods else "none", methods=methods)
    owner = login._canonical(db, door.person_id)
    if owner is not None and owner.id == me.person_id:
        return LinkOut(state="mine")
    if owner is None or not login.has_login(db, owner.id):
        return LinkOut(state="bind")
    return LinkOut(state="none")


@router.post("/order-link", response_model=OkOut, dependencies=[Depends(access.by_token)])
def order_link_bind(body: LinkIn, db: Session = Depends(get_db),
                    me: access.CurrentCustomer = Depends(access.require_customer)) -> OkOut:
    """把匿名的单记到我名下（令牌是凭证：拿着交付令牌 / 聊天 key 的就是这单的人）。是别人账号的 → 404。"""
    door = _door_of(db, body.token, body.chat_key)
    state, _ = login.adopt_door(db, login.person(db, me), door, by="customer")
    if state in ("other", "none"):
        raise HTTPException(404, detail="没有这一单")
    db.commit()
    return OkOut(state=state, message="记到你的账号下了，以后在「我的订单」里就能看到")


# ---------------------------------------------------------------- 我的订单

class MyOrder(BaseModel):
    order_no: str
    sku_name: str
    stage: str
    stage_label: str
    progress: str
    claimed_at: str | None = None
    delivery_path: str
    brief_path: str | None = None  # 需求卡还没确认时给
    chat_path: str | None = None
    invoice_hint: str = ""


class MyOrdersOut(BaseModel):
    masked: str
    label: str = ""
    orders: list[MyOrder]


def _my_order(db: Session, o: Order, chat_key: str) -> MyOrder:
    cfg = load_config(db)
    todo = brief.editable(o) and not brief.confirmed(db, o)
    return MyOrder(
        order_no=f"{o.id:05d}", sku_name=sku_name_of(cfg, o), stage=o.stage, stage_label=STAGE_LABELS.get(o.stage, o.stage),
        progress=customer_progress(o), claimed_at=o.claimed_at.isoformat() if o.claimed_at else None,
        delivery_path=f"/d/{o.delivery_token}", brief_path=brief.brief_path(o) if todo else None,
        chat_path=f"/chat/{chat_key}" if chat_key else None,
        invoice_hint="发票在交付页里申请和下载" if o.stage in ("completed", "delivered") else "订单完成后能在交付页申请发票",
    )


@router.get("/orders", response_model=MyOrdersOut)
def my_orders(request: Request, db: Session = Depends(get_db),
              me: access.CurrentCustomer = Depends(access.require_customer)) -> MyOrdersOut:
    """当前客户所有门上的单（网页、微信客服、合过来的），新的在前。"""
    key = _chat_key_of(db, me.person_id)
    phone = login.phone_of(db, me.person_id)
    label = account_label(me.method, phone)
    return MyOrdersOut(masked=label, label=label, orders=[_my_order(db, o, key) for o in _orders_of(db, me.person_id)])


@router.get("/orders/{order_no}", response_model=MyOrder)
def my_order(request: Request, order: Order = Depends(owned_order), db: Session = Depends(get_db)) -> MyOrder:
    me = access.current_customer(request, db)
    return _my_order(db, order, _chat_key_of(db, me.person_id) if me else "")


# ---------------------------------------------------------------- 邮箱（配了邮件服务才开；原来就有）

def _secret(request: Request) -> str:
    return access._secret(request)


def _serializer(request: Request, salt: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_secret(request), salt=f"entry.account.{salt}")


def _code_mac(request: Request, purpose: str, email: str, ref: int, code: str) -> str:
    return hmac.new(_secret(request).encode(), f"{purpose}|{email}|{ref}|{code}".encode(), hashlib.sha256).hexdigest()


def _challenge(request: Request, purpose: str, email: str, ref: int, code: str) -> str:
    return _serializer(request, "challenge").dumps({"p": purpose, "e": email, "r": ref, "h": _code_mac(request, purpose, email, ref, code)})


def _check_code(request: Request, challenge: str, purpose: str, email: str, ref: int, code: str) -> None:
    if not limits.limiter(request.app).hit("entry.account_verify", email, limit=8, window=CODE_TTL):
        raise HTTPException(429, detail="试错次数太多了，10 分钟后重新发一个验证码")
    try:
        data = _serializer(request, "challenge").loads(challenge, max_age=CODE_TTL)
    except SignatureExpired as e:
        raise HTTPException(400, detail="验证码过期了，重新发一个") from e
    except BadSignature as e:
        raise HTTPException(400, detail="验证码不对") from e
    ok = (data.get("p") == purpose and data.get("e") == email and data.get("r") == ref
          and hmac.compare_digest(str(data.get("h", "")), _code_mac(request, purpose, email, ref, code.strip())))
    if not ok:
        raise HTTPException(400, detail="验证码不对")


def _on() -> None:
    if not mailer.enabled():
        raise HTTPException(404, detail="Not Found")


def _email(raw: str) -> str:
    e = (raw or "").strip().lower()
    if len(e) > 120 or not EMAIL_RE.match(e):
        raise HTTPException(400, detail="邮箱格式不对，例如 name@example.edu.cn")
    return e


def _mask(email: str) -> str:
    name, _, host = email.partition("@")
    return f"{name[:2]}***@{host}"


def _call(db: Session, rt: ChannelsRuntime) -> NodeCall:
    flow.ensure_nodes()
    return NodeCall(db, rt.intake.ctx, "customer")


def _send_code(request: Request, call: NodeCall, email: str, code: str, why: str) -> None:
    ip = client_ip(request)
    lim = limits.limiter(request.app)
    if not lim.hit("entry.account_send_ip", ip, limit=10, window=3600) or not lim.hit("entry.account_send", email, limit=5, window=3600):
        raise HTTPException(429, detail="验证码发得太频繁了，过一会儿再试")
    text = (f"你的验证码是 {code}，10 分钟内有效，用来{why}。\n\n"
            "不是你本人操作的话不用管这封信。\nPsyEngine 心理学汇报 PPT 定制（杭州竹涧云科技有限公司）")
    r = run_node("notify.email", call, {"to": email, "subject": f"验证码 {code}（PsyEngine 心理学汇报 PPT 定制）", "text": text})
    if r.exit != "sent":
        raise HTTPException(503, detail="邮件没发出去，过一会儿再试")


def _new_code() -> str:
    import secrets

    return f"{secrets.randbelow(1_000_000):06d}"


def _owner_session(db: Session, chat_key: str | None, delivery_token: str | None) -> Customer:
    if chat_key:
        return web._customer(db, chat_key)
    if delivery_token:
        o = db.scalar(select(Order).where(Order.delivery_token == delivery_token))
        c = db.get(Customer, o.customer_id) if o is not None and o.customer_id else None
        if c is not None:
            return c
    raise HTTPException(404, detail="找不到这个聊天或订单")


def _emails_of(db: Session, person_id: int | None) -> set[str]:
    p = memory.person_of(db, person_id)
    if p is None:
        return set()
    return set(db.scalars(select(Contact.email).where(Contact.person_id == p.id)))


class StatusOut(BaseModel):
    enabled: bool


class BindStartIn(BaseModel):
    chat_key: str | None = Field(default=None, max_length=64)
    delivery_token: str | None = Field(default=None, max_length=64)
    email: str = Field(max_length=120)


class BindVerifyIn(BindStartIn):
    code: str = Field(min_length=4, max_length=8)
    challenge: str = Field(min_length=10, max_length=600)


class LoginStartIn(BaseModel):
    order_no: str = Field(min_length=1, max_length=20)
    email: str = Field(max_length=120)


class LoginVerifyIn(LoginStartIn):
    code: str = Field(min_length=4, max_length=8)
    challenge: str = Field(min_length=10, max_length=600)


class SentOut(BaseModel):
    challenge: str
    masked: str
    message: str


class TokenOut(BaseModel):
    ok: bool = True
    masked: str


@router.get("/status", response_model=StatusOut, dependencies=[Depends(access.public)])
def status() -> StatusOut:
    """邮箱这条老入口开着没有（聊天里「留邮箱」按钮看它）。"""
    return StatusOut(enabled=mailer.enabled())


@router.post("/bind/start", response_model=SentOut, dependencies=[Depends(access.by_token)])
def bind_start(body: BindStartIn, request: Request, rt: ChannelsRuntime = Depends(channels_dep),
               db: Session = Depends(get_db)) -> SentOut:
    _on()
    email = _email(body.email)
    c = _owner_session(db, body.chat_key, body.delivery_token)
    code = _new_code()
    _send_code(request, _call(db, rt), email, code, "把这个邮箱绑到你的订单上（以后凭订单号和邮箱就能查）")
    db.commit()
    return SentOut(challenge=_challenge(request, "bind", email, c.id, code), masked=_mask(email),
                   message=f"验证码发到 {_mask(email)} 了，10 分钟内有效")


@router.post("/bind/verify", response_model=OkOut, dependencies=[Depends(access.by_token)])
def bind_verify(body: BindVerifyIn, request: Request, db: Session = Depends(get_db)) -> OkOut:
    _on()
    email = _email(body.email)
    c = _owner_session(db, body.chat_key, body.delivery_token)
    _check_code(request, body.challenge, "bind", email, c.id, body.code)
    p = memory.ensure_person(db, c, by="entry.account")
    if db.scalar(select(Contact.id).where(Contact.person_id == p.id, Contact.email == email)) is None:
        db.add(Contact(person_id=p.id, email=email, verified_at=utcnow(), created_at=utcnow()))
    record_event(db, "entry.email_bound", f"person:{p.id}", {"email": _mask(email), "customer": c.id})
    db.commit()
    return OkOut(masked=_mask(email))


@router.post("/login/start", response_model=SentOut, dependencies=[Depends(access.public)])
def login_start(body: LoginStartIn, request: Request, rt: ChannelsRuntime = Depends(channels_dep),
                db: Session = Depends(get_db)) -> SentOut:
    _on()
    email = _email(body.email)
    o = _order_by_no(db, body.order_no)
    owner = db.get(Customer, o.customer_id) if o is not None and o.customer_id else None
    ref = o.id if o is not None else 0
    code = _new_code()
    if owner is not None and email in _emails_of(db, owner.person_id):
        _send_code(request, _call(db, rt), email, code, f"查看订单 {o.id:05d} 和你的其他订单")
        record_event(db, "entry.account_code_sent", f"order:{o.id}", {"email": _mask(email)})
    else:
        import secrets

        code = secrets.token_hex(8)  # 对不上：不发信，挑战照给（谁也猜不出这个码），不让人试出谁绑了什么邮箱
        record_event(db, "entry.account_code_skipped", "", {"order_no": body.order_no[:12], "email": _mask(email)})
    db.commit()
    return SentOut(challenge=_challenge(request, "login", email, ref, code), masked=_mask(email),
                   message="订单号和邮箱对得上的话，验证码已经发到邮箱了，10 分钟内有效")


@router.post("/login/verify", response_model=TokenOut, dependencies=[Depends(access.public)])
def login_verify(body: LoginVerifyIn, request: Request, response: Response, db: Session = Depends(get_db)) -> TokenOut:
    """订单号 + 邮箱验证码对了：登录成这单的主人（同一个会话 cookie）。"""
    _on()
    email = _email(body.email)
    o = _order_by_no(db, body.order_no)
    _check_code(request, body.challenge, "login", email, o.id if o is not None else 0, body.code)
    owner = db.get(Customer, o.customer_id) if o is not None and o.customer_id else None
    if owner is None:
        raise HTTPException(400, detail="验证码不对")
    p = memory.ensure_person(db, owner, by="entry.account")
    record_event(db, "entry.account_login", f"order:{o.id}", {"email": _mask(email), "person": p.id})
    db.commit()
    access.issue_session(request, response, person_id=p.id, epoch=p.session_epoch or 0, method="email")
    return TokenOut(masked=_mask(email))


def session_ids_of(db: Session, me: access.CurrentCustomer | None) -> list[int]:
    """当前客户所有门的 id（兑换页判断「这码是不是你的」用）。"""
    return [d.id for d in memory.doors(db, me.person_id)] if me is not None else []

