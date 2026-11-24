"""登录的接口（/api/channels/login/*、服务号推送 /api/channels/mp/callback；12 号设计第六、九节）。

- 微信里静默登录：/login/wx → 服务号网页授权（snsapi_base）→ /login/wx/callback 核 state、code 换 openid、发会话 cookie、回 next。
- 电脑扫码：POST /login/qr 建一张服务号带参二维码（临时、字符串场景值、5 分钟）；页面每 2 秒问 GET /login/qr/{场景值}
  （要带发起时种的浏览器 cookie）；扫码事件由推送回调记到票上，下一次轮询给这个浏览器发会话 cookie，票作废。
- 手机号：POST /login/sms/start 发码、/login/sms/verify 核码 → 登录（purpose=login）或绑到当前账号（purpose=bind，要已登录）。
- 推送回调：GET 核 signature 原样回 echostr；POST 核 signature，安全模式再核 msg_signature、解密（wechatpy 会核 appid），
  只处理扫码和取消关注，别的回 success。
哪种设备给哪几种登录：methods_for（微信里：微信 + 手机号；电脑：扫码 + 手机号；手机浏览器：手机号）。
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.channels import limits, login, mp, sms
from app.channels.entry_config import load_entry_config
from app.channels.models import QrLogin
from app.channels.runtime import ChannelsRuntime, channels_dep
from app.core import access, wxoauth
from app.core.db import get_db, get_write_db, utcnow
from app.core.events import record_event
from app.core.net import client_ip, ua_kind

router = APIRouter(tags=["channels"])

WX_STATE_COOKIE = "psy_wxl"
WX_COOKIE_PATH = "/api/channels/login/wx"
QR_COOKIE = "psy_qrl"
QR_COOKIE_PATH = "/api/channels/login/qr"
FAKE_WX_COOKIE = "psy_fakewx"  # 只在假微信（本机走查）：同一个浏览器每次登进同一个假微信
QR_IP_HOURLY = 30


# ---------------------------------------------------------------- 开关和登录方式

def fake_wx(rt: ChannelsRuntime) -> bool:
    return rt.settings.WECHAT_MP_FAKE and rt.core.APP_ENV != "prod"


def wx_on(rt: ChannelsRuntime) -> bool:
    s = rt.settings
    return s.WECHAT_LOGIN_ENABLED and (fake_wx(rt) or bool(s.WECHATPAY_APPID and s.mp_appsecret()))


def qr_on(rt: ChannelsRuntime) -> bool:
    return wx_on(rt) and (fake_wx(rt) or bool(rt.settings.mp_token()))


def methods_for(request: Request, rt: ChannelsRuntime) -> list[str]:
    """这台设备能用的登录方式，按推荐顺序。"""
    kind = ua_kind(request.headers.get("user-agent", ""))
    sms_on = sms.enabled(request)
    out: list[str] = []
    if kind == "wechat" and wx_on(rt):
        out.append("wx")
    if kind == "pc" and qr_on(rt):
        out.append("qr")
    if sms_on:
        out.append("sms")
    return out


def login_required(request: Request, rt: ChannelsRuntime, db: Session) -> bool:
    """认领前要不要先登录：后台开关开着（默认开）+ 这台设备至少有一种登录方式。一种都没有就照旧不登录认领（退路）。"""
    return load_entry_config(db).login_required and bool(methods_for(request, rt))


def safe_next(raw: str | None, default: str = "/me") -> str:
    """登录完回哪：只认站内路径（/ 开头、不是 //、没有反斜杠和换行）。"""
    s = (raw or "").strip()
    if not s.startswith("/") or s.startswith("//") or "\\" in s or any(ch in s for ch in "\r\n\t") or len(s) > 300:
        return default
    return s


def _with(path: str, query: str) -> str:
    return f"{path}{'&' if '?' in path else '?'}{query}"


def _cookie(request: Request, resp: Response, name: str, value: str, path: str, max_age: int) -> None:
    resp.set_cookie(name, value, max_age=max_age, path=path, httponly=True, samesite="lax", secure=access.secure_cookie(request))


# ---------------------------------------------------------------- 微信里静默登录

@router.get("/login/wx", include_in_schema=False, dependencies=[Depends(access.public)])
def wx_login(request: Request, next: str = "/me", rt: ChannelsRuntime = Depends(channels_dep)) -> RedirectResponse:
    nxt = safe_next(next)
    if not wx_on(rt):
        return RedirectResponse(_with(nxt, "login=wx_off"), status_code=303)
    if ua_kind(request.headers.get("user-agent", "")) != "wechat" and not fake_wx(rt):
        return RedirectResponse(_with(nxt, "login=wx_notwechat"), status_code=303)
    state = wxoauth.new_state()
    callback = f"/api/channels/login/wx/callback?next={quote(nxt, safe='')}"
    fake_id = ""
    if fake_wx(rt):
        fake_id = request.cookies.get(FAKE_WX_COOKIE) or secrets.token_hex(8)
        target = f"{callback}&code=FAKE{fake_id}&state={state}"
    else:
        target = wxoauth.authorize_url(rt.settings.WECHATPAY_APPID, rt.core.PUBLIC_BASE_URL.rstrip("/") + callback, state)
    resp = RedirectResponse(target, status_code=302)
    _cookie(request, resp, WX_STATE_COOKIE, state, WX_COOKIE_PATH, wxoauth.STATE_TTL_SEC)
    if fake_id:
        _cookie(request, resp, FAKE_WX_COOKIE, fake_id, "/api/channels/login", 86400 * 30)
    return resp


@router.get("/login/wx/callback", include_in_schema=False, dependencies=[Depends(access.public)])
def wx_callback(request: Request, next: str = "/me", code: str = "", state: str = "",
                rt: ChannelsRuntime = Depends(channels_dep), db: Session = Depends(get_write_db)) -> RedirectResponse:
    """授权回来：先核 state（和 cookie 里的一样才认），再用 code 换 openid（只换一次），找人或建人，发会话 cookie。"""
    nxt = safe_next(next)

    def back(why: str) -> RedirectResponse:
        record_event(db, "customer.login_failed", "", {"method": "wx", "why": why})
        db.commit()
        r = RedirectResponse(_with(nxt, f"login=wx_{why}"), status_code=303)
        r.delete_cookie(WX_STATE_COOKIE, path=WX_COOKIE_PATH)
        return r

    if not wx_on(rt):
        return RedirectResponse(_with(nxt, "login=wx_off"), status_code=303)
    if not wxoauth.state_ok(request.cookies.get(WX_STATE_COOKIE), state):
        return back("state")
    if not code:
        return back("denied")
    try:
        if fake_wx(rt):
            wx_user = wxoauth.fake_openid(code)
        else:
            wx_user = wxoauth.fetch_openid(rt.settings.WECHATPAY_APPID, rt.settings.mp_appsecret(), code,
                                           adapter=getattr(request.app.state, "wechat_oauth_adapter", None))
    except wxoauth.OAuthFailed as e:
        return back("snapshot" if e.reason == "snapshot" else "fail")
    p = login.login_as(db, "wx", wx_user, method="wx")
    db.commit()
    resp = RedirectResponse(nxt, status_code=303)
    resp.delete_cookie(WX_STATE_COOKIE, path=WX_COOKIE_PATH)
    access.issue_session(request, resp, person_id=p.id, epoch=p.session_epoch, method="wx")
    return resp


# ---------------------------------------------------------------- 电脑扫码

class QrOut(BaseModel):
    scene: str
    image: str
    expires_in: int
    fake: bool = False


class QrState(BaseModel):
    status: Literal["pending", "ok", "expired", "used"]


def _browser_mac(request: Request, scene: str, nonce: str) -> str:
    return hmac.new(access._secret(request).encode(), f"qr|{scene}|{nonce}".encode(), hashlib.sha256).hexdigest()


@router.post("/login/qr", response_model=QrOut, dependencies=[Depends(access.public)])
def qr_start(request: Request, response: Response, rt: ChannelsRuntime = Depends(channels_dep),
             db: Session = Depends(get_db)) -> QrOut:
    if not qr_on(rt):
        raise HTTPException(404, detail="Not Found")
    ip = client_ip(request)
    if not limits.limiter(request.app).hit("login.qr_ip", ip, limit=QR_IP_HOURLY, window=3600):
        raise HTTPException(429, detail="二维码换得太频繁了，过一会儿再试，或者用手机号登录")
    scene = mp.SCENE_PREFIX + secrets.token_hex(12)
    nonce = secrets.token_urlsafe(24)
    if fake_wx(rt):
        ticket, image = f"FAKE{scene}", f"/api/channels/login/qr/{scene}/fake.svg"
    else:
        try:  # 联网在动库之前（不拿着写锁等微信）
            ticket = mp.create_qr(rt.intake.database, rt.settings.WECHATPAY_APPID, rt.settings.mp_appsecret(),
                                  rt.settings.WECHAT_MP_API_BASE, scene, getattr(request.app.state, "mp_transport", None))
        except mp.MpError as e:
            record_event(db, "customer.qr_failed", "", {"errcode": e.errcode, "detail": e.detail})
            db.commit()
            if e.errcode == 40164:
                rt.intake.ctx.notifier.send("电脑扫码登录建不了二维码：服务器 IP 不在服务号的 IP 白名单里（40164），去微信开发者平台加上", level="urgent", kind="系统异常", who="wechat-mp-qr")
            raise HTTPException(503, detail="二维码暂时出不来，先用手机号登录，或者过一会儿再试") from None
        image = mp.qr_image_url(ticket)
    now = utcnow()
    db.add(QrLogin(scene=scene, browser_mac=_browser_mac(request, scene, nonce), ticket=ticket[:255], status="pending",
                   ip=ip[:64], created_at=now, expires_at=now + timedelta(seconds=mp.QR_TTL)))
    db.commit()
    _cookie(request, response, QR_COOKIE, nonce, QR_COOKIE_PATH, mp.QR_TTL + 300)
    return QrOut(scene=scene, image=image, expires_in=mp.QR_TTL, fake=fake_wx(rt))


def _qr_row(request: Request, db: Session, scene: str) -> QrLogin:
    row = db.scalar(select(QrLogin).where(QrLogin.scene == scene)) if 2 <= len(scene) <= 64 else None
    nonce = request.cookies.get(QR_COOKIE) or ""
    if row is None or not nonce or not hmac.compare_digest(row.browser_mac, _browser_mac(request, scene, nonce)):
        raise HTTPException(404, detail="没有这张二维码")
    return row


@router.get("/login/qr/{scene}", response_model=QrState, dependencies=[Depends(access.public)])
def qr_poll(scene: str, request: Request, response: Response, rt: ChannelsRuntime = Depends(channels_dep),
            db: Session = Depends(get_write_db)) -> QrState:
    """轮询：扫过了就给这个浏览器发会话 cookie（票只用一次）。只有发起的那个浏览器（带着 psy_qrl cookie）问得到。"""
    if not qr_on(rt):
        raise HTTPException(404, detail="Not Found")
    row = _qr_row(request, db, scene)
    if row.status == "done":
        return QrState(status="used")
    if row.status == "scanned" and row.person_id:
        p = login._canonical(db, row.person_id)
        if p is None:
            raise HTTPException(404, detail="没有这张二维码")
        row.status, row.done_at = "done", utcnow()
        db.commit()
        access.issue_session(request, response, person_id=p.id, epoch=p.session_epoch, method="qr")
        response.delete_cookie(QR_COOKIE, path=QR_COOKIE_PATH)
        return QrState(status="ok")
    if row.expires_at <= utcnow():
        return QrState(status="expired")
    return QrState(status="pending")


@router.get("/login/qr/{scene}/fake.svg", include_in_schema=False, dependencies=[Depends(access.public)])
def qr_fake_image(scene: str, rt: ChannelsRuntime = Depends(channels_dep)) -> Response:
    """本机走查的假二维码（只在假微信时有）。"""
    if not fake_wx(rt):
        raise HTTPException(404, detail="Not Found")
    cells = "".join(f'<rect x="{(i * 7) % 21 * 8}" y="{(i * 11) % 21 * 8}" width="8" height="8"/>'
                    for i, ch in enumerate(hashlib.sha256(scene.encode()).hexdigest()) if int(ch, 16) % 2)
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 168 168" width="168" height="168">'
           f'<rect width="168" height="168" fill="white"/><g fill="black">{cells}</g>'
           '<text x="84" y="92" font-size="14" text-anchor="middle" fill="black">假二维码</text></svg>')
    return Response(svg, media_type="image/svg+xml")


@router.post("/login/qr/{scene}/fake-scan", include_in_schema=False, dependencies=[Depends(access.public)])
def qr_fake_scan(scene: str, request: Request, rt: ChannelsRuntime = Depends(channels_dep),
                 db: Session = Depends(get_db)) -> dict[str, str]:
    """本机走查：假装手机微信扫了这张码（只在假微信时有；APP_ENV=prod 时 fake_wx 一律为假）。"""
    if not fake_wx(rt):
        raise HTTPException(404, detail="Not Found")
    fake_id = request.cookies.get(FAKE_WX_COOKIE) or "desk"
    text = mp.scanned(db, scene, wxoauth.fake_openid(f"FAKE{fake_id}"))
    db.commit()
    return {"reply": text or ""}


# ---------------------------------------------------------------- 手机号

class SmsStartIn(BaseModel):
    phone: str = Field(min_length=6, max_length=20)
    purpose: Literal["login", "bind"] = "login"


class SmsVerifyIn(SmsStartIn):
    code: str = Field(min_length=4, max_length=8)


class SmsSentOut(BaseModel):
    masked: str
    message: str
    ttl_min: int


class LoginOut(BaseModel):
    ok: bool = True
    masked: str = ""
    merged: bool = False
    message: str = ""


def _phone(raw: str) -> str:
    p = login.normalize_phone(raw)
    if p is None:
        raise HTTPException(400, detail="手机号不对：只支持中国大陆 11 位手机号")
    return p


@router.post("/login/sms/start", response_model=SmsSentOut, dependencies=[Depends(access.public)])
def sms_start(body: SmsStartIn, request: Request, rt: ChannelsRuntime = Depends(channels_dep),
              db: Session = Depends(get_db)) -> SmsSentOut:
    sms.require_on(request)
    phone = _phone(body.phone)
    if body.purpose == "bind":
        access.require_customer(request, db)
    sms.send_code(request, db, phone, body.purpose, client_ip(request), alert=rt.intake.ctx.notifier)
    db.commit()
    ttl = rt.settings.SMS_CODE_TTL_MIN
    return SmsSentOut(masked=login.mask_phone(phone), ttl_min=ttl, message=f"验证码发到 {login.mask_phone(phone)} 了，{ttl} 分钟内有效")


@router.post("/login/sms/verify", response_model=LoginOut, dependencies=[Depends(access.public)])
def sms_verify(body: SmsVerifyIn, request: Request, response: Response, db: Session = Depends(get_db)) -> LoginOut:
    sms.require_on(request)
    phone = _phone(body.phone)
    me = access.require_customer(request, db) if body.purpose == "bind" else None
    sms.check_code(request, db, phone, body.purpose, body.code)
    if me is not None:
        p, merged = login.bind_phone(db, login.person(db, me), phone, by="customer")
        db.commit()
        if p.id != me.person_id:  # 合人后保留的是较早的那个人：cookie 换成它（旧的也还认，顺着并走的痕迹找得到）
            access.issue_session(request, response, person_id=p.id, epoch=p.session_epoch, method=me.method)
        msg = "绑好了。这个手机号之前登录过，两边的订单已经合在一起。" if merged else "绑好了，以后也可以用手机号登录。"
        return LoginOut(masked=login.mask_phone(phone), merged=merged, message=msg)
    p = login.login_as(db, "phone", phone, method="sms")
    db.commit()
    access.issue_session(request, response, person_id=p.id, epoch=p.session_epoch, method="sms")
    return LoginOut(masked=login.mask_phone(phone), message="登录了")


# ---------------------------------------------------------------- 服务号消息推送

def _mp_token(rt: ChannelsRuntime) -> str:
    """推送回调认的 Token（没配 = 回调整个 404）。微信登录总开关关了也照收：取消关注删 openid 不能停。"""
    return rt.settings.mp_token()


@router.get("/mp/callback", include_in_schema=False, dependencies=[Depends(access.webhook)])
def mp_verify(signature: str = "", timestamp: str = "", nonce: str = "", echostr: str = "",
              rt: ChannelsRuntime = Depends(channels_dep)) -> PlainTextResponse:
    """开发者平台保存「消息与事件推送」时来验：token、timestamp、nonce 排序拼接 sha1 和 signature 对上，原样回 echostr。"""
    from wechatpy.exceptions import InvalidSignatureException
    from wechatpy.utils import check_signature

    token = _mp_token(rt)
    if not token:
        raise HTTPException(404, detail="Not Found")
    try:
        check_signature(token, signature, timestamp, nonce)
    except InvalidSignatureException:
        raise HTTPException(403, detail="签名不对") from None
    return PlainTextResponse(echostr)


@router.post("/mp/callback", include_in_schema=False, dependencies=[Depends(access.webhook)])
async def mp_push(request: Request, signature: str = "", timestamp: str = "", nonce: str = "", encrypt_type: str = "",
                  msg_signature: str = "", rt: ChannelsRuntime = Depends(channels_dep)) -> Response:
    body = await request.body()
    return await run_in_threadpool(_mp_push, rt, body, signature, timestamp, nonce, encrypt_type, msg_signature)


def _mp_push(rt: ChannelsRuntime, body: bytes, signature: str, timestamp: str, nonce: str, encrypt_type: str,
             msg_signature: str) -> Response:
    from wechatpy import create_reply, parse_message
    from wechatpy.crypto import WeChatCrypto
    from wechatpy.exceptions import InvalidAppIdException, InvalidSignatureException
    from wechatpy.utils import check_signature

    token = _mp_token(rt)
    if not token or len(body) > 64 * 1024:
        raise HTTPException(404, detail="Not Found")
    try:
        check_signature(token, signature, timestamp, nonce)
    except InvalidSignatureException:
        raise HTTPException(403, detail="签名不对") from None
    crypto = None
    xml: bytes | str = body
    if encrypt_type == "aes":
        aes = rt.settings.mp_aes_key()
        if not aes:
            raise HTTPException(403, detail="没配 EncodingAESKey，收不了安全模式的推送")
        crypto = WeChatCrypto(token, aes, rt.settings.WECHATPAY_APPID)
        try:
            xml = crypto.decrypt_message(body, msg_signature, timestamp, nonce)
        except (InvalidSignatureException, InvalidAppIdException):
            raise HTTPException(403, detail="签名或 AppID 不对") from None
    try:
        msg = parse_message(xml)
    except Exception:  # noqa: BLE001  看不懂的包：回 success，不让微信重推
        return PlainTextResponse("success")
    with rt.intake.database.session() as db:
        text = mp.handle(db, msg)
    if not text:
        return PlainTextResponse("success")
    reply = create_reply(text, msg).render()
    if crypto is not None:
        reply = crypto.encrypt_message(reply, nonce, timestamp)
    return Response(reply, media_type="application/xml")


def prune_tick(rt: ChannelsRuntime) -> str:
    """每小时删一天前的验证码和扫码票。"""
    with rt.intake.database.session() as db:
        n = sms.prune(db) + mp.prune(db)
    return f"删了 {n} 条"
