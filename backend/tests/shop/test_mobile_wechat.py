"""手机上的微信付款（docs/任务单/11_手机微信支付_设计.md）：微信里 JSAPI（服务号网页授权拿 openid）、手机浏览器 H5、校验文件。

微信支付是 test_gateways 里的 httpx.MockTransport 假扮的（也验我们的签名），网页授权是一个假的 requests 适配器：
不联网、不读真密钥、不产生真实付款。
"""

from __future__ import annotations

import json
import logging
import re
from datetime import timedelta
from urllib.parse import parse_qs, quote, unquote, urlparse

import pytest
import requests
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text

from app.core.db import utcnow
from app.shop.models import ShopCheckout
from app.shop.paycore import wechat_sign
from app.shop.router import run_tick
from tests.conftest import TEST_PASSWORD
from tests.shop.helpers import MOBILE_UA, PC_UA, WECHAT_UA, checkout_body, make_shop_app
from tests.shop.test_gateways import APPID, wx, wx_notify  # noqa: F401  wx 是 fixture

BASE = "https://psyppt.example.cn"
SECRET = "test-appsecret-not-real-0123456789"
OPENID = "oTESTuserOpenid_0000000000001"


class FakeOAuth(requests.adapters.BaseAdapter):
    """假的 api.weixin.qq.com：sns/oauth2/access_token 按 code 回 openid；同一个 code 第二次用回 40163（跟官方一样）。"""

    def __init__(self, *, snapshot: bool = False, error: Exception | None = None) -> None:
        super().__init__()
        self.calls: list[dict[str, list[str]]] = []
        self.used: set[str] = set()
        self.snapshot = snapshot
        self.error = error

    def send(self, request, **kwargs):  # noqa: ANN001, ANN201
        assert kwargs.get("timeout"), "换 openid 的请求要带超时"
        q = parse_qs(urlparse(request.url).query)
        self.calls.append(q)
        if self.error is not None:
            raise self.error
        assert urlparse(request.url).path == "/sns/oauth2/access_token"
        assert q["grant_type"] == ["authorization_code"] and q["appid"] == [APPID]
        code = q["code"][0]
        if q["secret"] != [SECRET]:
            body = {"errcode": 40125, "errmsg": "invalid appsecret"}
        elif code in self.used:
            body = {"errcode": 40163, "errmsg": "code been used"}
        else:
            self.used.add(code)
            body = {"access_token": "AT", "expires_in": 7200, "refresh_token": "RT", "openid": OPENID, "scope": "snsapi_base"}
            if self.snapshot:
                body["is_snapshotuser"] = 1
        r = requests.Response()
        r.status_code, r._content, r.url, r.request = 200, json.dumps(body).encode(), request.url, request
        r.headers["content-type"] = "application/json"
        return r

    def close(self) -> None:
        pass


def _app(settings, notifier, tmp_path, wx, *, methods: str, oauth: FakeOAuth | None = None, secret_file: bool = True, **over):
    settings.PUBLIC_BASE_URL = BASE
    tmp_path.mkdir(parents=True, exist_ok=True)
    extra = dict(wx["over"], SHOP_METHODS=methods)
    if secret_file:
        f = tmp_path / "wechat_mp_appsecret"
        f.write_text(SECRET + "\n", encoding="utf-8")
        extra["WECHAT_MP_APPSECRET_FILE"] = f
    extra.update(over)
    transports = {"wechat": wx["transport"], "wechat_oauth": oauth or FakeOAuth()}
    return make_shop_app(settings, notifier, tmp_path, transports=transports, **extra)


def _client(app) -> TestClient:
    return TestClient(app, base_url="https://testserver")


def _row(database, token: str) -> ShopCheckout:
    with database.session() as db:
        return db.scalar(select(ShopCheckout).where(ShopCheckout.view_token == token))


def _all_rows_text(database) -> str:
    with database.engine.connect() as conn:
        return "\n".join(str(conn.execute(text(f'SELECT * FROM "{t}"')).fetchall()) for t in inspect(database.engine).get_table_names())


JSAPI = "wechat_native=pay.wechat,wechat_jsapi=pay.wechat"


def _start(c: TestClient) -> dict:
    r = c.post("/api/shop/checkout", json=checkout_body(method="wechat_jsapi"), headers={"user-agent": WECHAT_UA})
    assert r.status_code == 200, r.text
    return r.json()


def _authorize(c: TestClient, token: str) -> str:
    """走到微信授权页门口：返回 state。"""
    r = c.get(f"/api/shop/wx/oauth?t={token}", headers={"user-agent": WECHAT_UA}, follow_redirects=False)
    assert r.status_code == 302, r.text
    m = re.search(r"&state=([a-z0-9]{32})#wechat_redirect$", r.headers["location"])
    assert m, r.headers["location"]
    return m.group(1)


# ---------------------------------------------------------------- 微信里：JSAPI

def test_jsapi_hidden_without_appsecret(settings, notifier, tmp_path, database, wx):
    """没配 AppSecret：微信里不出「微信支付」、授权接口 404、后台写着缺哪项；配了文件就出现（文件优先于 .env 里的值）。"""
    app = _app(settings, notifier, tmp_path, wx, methods=JSAPI, secret_file=False)
    with _client(app) as c:
        cat = c.get("/api/shop/catalog", headers={"user-agent": WECHAT_UA}).json()
        assert cat["methods"] == [] and "电脑" in cat["hint"] and "支付宝" not in cat["hint"]  # 支付宝没开就不提它
        assert c.post("/api/shop/checkout", json=checkout_body(method="wechat_jsapi"), headers={"user-agent": WECHAT_UA}).status_code == 409
        assert c.get("/api/shop/wx/oauth?t=abcdefgh12345678", headers={"user-agent": WECHAT_UA}, follow_redirects=False).status_code == 404
        assert c.get("/api/shop/wx/callback?t=abcdefgh12345678&code=x&state=y", follow_redirects=False).status_code == 404
        assert c.post("/api/auth/login", json={"password": TEST_PASSWORD}).status_code == 200
        row = next(m for m in c.get("/api/admin/shop/status").json()["methods"] if m["method"] == "wechat_jsapi")
        assert not row["ready"] and any("WECHAT_MP_APPSECRET" in x for x in row["missing"])

    oauth = FakeOAuth()
    app2 = _app(settings, notifier, tmp_path / "b", wx, methods=JSAPI, oauth=oauth, WECHAT_MP_APPSECRET="env-value-not-used")
    with _client(app2) as c:
        cat = c.get("/api/shop/catalog", headers={"user-agent": WECHAT_UA}).json()
        assert [m["method"] for m in cat["methods"]] == ["wechat_jsapi"] and cat["hint"] == ""
        assert [m["method"] for m in c.get("/api/shop/catalog", headers={"user-agent": PC_UA}).json()["methods"]] == ["wechat_native"]
        v = _start(c)
        state = _authorize(c, v["view_token"])
        r = c.get(f"/api/shop/wx/callback?t={v['view_token']}&code=C1&state={state}", follow_redirects=False)
        assert r.headers["location"] == f"/order/pay/{v['view_token']}"
        assert oauth.calls[0]["secret"] == [SECRET]  # 用的是文件里的，不是 WECHAT_MP_APPSECRET


def test_jsapi_flow_oauth_prepay_and_paid_only_by_notify(settings, notifier, tmp_path, database, wx, caplog):
    """下单 → 网页授权（链接格式、state cookie）→ code 换 openid → JSAPI 下单（payer.openid）→ 调起参数（paySign 验得过）；
    openid 不落库、不进日志；同一个 code 回调两次只换一次；付没付只看通知。"""
    caplog.set_level(logging.DEBUG)
    oauth = FakeOAuth()
    app = _app(settings, notifier, tmp_path, wx, methods=JSAPI, oauth=oauth)
    with _client(app) as c:
        v = _start(c)
        token = v["view_token"]
        assert v["pay"]["kind"] == "oauth" and v["pay"]["payload"] == {"url": f"/api/shop/wx/oauth?t={token}"}
        assert wx["state"]["calls"] == []  # 还没拿到 openid：微信那边一单都没下

        r = c.get(f"/api/shop/wx/oauth?t={token}", headers={"user-agent": WECHAT_UA}, follow_redirects=False)
        loc = r.headers["location"]
        # 官方格式：参数顺序固定、redirect_uri urlEncode、snsapi_base、state a-zA-Z0-9、#wechat_redirect 结尾
        m = re.fullmatch(r"https://open\.weixin\.qq\.com/connect/oauth2/authorize\?appid=(\w+)&redirect_uri=([^&]+)"
                         r"&response_type=code&scope=snsapi_base&state=([a-z0-9]{32})#wechat_redirect", loc)
        assert m, loc
        assert m.group(1) == APPID and unquote(m.group(2)) == f"{BASE}/api/shop/wx/callback?t={token}" and "%2F" in m.group(2)
        state = m.group(3)
        cookie = r.headers["set-cookie"]
        assert f"psy_wxo={state}" in cookie and "HttpOnly" in cookie and "Path=/api/shop/wx" in cookie and "Secure" in cookie
        assert "samesite=lax" in cookie.lower()

        r = c.get(f"/api/shop/wx/callback?t={token}&code=CODE-1&state={state}", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == f"/order/pay/{token}"
        row = _row(database, token)
        body = wx["state"]["bodies"][row.out_trade_no]
        assert ("POST", "/v3/pay/transactions/jsapi") in wx["state"]["calls"]
        assert body["payer"] == {"openid": OPENID} and body["appid"] == APPID and body["amount"]["total"] == row.amount_fen

        got = c.get(f"/api/shop/checkout/{token}").json()
        pay = got["pay"]
        assert pay["kind"] == "jsapi" and got["status"] == "pending"
        p = pay["payload"]
        assert set(p) == {"appId", "timeStamp", "nonceStr", "package", "signType", "paySign"}
        assert p["appId"] == APPID and p["package"].startswith("prepay_id=") and p["signType"] == "RSA"
        msg = wechat_sign.jsapi_pay_message(appid=p["appId"], timestamp=p["timeStamp"], nonce_str=p["nonceStr"],
                                            prepay_id=p["package"].removeprefix("prepay_id="))
        assert wechat_sign.rsa_verify(wx["merchant_pub"], msg, p["paySign"])

        # 回调被重复打开（同一个 code）：不再去换 openid、不再下单
        n_jsapi = sum(1 for x in wx["state"]["calls"] if x[1] == "/v3/pay/transactions/jsapi")
        r = c.get(f"/api/shop/wx/callback?t={token}&code=CODE-1&state={state}", follow_redirects=False)
        assert r.status_code == 303  # cookie 已清：state 对不上，回付款页说一句（付款页已有参数，照样能付）
        # 已经有调起参数了：再走 /wx/oauth 直接回付款页，不再去微信授权
        r = c.get(f"/api/shop/wx/oauth?t={token}", headers={"user-agent": WECHAT_UA}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == f"/order/pay/{token}"
        assert len(oauth.calls) == 1 and sum(1 for x in wx["state"]["calls"] if x[1] == "/v3/pay/transactions/jsapi") == n_jsapi

        # openid 只在内存里用了一下：库里任何表、日志里都没有（付款后的 payer_ref 来自验过签的通知，这里还没付）
        assert OPENID not in _all_rows_text(database)
        assert OPENID not in caplog.text and SECRET not in caplog.text

        # 前端说「付了」不算：没有这样的接口；查单还是 NOTPAY 就还是待付款
        assert c.post(f"/api/shop/checkout/{token}", json={"err_msg": "get_brand_wcpay_request:ok"}).status_code in (404, 405)
        app.state.shop.settings.SHOP_QUERY_MIN_INTERVAL_SEC = 0
        assert c.get(f"/api/shop/checkout/{token}").json()["status"] == "pending"
        # 微信的付款通知到了才出码
        body, h = wx_notify(wx["key"], no=row.out_trade_no, total=row.amount_fen, openid=OPENID)
        assert c.post("/api/shop/pay/wechat/notify", content=body, headers=h).status_code == 204
        done = c.get(f"/api/shop/checkout/{token}").json()
        assert done["status"] == "paid" and done["code"].startswith("PSY-") and done["pay"]["payload"] == {}


def test_oauth_state_must_match(settings, notifier, tmp_path, database, wx):
    """state 对不上（没 cookie、被换掉）不换 openid、不下单，回付款页说「再试一次」；不在微信里打开不去授权页。"""
    oauth = FakeOAuth()
    app = _app(settings, notifier, tmp_path, wx, methods=JSAPI, oauth=oauth)
    with _client(app) as c:
        token = _start(c)["view_token"]
        r = c.get(f"/api/shop/wx/callback?t={token}&code=C&state={'a' * 32}", follow_redirects=False)  # 没有 cookie
        assert r.headers["location"] == f"/order/pay/{token}?wx=state"
        state = _authorize(c, token)
        r = c.get(f"/api/shop/wx/callback?t={token}&code=C&state={'b' * 32}", follow_redirects=False)  # 有 cookie、state 不一样
        assert r.headers["location"] == f"/order/pay/{token}?wx=state"
        assert state != "b" * 32 and oauth.calls == [] and wx["state"]["calls"] == []
        r = c.get(f"/api/shop/wx/oauth?t={token}", headers={"user-agent": MOBILE_UA}, follow_redirects=False)
        assert r.headers["location"] == f"/order/pay/{token}?wx=notwechat"
        assert c.get("/api/shop/wx/oauth?t=../../evil", headers={"user-agent": WECHAT_UA}, follow_redirects=False).status_code == 404


@pytest.mark.parametrize("case,expect", [("used", "fail"), ("conn", "fail"), ("snapshot", "snapshot"), ("nocode", "denied")])
def test_oauth_failures_back_to_pay_page(settings, notifier, tmp_path, database, wx, case, expect, caplog):
    """code 用过了、连不上微信、快照页虚拟账号、没带 code：都回付款页说清楚，不下单；记的事件里没有 secret、code。"""
    oauth = FakeOAuth(snapshot=case == "snapshot",
                      error=requests.ConnectionError(f"Max retries exceeded with url: /sns/oauth2/access_token?secret={SECRET}")
                      if case == "conn" else None)
    app = _app(settings, notifier, tmp_path, wx, methods=JSAPI, oauth=oauth)
    with _client(app) as c:
        token = _start(c)["view_token"]
        if case == "used":
            oauth.used.add("C-USED")
        state = _authorize(c, token)
        code = "" if case == "nocode" else "C-USED"
        r = c.get(f"/api/shop/wx/callback?t={token}&code={code}&state={state}", follow_redirects=False)
        assert r.headers["location"] == f"/order/pay/{token}?wx={expect}"
        assert ("POST", "/v3/pay/transactions/jsapi") not in wx["state"]["calls"]
        assert c.get(f"/api/shop/checkout/{token}").json()["pay"]["kind"] == "oauth"  # 还能再点「重新授权」
        everything = _all_rows_text(database) + caplog.text
        assert SECRET not in everything and "C-USED" not in everything


def test_unfinished_wechat_checkout_expires_without_gateway_calls(settings, notifier, tmp_path, database, wx):
    """授权没走完就放着：30 分钟后定时任务把它关掉，不去微信查单、关单（那边根本没下过单）。"""
    app = _app(settings, notifier, tmp_path, wx, methods=JSAPI)
    with _client(app) as c:
        token = _start(c)["view_token"]
        row = _row(database, token)
        run_tick(app, now=row.expires_at + timedelta(seconds=1))
        assert _row(database, token).status == "closed" and wx["state"]["calls"] == []
        assert c.get(f"/api/shop/wx/oauth?t={token}", headers={"user-agent": WECHAT_UA}, follow_redirects=False).headers["location"] \
            == f"/order/pay/{token}"


# ---------------------------------------------------------------- 手机浏览器：H5、复制到微信

H5 = "wechat_native=pay.wechat,wechat_jsapi=pay.wechat,wechat_h5=pay.wechat"


def test_h5_off_by_default_mobile_gets_open_in_wechat(settings, notifier, tmp_path, database, wx):
    """H5 默认不开：手机浏览器没有付款方式，JSAPI 开着就引导「复制网址到微信里打开」；JSAPI 也没开就说用电脑扫码。"""
    app = _app(settings, notifier, tmp_path, wx, methods=JSAPI)
    with _client(app) as c:
        cat = c.get("/api/shop/catalog", headers={"user-agent": MOBILE_UA}).json()
        assert cat["methods"] == [] and cat["open_in_wechat"] is True and "微信里打开" in cat["hint"]
        assert c.post("/api/shop/checkout", json=checkout_body(method="wechat_h5"), headers={"user-agent": MOBILE_UA}).status_code == 409
        assert c.get("/api/shop/catalog", headers={"user-agent": PC_UA}).json()["open_in_wechat"] is False
    app2 = _app(settings, notifier, tmp_path / "b", wx, methods=JSAPI, secret_file=False)
    with _client(app2) as c:
        cat = c.get("/api/shop/catalog", headers={"user-agent": MOBILE_UA}).json()
        assert cat["open_in_wechat"] is False and "电脑" in cat["hint"]


def test_h5_flow_url_fresh_and_redirect(settings, notifier, tmp_path, database, wx):
    """开了 H5：手机浏览器出「微信支付」、微信里不出；点付款时才 H5 下单（客人 IP、Wap），链接后面只拼 redirect_url；
    4 分钟内再点用同一个，过了用同一个商户订单号、原参数重新要。"""
    app = _app(settings, notifier, tmp_path, wx, methods=H5)
    with _client(app) as c:
        assert [m["method"] for m in c.get("/api/shop/catalog", headers={"user-agent": MOBILE_UA}).json()["methods"]] == ["wechat_h5"]
        assert [m["method"] for m in c.get("/api/shop/catalog", headers={"user-agent": WECHAT_UA}).json()["methods"]] == ["wechat_jsapi"]
        v = c.post("/api/shop/checkout", json=checkout_body(method="wechat_h5"), headers={"user-agent": MOBILE_UA}).json()
        token = v["view_token"]
        assert v["pay"]["kind"] == "h5" and wx["state"]["calls"] == []

        r = c.post(f"/api/shop/checkout/{token}/repay")
        assert r.status_code == 200, r.text
        got = r.json()
        row = _row(database, token)
        body = wx["state"]["bodies"][row.out_trade_no]
        assert body["scene_info"] == {"payer_client_ip": "testclient", "h5_info": {"type": "Wap"}}
        assert body["amount"]["total"] == row.amount_fen and "payer" not in body
        h5_url = "https://wx.tenpay.com/cgi-bin/mmpayweb-bin/checkmweb?prepay_id=wxH5TEST1&package=1405458241"
        assert got["pay"]["kind"] == "redirect"
        assert got["pay"]["payload"]["url"] == h5_url + "&redirect_url=" + quote(f"{BASE}/order/pay/{token}", safe="")

        assert c.post(f"/api/shop/checkout/{token}/repay").json()["pay"]["payload"]["url"] == got["pay"]["payload"]["url"]
        assert sum(1 for x in wx["state"]["calls"] if x[1] == "/v3/pay/transactions/h5") == 1
        with database.session() as db:  # 领到已经 5 分钟了
            r0 = db.scalar(select(ShopCheckout).where(ShopCheckout.view_token == token))
            r0.pay_payload = {**r0.pay_payload, "issued_at": (utcnow() - timedelta(minutes=5)).isoformat()}
        again = c.post(f"/api/shop/checkout/{token}/repay").json()
        assert "wxH5TEST2" in again["pay"]["payload"]["url"]
        assert wx["state"]["bodies"][row.out_trade_no]["out_trade_no"] == row.out_trade_no
        assert wx["state"]["bodies"][row.out_trade_no]["scene_info"]["payer_client_ip"] == "testclient"
        # 跳回来（redirect_url）不算付了：还是待付款，只认通知 / 查单
        assert c.get(f"/api/shop/checkout/{token}").json()["status"] == "pending"
        assert c.post("/api/shop/checkout/nope-nope-nope/repay").status_code == 404


# ---------------------------------------------------------------- 校验文件

def test_mp_verify_file_served_at_site_root(settings, notifier, tmp_path, wx):
    app = _app(settings, notifier, tmp_path, wx, methods=JSAPI, WECHAT_MP_VERIFY_FILE="MP_verify_AbC123xyz.txt",
               WECHAT_MP_VERIFY_CONTENT="AbC123xyz")
    with _client(app) as c:
        r = c.get("/MP_verify_AbC123xyz.txt")
        assert r.status_code == 200 and r.text == "AbC123xyz" and r.headers["content-type"].startswith("text/plain")
        assert c.get("/MP_verify_other.txt").status_code == 404
    bad = _app(settings, notifier, tmp_path / "b", wx, methods=JSAPI, WECHAT_MP_VERIFY_FILE="../etc/passwd",
               WECHAT_MP_VERIFY_CONTENT="x")
    with _client(bad) as c:
        assert c.get("/MP_verify_x.txt").status_code == 404


def test_jsapi_pay_sign_message_matches_official_example():
    """签名串和官方「JSAPI调起支付签名」第 2 节的例子一字不差（四行、每行 \\n 结尾、含最后一行）。"""
    msg = wechat_sign.jsapi_pay_message(appid="wx2421b1c4370ec43b", timestamp="1554208460",
                                        nonce_str="593BEC0C930BF1AFEB40B4A08C8FB242",
                                        prepay_id="wx201410272009395522657a690389285100")
    assert msg == "wx2421b1c4370ec43b\n1554208460\n593BEC0C930BF1AFEB40B4A08C8FB242\nprepay_id=wx201410272009395522657a690389285100\n"
