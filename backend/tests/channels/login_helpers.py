"""登录测试共用（12 号设计）：假的服务号网页授权（requests 适配器）、假的服务号接口（httpx.MockTransport）、假短信网关、
按 UA 建 app、登录几种办法的快捷函数。全程不联网、不读真密钥、不发真短信。"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import requests
from fastapi.testclient import TestClient

from app.channels.sms import FakeSms
from tests.channels.entry_helpers import entry_app

APPID = "wxlogintest0000001"
SECRET = "login-appsecret-not-real-0123456789"
MP_TOKEN = "LoginToken0123456789abcdefABCDEF"
MP_AES = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG"  # 43 位
BASE = "https://psyppt.example.cn"
WECHAT_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
             "MicroMessenger/8.0.50(0x18003237) NetType/WIFI Language/zh_CN")
MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
             "Mobile/15E148 Safari/604.1")
PC_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15"


class FakeOAuth(requests.adapters.BaseAdapter):
    """假的 api.weixin.qq.com 网页授权：code → openid（code=Cxxx 换成 oUSERxxx）；同一个 code 第二次回 40163。"""

    def __init__(self, *, snapshot: bool = False, error: Exception | None = None) -> None:
        super().__init__()
        self.calls: list[dict[str, list[str]]] = []
        self.used: set[str] = set()
        self.snapshot, self.error = snapshot, error

    def send(self, request, **kwargs):  # noqa: ANN001, ANN201
        assert kwargs.get("timeout"), "换 openid 的请求要带超时"
        q = parse_qs(urlparse(request.url).query)
        self.calls.append(q)
        if self.error is not None:
            raise self.error
        code = q["code"][0]
        if q["secret"] != [SECRET] or q["appid"] != [APPID]:
            body: dict[str, Any] = {"errcode": 40125, "errmsg": "invalid appsecret"}
        elif code in self.used:
            body = {"errcode": 40163, "errmsg": "code been used"}
        else:
            self.used.add(code)
            body = {"access_token": "AT", "expires_in": 7200, "refresh_token": "RT", "openid": openid_for(code), "scope": "snsapi_base"}
            if self.snapshot:
                body["is_snapshotuser"] = 1
        r = requests.Response()
        r.status_code, r._content, r.url, r.request = 200, json.dumps(body).encode(), request.url, request
        r.headers["content-type"] = "application/json"
        return r

    def close(self) -> None:
        pass


def openid_for(code: str) -> str:
    """code「C1」「C1-b」换出同一个 openid（同一个微信、两次授权）；「C2」是另一个微信。"""
    return "oUSER" + code.removeprefix("C").split("-")[0].ljust(23, "0")[:23]


class FakeMp:
    """假的服务号接口：stable_token、qrcode/create。记下每次调用；token_errors 让前几次建码回凭证失效。"""

    def __init__(self, *, token_errors: int = 0, token_errcode: int = 0) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.token_errors = token_errors
        self.token_errcode = token_errcode
        self.n_token = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        self.calls.append((request.url.path, body))
        if request.url.path == "/cgi-bin/stable_token":
            if self.token_errcode:
                return httpx.Response(200, json={"errcode": self.token_errcode, "errmsg": "x"})
            assert body == {"grant_type": "client_credential", "appid": APPID, "secret": SECRET, "force_refresh": False}
            self.n_token += 1
            return httpx.Response(200, json={"access_token": f"TOKEN{self.n_token}", "expires_in": 7200})
        if request.url.path == "/cgi-bin/qrcode/create":
            if self.token_errors > 0:
                self.token_errors -= 1
                return httpx.Response(200, json={"errcode": 40001, "errmsg": "invalid credential"})
            assert body["action_name"] == "QR_STR_SCENE" and body["expire_seconds"] == 300
            scene = body["action_info"]["scene"]["scene_str"]
            assert 1 <= len(scene) <= 64
            return httpx.Response(200, json={"ticket": f"gQ/{scene}+=", "expire_seconds": 300, "url": "http://weixin.qq.com/q/x"})
        return httpx.Response(404)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


def login_app(settings, notifier, tmp_path: Path, *, wx: bool = True, qr: bool = True, sms: FakeSms | None = None,
              oauth: FakeOAuth | None = None, mp: FakeMp | None = None, mail=None, **over: Any):
    """开了微信登录（和扫码）、可选假短信的 app。"""
    settings.PUBLIC_BASE_URL = BASE
    ch: dict[str, Any] = {}
    if wx:
        ch.update(WECHATPAY_APPID=APPID, WECHAT_MP_APPSECRET=SECRET)
    if qr:
        ch.update(WECHAT_MP_TOKEN=MP_TOKEN, WECHAT_MP_AES_KEY=MP_AES)
    ch.update(over)
    app = entry_app(settings, notifier, tmp_path, mail=mail, **ch)
    app.state.wechat_oauth_adapter = oauth or FakeOAuth()
    app.state.mp_transport = (mp or FakeMp()).transport()
    app.state.sms_sender = sms  # None = 短信整块关
    return app


def client(app, ua: str = MOBILE_UA) -> TestClient:
    return TestClient(app, base_url="https://testserver", headers={"User-Agent": ua})


def wx_login(c: TestClient, code: str = "C1", next_path: str = "/me") -> Any:
    """微信里静默登录走一遍：/login/wx → 拿 state → 带 code 回调。返回回调的响应。"""
    r = c.get("/api/channels/login/wx", params={"next": next_path}, follow_redirects=False)
    assert r.status_code == 302, r.text
    loc = r.headers["location"]
    state = parse_qs(urlparse(loc.replace("#wechat_redirect", "")).query)["state"][0]
    return c.get("/api/channels/login/wx/callback", params={"next": next_path, "code": code, "state": state}, follow_redirects=False)


def sms_login(c: TestClient, sms: FakeSms, phone: str = "13800138000", purpose: str = "login") -> Any:
    _forget_60s(c, phone)
    r = c.post("/api/channels/login/sms/start", json={"phone": phone, "purpose": purpose})
    assert r.status_code == 200, r.text
    return c.post("/api/channels/login/sms/verify", json={"phone": phone, "purpose": purpose, "code": sms.last_code()})


def all_rows_text(database) -> str:
    """库里所有表所有行拼成一串（查 openid、手机号、验证码有没有落到不该落的地方）。"""
    from sqlalchemy import inspect, text

    out = []
    with database.session(write=False) as db:
        for t in inspect(db.get_bind()).get_table_names():
            for row in db.execute(text(f'SELECT * FROM "{t}"')):
                out.append(f"{t}:{row}")
    return "\n".join(out)


def wait(seconds: float) -> None:
    time.sleep(seconds)


def _forget_60s(c: TestClient, phone: str) -> None:
    """测试里同一个号连着登、绑：清掉「60 秒一条」那一道（限流本身在 test_sms 里测）。"""
    from app.channels.login import normalize_phone

    c.app.state.ratelimit.clear("sms.phone_60s", normalize_phone(phone) or phone, limit=1, window=60)
