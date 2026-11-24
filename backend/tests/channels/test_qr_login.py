"""电脑扫码登录和服务号消息推送（12 号设计第六、九节）：假服务号接口（httpx.MockTransport），推送用 wechatpy 按官方算法加密、签名。"""

from __future__ import annotations

import hashlib
import re
import time
from datetime import timedelta

from sqlalchemy import select

from app.channels.models import Login, MpToken, QrLogin
from app.core.db import utcnow
from app.intake.runtime import get_runtime
from tests.channels.login_helpers import APPID, MP_AES, MP_TOKEN, PC_UA, FakeMp, client, login_app

GH = "gh_0123456789ab"


def _sig(timestamp: str, nonce: str, token: str = MP_TOKEN) -> str:
    return hashlib.sha1("".join(sorted([token, timestamp, nonce])).encode()).hexdigest()


def _event_xml(user: str, event: str, key: str = "") -> str:
    ek = f"<EventKey><![CDATA[{key}]]></EventKey><Ticket><![CDATA[gQ/x]]></Ticket>" if key else ""
    return (f"<xml><ToUserName><![CDATA[{GH}]]></ToUserName><FromUserName><![CDATA[{user}]]></FromUserName>"
            f"<CreateTime>{int(time.time())}</CreateTime><MsgType><![CDATA[event]]></MsgType>"
            f"<Event><![CDATA[{event}]]></Event>{ek}</xml>")


def _push(c, xml: str, *, aes: bool = True, bad_sig: bool = False):
    from wechatpy.crypto import WeChatCrypto

    ts, nonce = str(int(time.time())), "nonce123"
    params = {"signature": "0" * 40 if bad_sig else _sig(ts, nonce), "timestamp": ts, "nonce": nonce, "openid": "x"}
    body = xml
    if aes:
        enc = WeChatCrypto(MP_TOKEN, MP_AES, APPID).encrypt_message(xml, nonce, ts)
        encrypt = re.search(r"<Encrypt><!\[CDATA\[(.*?)\]\]></Encrypt>", enc).group(1)
        params.update(encrypt_type="aes", msg_signature=re.search(r"<MsgSignature><!\[CDATA\[(.*?)\]\]>", enc).group(1))
        body = f"<xml><ToUserName><![CDATA[{GH}]]></ToUserName><Encrypt><![CDATA[{encrypt}]]></Encrypt></xml>"
    return c.post("/api/channels/mp/callback", params=params, content=body.encode(), headers={"Content-Type": "text/xml"})


def _decrypt_reply(text: str, nonce: str = "nonce123") -> str:
    from wechatpy.crypto import WeChatCrypto

    sig = re.search(r"<MsgSignature><!\[CDATA\[(.*?)\]\]>", text).group(1)
    ts = re.search(r"<TimeStamp>(\d+)</TimeStamp>", text).group(1)
    return WeChatCrypto(MP_TOKEN, MP_AES, APPID).decrypt_message(text, sig, ts, nonce)


def test_mp_callback_signature(settings, notifier, tmp_path):
    """GET 验 URL：签名对了原样回 echostr，不对 403；POST 签名不对 403；安全模式核 msg_signature；明文模式也认；
    别的消息回 success；没配 Token 整个 404。"""
    app = login_app(settings, notifier, tmp_path)
    with client(app, PC_UA) as c:
        ts, nonce = "1700000000", "abc"
        ok = c.get("/api/channels/mp/callback", params={"signature": _sig(ts, nonce), "timestamp": ts, "nonce": nonce, "echostr": "E123"})
        assert ok.status_code == 200 and ok.text == "E123"
        assert c.get("/api/channels/mp/callback", params={"signature": "0" * 40, "timestamp": ts, "nonce": nonce,
                                                          "echostr": "E"}).status_code == 403
        assert _push(c, _event_xml("oX", "subscribe"), bad_sig=True).status_code == 403
        r = _push(c, "<xml><ToUserName><![CDATA[gh]]></ToUserName><FromUserName><![CDATA[oX]]></FromUserName>"
                     "<CreateTime>1</CreateTime><MsgType><![CDATA[text]]></MsgType><Content><![CDATA[你好]]></Content>"
                     "<MsgId>1</MsgId></xml>")
        assert r.status_code == 200 and r.text == "success"
        assert _push(c, _event_xml("oX", "subscribe"), aes=False).text == "success"
        # 安全模式下 msg_signature 不对
        from wechatpy.crypto import WeChatCrypto

        tsx, nx = str(int(time.time())), "n2"
        enc = WeChatCrypto(MP_TOKEN, MP_AES, APPID).encrypt_message(_event_xml("oX", "subscribe"), nx, tsx)
        encrypt = re.search(r"<Encrypt><!\[CDATA\[(.*?)\]\]></Encrypt>", enc).group(1)
        bad = c.post("/api/channels/mp/callback", params={"signature": _sig(tsx, nx), "timestamp": tsx, "nonce": nx,
                                                          "encrypt_type": "aes", "msg_signature": "f" * 40},
                     content=f"<xml><Encrypt><![CDATA[{encrypt}]]></Encrypt></xml>".encode())
        assert bad.status_code == 403
    off = login_app(settings, notifier, tmp_path / "off", qr=False)
    with client(off, PC_UA) as c:
        assert c.get("/api/channels/mp/callback", params={"echostr": "x"}).status_code == 404
        assert c.post("/api/channels/login/qr").status_code == 404


def test_qr_login_scan_flow(settings, notifier, tmp_path):
    """建码（access_token 只拿一次、缓存在库里）→ 轮询 pending → 推送「未关注扫码关注」（qrscene_ 前缀）→ 轮询 ok、发会话、票只用一次；
    已关注的 SCAN 也认；别的浏览器拿到场景值问不到；过期给 expired；凭证失效重拿一次。"""
    mp = FakeMp()
    app = login_app(settings, notifier, tmp_path, mp=mp)
    with client(app, PC_UA) as a, client(app, PC_UA) as other:
        q = a.post("/api/channels/login/qr").json()
        assert q["image"].startswith("https://mp.weixin.qq.com/cgi-bin/showqrcode?ticket=gQ%2F") and "%2B%3D" in q["image"]
        scene = q["scene"]
        assert scene.startswith("L") and len(scene) <= 64 and q["expires_in"] == 300
        assert a.get(f"/api/channels/login/qr/{scene}").json() == {"status": "pending"}
        assert other.get(f"/api/channels/login/qr/{scene}").status_code == 404  # 没有发起时种的 cookie
        r = _push(a, _event_xml("oSCANNER0000000000000001", "subscribe", f"qrscene_{scene}"))
        assert r.status_code == 200 and "已在电脑上登录" in _decrypt_reply(r.text)
        assert "已在电脑上登录" in _decrypt_reply(_push(a, _event_xml("oSCANNER0000000000000001", "subscribe", f"qrscene_{scene}")).text)
        done = a.get(f"/api/channels/login/qr/{scene}")
        assert done.json() == {"status": "ok"} and "psy_sess" in done.cookies
        assert a.get("/api/channels/account/session").json()["method"] == "qr"
        assert a.get(f"/api/channels/login/qr/{scene}").status_code == 404 or \
            a.get(f"/api/channels/login/qr/{scene}").json()["status"] == "used"
        # 已关注的人扫第二张：SCAN，EventKey 就是场景值
        q2 = other.post("/api/channels/login/qr").json()
        _push(other, _event_xml("oSCANNER0000000000000001", "SCAN", q2["scene"]), aes=False)
        assert other.get(f"/api/channels/login/qr/{q2['scene']}").json()["status"] == "ok"
        # 两张码都是同一个微信 → 同一个人
        with get_runtime(app).database.session(write=False) as db:
            assert len(list(db.scalars(select(Login)))) == 1
        # 过期
        q3 = a.post("/api/channels/login/qr").json()
        with get_runtime(app).database.session() as db:
            row = db.scalar(select(QrLogin).where(QrLogin.scene == q3["scene"]))
            row.expires_at = utcnow() - timedelta(seconds=1)
        assert a.get(f"/api/channels/login/qr/{q3['scene']}").json()["status"] == "expired"
        assert "过期" in _decrypt_reply(_push(a, _event_xml("oSCANNER0000000000000002", "subscribe", f"qrscene_{q3['scene']}")).text)
    assert sum(1 for path, _ in mp.calls if path == "/cgi-bin/stable_token") == 1  # 缓存住了
    with get_runtime(app).database.session(write=False) as db:
        assert db.get(MpToken, APPID).token == "TOKEN1"


def test_access_token_renewed_once_on_invalid(settings, notifier, tmp_path):
    mp = FakeMp(token_errors=1)
    app = login_app(settings, notifier, tmp_path, mp=mp)
    with client(app, PC_UA) as c:
        assert c.post("/api/channels/login/qr").status_code == 200
    assert [p for p, _ in mp.calls].count("/cgi-bin/stable_token") == 2


def test_ip_not_in_whitelist_tells_owner(settings, notifier, tmp_path):
    """服务器 IP 不在服务号 IP 白名单（40164）：页面说先用手机号，负责人收到一句怎么改。"""
    app = login_app(settings, notifier, tmp_path, mp=FakeMp(token_errcode=40164))
    with client(app, PC_UA) as c:
        r = c.post("/api/channels/login/qr")
        assert r.status_code == 503 and "手机号" in r.json()["detail"]
    assert any("IP 白名单" in m for m in notifier.sent)


def test_unsubscribe_push_removes_openid(settings, notifier, tmp_path):
    app = login_app(settings, notifier, tmp_path)
    with client(app, PC_UA) as c:
        q = c.post("/api/channels/login/qr").json()
        _push(c, _event_xml("oLEAVER00000000000000001", "SCAN", q["scene"]))
        c.get(f"/api/channels/login/qr/{q['scene']}")
        assert c.get("/api/channels/account/session").json()["logged_in"]
        assert _push(c, _event_xml("oLEAVER00000000000000001", "unsubscribe")).text == "success"
        assert not c.get("/api/channels/account/session").json()["logged_in"]
    with get_runtime(app).database.session(write=False) as db:
        assert db.scalar(select(Login).where(Login.value == "oLEAVER00000000000000001")) is None
