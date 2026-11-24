"""pay.wechat、pay.alipay 走一遍：下单 → 通知（验签、解密、核金额和商户号）→ 建单出码；查单、退款。
网关是 httpx.MockTransport 假扮的（它也验我们的签名），密钥是测试里现生成的：不联网、不读真密钥。"""

from __future__ import annotations

import json
from urllib.parse import parse_qs, parse_qsl, urlencode, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.intake.models import ActivationCode, Order
from app.shop.models import ShopCheckout, ShopNotification
from app.shop.paycore import alipay_sign, keys, wechat_sign
from tests.conftest import TEST_PASSWORD
from tests.shop.helpers import PC_UA, checkout_body, make_shop_app, new_rsa

APIV3 = "0123456789abcdef0123456789ABCDEF"
MCHID, APPID, PUB_ID = "1900000001", "wxtestappid000000", "PUB_KEY_ID_TEST"
ALI_APP = "2021000000000000"


# ---------------------------------------------------------------- 假微信支付

@pytest.fixture
def wx(tmp_path):
    mkey, mpriv, mpub = new_rsa()  # 商户的
    wkey, _, wpub = new_rsa()  # 「微信支付」的
    (tmp_path / "apiclient_key.pem").write_bytes(mpriv)
    (tmp_path / "wechatpay_pub.pem").write_bytes(wpub)
    state = {"trade_state": "NOTPAY", "refund_status": "SUCCESS", "calls": [], "bodies": {}}
    merchant_pub = keys.load_public_key(mpub)

    def handler(request: httpx.Request) -> httpx.Response:
        auth = request.headers["authorization"]
        f = {k: v.strip('"') for k, v in (p.split("=", 1) for p in auth.split(" ", 1)[1].split(","))}
        path = request.url.raw_path.decode()
        msg = wechat_sign.request_message(request.method, path, f["timestamp"], f["nonce_str"], request.content.decode())
        assert wechat_sign.rsa_verify(merchant_pub, msg, f["signature"]), "我们发给微信的请求签名不对"
        state["calls"].append((request.method, request.url.path))
        if request.url.path.endswith("/close"):
            return httpx.Response(204)
        if request.url.path in ("/v3/pay/transactions/native", "/v3/pay/transactions/jsapi", "/v3/pay/transactions/h5"):
            body = json.loads(request.content)
            state["bodies"][body["out_trade_no"]] = body
            kind = request.url.path.rsplit("/", 1)[-1]
            n = sum(1 for c in state["calls"] if c[1] == request.url.path)
            resp = ({"code_url": "weixin://wxpay/bizpayurl?pr=TEST" + body["out_trade_no"][-4:]} if kind == "native" else
                    {"prepay_id": f"wx2026TESTPREPAY{n}"} if kind == "jsapi" else
                    {"h5_url": f"https://wx.tenpay.com/cgi-bin/mmpayweb-bin/checkmweb?prepay_id=wxH5TEST{n}&package=1405458241"})
        elif request.url.path.startswith("/v3/pay/transactions/out-trade-no/"):
            no = request.url.path.rsplit("/", 1)[-1]
            total = state["bodies"].get(no, {}).get("amount", {}).get("total", 0)
            resp = {"appid": APPID, "mchid": MCHID, "out_trade_no": no, "transaction_id": "42000Q" + no[-6:],
                    "trade_state": state["trade_state"], "payer": {"openid": "o_query"}, "amount": {"total": total}}
        elif request.url.path.startswith("/v3/refund/domestic/refunds"):
            resp = {"refund_id": "50300" + str(len(state["calls"])), "status": state["refund_status"]}
        else:
            return httpx.Response(404, json={"code": "NOT_FOUND", "message": "x"})
        raw = json.dumps(resp).encode()
        return httpx.Response(200, content=raw, headers={**wechat_sign.signed_headers(wkey, raw, serial=PUB_ID),
                                                         "content-type": "application/json"})

    over = dict(SHOP_FAKE_PAY=False, SHOP_METHODS="wechat_native=pay.wechat", WECHATPAY_MCHID=MCHID, WECHATPAY_APPID=APPID,
                WECHATPAY_CERT_SERIAL="MERCHANT_SERIAL", WECHATPAY_PRIVATE_KEY_PATH=tmp_path / "apiclient_key.pem",
                WECHATPAY_APIV3_KEY=APIV3, WECHATPAY_PUBLIC_KEY_ID=PUB_ID, WECHATPAY_PUBLIC_KEY_PATH=tmp_path / "wechatpay_pub.pem",
                WECHATPAY_NOTIFY_URL="https://psyppt.example.cn/api/shop/pay/wechat/notify", WECHATPAY_API_BASE="https://wx.test")
    return {"key": wkey, "state": state, "transport": httpx.MockTransport(handler), "over": over, "merchant_pub": merchant_pub}


def wx_notify(key, *, no: str, total: int, mchid: str = MCHID, appid: str = APPID, txn: str = "4200000001",
              openid: str = "o_payer_1", event: str = "TRANSACTION.SUCCESS") -> tuple[bytes, dict[str, str]]:
    tx = {"appid": appid, "mchid": mchid, "out_trade_no": no, "transaction_id": txn, "trade_type": "NATIVE",
          "trade_state": "SUCCESS", "success_time": "2026-11-18T20:00:00+08:00", "payer": {"openid": openid},
          "amount": {"total": total, "payer_total": total, "currency": "CNY"}}
    res = wechat_sign.encrypt_resource(APIV3, json.dumps(tx).encode())
    body = json.dumps({"id": "EV-" + txn, "event_type": event, "resource_type": "encrypt-resource",
                       "resource": {"original_type": "transaction", **res}}).encode()
    return body, wechat_sign.signed_headers(key, body, serial=PUB_ID)


def _orders(database) -> int:
    with database.session() as db:
        return db.scalar(select(func.count()).select_from(Order)) or 0


def _checkout(database) -> ShopCheckout:
    with database.session() as db:
        return db.scalars(select(ShopCheckout).order_by(ShopCheckout.id.desc())).first()


def test_notify_must_verify_signature(settings, notifier, tmp_path, database, wx):
    """检查 4：伪造签名、篡改金额、换商户号 / AppID 的通知都不建单、不出码；对的才建。"""
    app = make_shop_app(settings, notifier, tmp_path, transports={"wechat": wx["transport"]}, **wx["over"])
    with TestClient(app) as c:
        r = c.post("/api/shop/checkout", json=checkout_body(), headers={"user-agent": PC_UA})
        assert r.status_code == 200, r.text
        v = r.json()
        assert v["pay"]["kind"] == "qr" and v["pay"]["payload"]["code_url"].startswith("weixin://") and v["pay"]["payload"]["qr"]
        row = _checkout(database)
        assert wx["state"]["bodies"][row.out_trade_no]["amount"]["total"] == row.amount_fen == 4980

        other, _, _ = new_rsa()
        body, h = wx_notify(other, no=row.out_trade_no, total=4980)  # 别人签的
        assert c.post("/api/shop/pay/wechat/notify", content=body, headers=h).status_code == 401
        body, h = wx_notify(wx["key"], no=row.out_trade_no, total=1, txn="T-AMOUNT")  # 金额被改
        assert c.post("/api/shop/pay/wechat/notify", content=body, headers=h).status_code == 500
        body, h = wx_notify(wx["key"], no=row.out_trade_no, total=4980, mchid="1999999999", txn="T-MCH")  # 别的商户号
        assert c.post("/api/shop/pay/wechat/notify", content=body, headers=h).status_code == 500
        body, h = wx_notify(wx["key"], no=row.out_trade_no, total=4980, appid="wxother", txn="T-APP")
        assert c.post("/api/shop/pay/wechat/notify", content=body, headers=h).status_code == 500
        assert _orders(database) == 0 and c.get(f"/api/shop/checkout/{v['view_token']}").json()["code"] == ""
        assert any("对不上" in s for s in notifier.sent)

        body, h = wx_notify(wx["key"], no=row.out_trade_no, total=4980)
        assert c.post("/api/shop/pay/wechat/notify", content=body, headers=h).status_code == 204
        got = c.get(f"/api/shop/checkout/{v['view_token']}").json()
        assert got["status"] == "paid" and got["code"].startswith("PSY-")
        assert _orders(database) == 1
        with database.session() as db:
            o = db.scalar(select(Order))
            assert (o.platform, o.platform_order_id, o.paid_amount, o.buyer_id) == ("web", row.out_trade_no, "49.80", "wx:o_payer_1")
            assert o.sku == "regular-p2_3" and [a["key"] for a in o.addons] == ["revision"] and o.stage == "paid"
            assert db.scalar(select(func.count()).select_from(ShopNotification).where(ShopNotification.verified.is_(False))) >= 1

    # 假网关：伪造签名也不认
    app2 = make_shop_app(settings, notifier, tmp_path / "f")
    with TestClient(app2) as c:
        v = c.post("/api/shop/checkout", json=checkout_body(), headers={"user-agent": PC_UA}).json()
        row = _checkout(database)
        fake = json.dumps({"event": "pay", "out_trade_no": row.out_trade_no, "amount_fen": row.amount_fen, "txn_id": "X",
                           "payer_ref": "p", "merchant": "fake-merchant", "sign": "0" * 64}).encode()
        assert c.post("/api/shop/pay/fake/notify", content=fake).status_code == 400
        assert c.get(f"/api/shop/checkout/{v['view_token']}").json()["code"] == ""


def test_wechat_query_recovers_lost_notify_and_refund(settings, notifier, tmp_path, database, wx):
    app = make_shop_app(settings, notifier, tmp_path, transports={"wechat": wx["transport"]}, **wx["over"])
    with TestClient(app) as c:
        v = c.post("/api/shop/checkout", json=checkout_body(extra_revisions=0, band="p1"), headers={"user-agent": PC_UA}).json()
        assert c.get(f"/api/shop/checkout/{v['view_token']}").json()["status"] == "pending"  # 查单：还没付
        wx["state"]["trade_state"] = "SUCCESS"  # 付了，但通知丢了
        app.state.shop.settings.SHOP_QUERY_MIN_INTERVAL_SEC = 0
        got = c.get(f"/api/shop/checkout/{v['view_token']}").json()
        assert got["status"] == "paid" and got["code"]
        row = _checkout(database)
        assert row.payer_ref == "wx:o_query" and row.paid_fen == 2990
        assert c.post("/api/auth/login", json={"password": TEST_PASSWORD}).status_code == 200
        r = c.post("/api/admin/shop/refunds", json={"order_id": row.order_id, "amount_fen": 2990, "reason": "开工前撤单"})
        assert r.status_code == 200 and r.json()["exit"] == "ok", r.text
        with database.session() as db:
            o = db.get(Order, row.order_id)
            assert o.stage == "void" and o.void_reason == "refund"
            assert db.scalar(select(ActivationCode).where(ActivationCode.order_id == o.id)).status == "void"
        assert ("POST", "/v3/refund/domestic/refunds") in wx["state"]["calls"]


def test_wechat_missing_config_means_method_hidden(settings, notifier, tmp_path, wx):
    over = {**wx["over"], "WECHATPAY_APIV3_KEY": ""}
    app = make_shop_app(settings, notifier, tmp_path, transports={"wechat": wx["transport"]}, **over)
    with TestClient(app) as c:
        cat = c.get("/api/shop/catalog", headers={"user-agent": PC_UA}).json()
        # 一种真网关都没配好：自有网页暂不收款，「去付款」换成去小红书 / 闲鱼下单
        assert cat["methods"] == [] and cat["pay_mode"] == "platforms" and "小红书或闲鱼下单" in cat["hint"]
        assert c.post("/api/shop/checkout", json=checkout_body(), headers={"user-agent": PC_UA}).status_code == 409
        assert c.post("/api/auth/login", json={"password": TEST_PASSWORD}).status_code == 200
        st = c.get("/api/admin/shop/status").json()
        native = next(m for m in st["methods"] if m["method"] == "wechat_native")
        assert native["missing"] == ["WECHATPAY_APIV3_KEY"] and not native["ready"]


# ---------------------------------------------------------------- 假支付宝

@pytest.fixture
def ali(tmp_path):
    akey, apriv, apub = new_rsa()  # 应用的
    zkey, _, zpub = new_rsa()  # 「支付宝」的
    (tmp_path / "app_private.pem").write_bytes(apriv)
    (tmp_path / "alipay_public.pem").write_bytes(zpub)
    app_pub = keys.load_public_key(apub)
    state = {"trade_status": "WAIT_BUYER_PAY", "calls": []}

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(parse_qsl(request.content.decode()))
        assert alipay_sign.rsa2_verify(app_pub, alipay_sign.sign_content(params), params["sign"]), "我们的请求签名不对"
        method = params["method"]
        biz = json.loads(params["biz_content"])
        state["calls"].append(method)
        if method == "alipay.trade.query":
            body = {"code": "10000", "msg": "Success", "out_trade_no": biz["out_trade_no"], "trade_no": "2026111822001",
                    "trade_status": state["trade_status"], "total_amount": state.get("amount", "0.00"), "buyer_open_id": "ali_q"}
        elif method == "alipay.trade.refund":
            body = {"code": "10000", "msg": "Success", "fund_change": "Y", "trade_no": "2026111822001"}
        else:
            body = {"code": "10000", "msg": "Success"}
        return httpx.Response(200, text=alipay_sign.signed_response(zkey, method, body))

    over = dict(SHOP_FAKE_PAY=False, SHOP_METHODS="alipay_page=pay.alipay,alipay_wap=pay.alipay", ALIPAY_APP_ID=ALI_APP,
                ALIPAY_PRIVATE_KEY_PATH=tmp_path / "app_private.pem", ALIPAY_PUBLIC_KEY_PATH=tmp_path / "alipay_public.pem",
                ALIPAY_NOTIFY_URL="https://psyppt.example.cn/api/shop/pay/alipay/notify", ALIPAY_GATEWAY="https://ali.test/gateway.do")
    return {"key": zkey, "app_pub": app_pub, "state": state, "transport": httpx.MockTransport(handler), "over": over}


def ali_notify(key, *, no: str, amount: str, app_id: str = ALI_APP, status: str = "TRADE_SUCCESS") -> bytes:
    p = {"notify_id": "N1", "notify_type": "trade_status_sync", "app_id": app_id, "out_trade_no": no, "trade_no": "2026111822001",
         "total_amount": amount, "trade_status": status, "buyer_open_id": "ali_buyer_1", "gmt_payment": "2026-11-18 20:00:00",
         "charset": "utf-8"}
    p["sign"] = alipay_sign.rsa2_sign(key, alipay_sign.sign_content(p, drop=("sign", "sign_type")))
    p["sign_type"] = "RSA2"
    return urlencode(p).encode()


def test_alipay_pay_url_notify_and_refund(settings, notifier, tmp_path, database, ali):
    app = make_shop_app(settings, notifier, tmp_path, transports={"alipay": ali["transport"]}, **ali["over"])
    form = {"content-type": "application/x-www-form-urlencoded"}
    with TestClient(app) as c:
        v = c.post("/api/shop/checkout", json=checkout_body(method="alipay_page"), headers={"user-agent": PC_UA}).json()
        assert v["pay"]["kind"] == "redirect"
        url = urlparse(v["pay"]["payload"]["url"])
        q = {k: vs[0] for k, vs in parse_qs(url.query).items()}
        assert alipay_sign.rsa2_verify(ali["app_pub"], alipay_sign.sign_content(q), q["sign"])
        biz = json.loads(q["biz_content"])
        assert biz["total_amount"] == "49.80" and biz["product_code"] == "FAST_INSTANT_TRADE_PAY" and q["notify_url"].endswith("/alipay/notify")
        row = _checkout(database)
        assert c.get(f"/api/shop/checkout/{v['view_token']}").json()["status"] == "pending"  # 查单：等付款

        other, _, _ = new_rsa()
        r = c.post("/api/shop/pay/alipay/notify", content=ali_notify(other, no=row.out_trade_no, amount="49.80"), headers=form)
        assert r.status_code == 400 and r.text == "fail"
        r = c.post("/api/shop/pay/alipay/notify", content=ali_notify(ali["key"], no=row.out_trade_no, amount="0.01"), headers=form)
        assert r.status_code == 500 and _orders(database) == 0
        r = c.post("/api/shop/pay/alipay/notify", content=ali_notify(ali["key"], no=row.out_trade_no, amount="49.80", app_id="2021999"),
                   headers=form)
        assert r.status_code == 500 and _orders(database) == 0
        r = c.post("/api/shop/pay/alipay/notify", content=ali_notify(ali["key"], no=row.out_trade_no, amount="49.80"), headers=form)
        assert r.status_code == 200 and r.text == "success"
        got = c.get(f"/api/shop/checkout/{v['view_token']}").json()
        assert got["code"].startswith("PSY-") and _checkout(database).payer_ref == "ali:ali_buyer_1"

        assert c.post("/api/auth/login", json={"password": TEST_PASSWORD}).status_code == 200
        r = c.post("/api/admin/shop/refunds", json={"order_id": _checkout(database).order_id, "amount_fen": 990, "scope": "addon:revision",
                                                    "reason": "第二轮没用上"})
        assert r.json()["exit"] == "ok"
        row = _checkout(database)
        assert (row.status, row.refunded_fen) == ("part_refunded", 990)
        with database.session() as db:
            assert db.get(Order, row.order_id).stage == "paid"  # 部分退款不作废
        assert "alipay.trade.refund" in ali["state"]["calls"]

        v2 = c.post("/api/shop/checkout", json=checkout_body(method="alipay_wap"),
                    headers={"user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Mobile/15E148"}).json()
        q2 = {k: vs[0] for k, vs in parse_qs(urlparse(v2["pay"]["payload"]["url"]).query).items()}
        assert q2["method"] == "alipay.trade.wap.pay" and json.loads(q2["biz_content"])["product_code"] == "QUICK_WAP_WAY"
