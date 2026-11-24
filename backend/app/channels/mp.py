"""服务号（认证服务号）接口：access_token 集中缓存、带参二维码、消息推送里的扫码 / 取消关注事件（12 号设计第六、九节）。

- access_token：稳定版接口 POST /cgi-bin/stable_token 普通模式（「access_token 有效期内重复调用该接口不会更新 access_token」，
  「和 getAccessToken 互相隔离，且比其更加稳定」）。全站一份存在 channels_mp_tokens；还剩 5 分钟以上直接用，不够再拿。
  普通模式下几个进程同时去拿拿到的是同一个，所以不用加锁；联网时不拿着库的写锁（先读、再联网、再另开会话写）。
  要服务器 IP 在开发者平台的 IP 白名单里（不在回 40164）。
- 二维码：POST /cgi-bin/qrcode/create，QR_STR_SCENE（临时字符串），scene_str 1–64 字符；换图 showqrcode?ticket=（urlencode）。
- 推送：未关注扫码 → subscribe（EventKey 带 qrscene_ 前缀）；已关注 → SCAN。只认我们发的 L 开头场景值；取消关注删 openid。
测试里换成假的：app.state.mp_transport（httpx.MockTransport）。日志、事件不带 openid、access_token、AppSecret。
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from urllib.parse import quote

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.channels import login
from app.channels.models import MpToken, QrLogin
from app.core.db import Database, utcnow
from app.core.events import record_event

QR_TTL = 300  # 扫码登录票 5 分钟
SCENE_PREFIX = "L"
TOKEN_MARGIN = 300  # 还剩 5 分钟就换
_INVALID_TOKEN = (40001, 42001, 40014)
SCAN_OK_TEXT = "已在电脑上登录 PsyEngine（心理学汇报 PPT 定制）。不是你本人在操作的话，回到电脑网页点「退出」。"
SCAN_EXPIRED_TEXT = "这个登录二维码过期了：回到电脑上点「换一张」，再扫一次。"


class MpError(Exception):
    def __init__(self, errcode: int, detail: str) -> None:
        super().__init__(detail)
        self.errcode = errcode
        self.detail = detail


def _client(transport: Any, base: str) -> httpx.Client:
    return httpx.Client(base_url=base, timeout=8.0, transport=transport)


def _fetch_token(appid: str, secret: str, base: str, transport: Any) -> tuple[str, int]:
    try:
        with _client(transport, base) as c:
            r = c.post("/cgi-bin/stable_token", json={"grant_type": "client_credential", "appid": appid, "secret": secret,
                                                     "force_refresh": False})
        data = r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise MpError(-1, f"连不上服务号接口（{type(e).__name__}）") from None
    if data.get("errcode"):
        raise MpError(int(data["errcode"]), f"服务号接口回错误码 {data['errcode']}")
    token, exp = str(data.get("access_token") or ""), int(data.get("expires_in") or 0)
    if not token or exp <= 0:
        raise MpError(-2, "服务号接口没给 access_token")
    return token, exp


def access_token(database: Database, appid: str, secret: str, base: str, transport: Any = None, *, renew: bool = False) -> str:
    """全站一份的 access_token（库里缓存）。renew=True：库里那个被微信说失效了，丢掉重拿（普通模式，不用强制刷新）。"""
    now = utcnow()
    if not renew:
        with database.session(write=False) as db:
            row = db.get(MpToken, appid)
            if row is not None and row.token and row.expires_at - timedelta(seconds=TOKEN_MARGIN) > now:
                return row.token
    token, exp = _fetch_token(appid, secret, base, transport)
    with database.session() as db:
        row = db.get(MpToken, appid)
        if row is None:
            row = MpToken(appid=appid)
            db.add(row)
        row.token, row.expires_at, row.updated_at = token, now + timedelta(seconds=exp), now
    return token


def create_qr(database: Database, appid: str, secret: str, base: str, scene: str, transport: Any = None) -> str:
    """建一张临时字符串场景值二维码，返回 ticket（凭证失效回 40001 / 42001 时重拿一次 access_token 再试）。"""
    body = {"expire_seconds": QR_TTL, "action_name": "QR_STR_SCENE", "action_info": {"scene": {"scene_str": scene}}}
    for attempt in (0, 1):
        token = access_token(database, appid, secret, base, transport, renew=attempt == 1)
        try:
            with _client(transport, base) as c:
                r = c.post("/cgi-bin/qrcode/create", params={"access_token": token}, json=body)
            data = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise MpError(-1, f"连不上服务号接口（{type(e).__name__}）") from None
        code = int(data.get("errcode") or 0)
        if code in _INVALID_TOKEN and attempt == 0:
            continue
        if code:
            raise MpError(code, f"建二维码失败，错误码 {code}")
        ticket = str(data.get("ticket") or "")
        if not ticket:
            raise MpError(-2, "建二维码没给 ticket")
        return ticket
    raise MpError(-3, "access_token 一直失效")


def qr_image_url(ticket: str) -> str:
    """官方：showqrcode?ticket=TICKET，「TICKET记得进行UrlEncode」，「本接口无须登录态即可调用」。"""
    return "https://mp.weixin.qq.com/cgi-bin/showqrcode?ticket=" + quote(ticket, safe="")


# ---------------------------------------------------------------- 推送里的事件

def scanned(db: Session, scene: str, wx_user: str) -> str | None:
    """扫码事件：按场景值找到票，openid 找人（L1），票记「已扫」。返回给客人的被动回复（None = 不是我们的码，回 success）。
    同一事件微信可能重推三次：票已经扫过就只回同一句，不再处理。"""
    row = db.scalar(select(QrLogin).where(QrLogin.scene == scene))
    if row is None:
        return None
    if row.status != "pending":
        return SCAN_OK_TEXT
    if row.expires_at <= utcnow():
        return SCAN_EXPIRED_TEXT
    p = login.login_as(db, "wx", wx_user, method="qr")
    row.status, row.person_id, row.scanned_at = "scanned", p.id, utcnow()
    record_event(db, "customer.qr_scanned", f"person:{p.id}", {"ticket_id": row.id})
    return SCAN_OK_TEXT


def handle(db: Session, msg: Any) -> str | None:
    """推送来的一条（wechatpy.parse_message 的结果）。只处理扫码登录和取消关注，别的返回 None（回 success）。"""
    if getattr(msg, "type", "") != "event":
        return None
    ev = getattr(msg, "event", "")
    if ev in ("subscribe_scan", "scan"):
        scene = str(getattr(msg, "scene_id", "") or "").removeprefix("qrscene_")
        if scene.startswith(SCENE_PREFIX) and 2 <= len(scene) <= 64:
            return scanned(db, scene, str(msg.source))
        return None
    if ev == "unsubscribe":
        login.forget_wx(db, str(msg.source), by="mp.unsubscribe")
    return None


def prune(db: Session) -> int:
    from sqlalchemy import delete

    cut = utcnow() - timedelta(days=1)
    return db.execute(delete(QrLogin).where(QrLogin.created_at < cut)).rowcount or 0
