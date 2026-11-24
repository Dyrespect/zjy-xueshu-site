"""签名、验签、解密、二维码的纯函数：全部用测试里现生成的密钥做往返，不读任何真密钥、不联网（设计第十节验收 3）。"""

from __future__ import annotations

import base64
import json
import time

import pytest
from cryptography.hazmat.primitives import serialization

from app.shop.paycore import alipay_sign, fake_sign, keys, qr, wechat_sign
from tests.shop.helpers import new_rsa

APIV3 = "0123456789abcdef0123456789ABCDEF"  # 测试用的 32 位，不是真的


def test_wechat_request_signature_roundtrip():
    key, _, pub = new_rsa()
    auth = wechat_sign.authorization(mchid="1900000001", serial_no="SERIAL1", private_key=key, method="POST",
                                     url_path="/v3/pay/transactions/native", body='{"a":1}', timestamp="1700000000",
                                     nonce_str="abc")
    assert auth.startswith("WECHATPAY2-SHA256-RSA2048 ")
    fields = dict(part.split("=", 1) for part in auth.split(" ", 1)[1].split(","))
    sig = fields["signature"].strip('"')
    msg = wechat_sign.request_message("POST", "/v3/pay/transactions/native", "1700000000", "abc", '{"a":1}')
    assert wechat_sign.rsa_verify(keys.load_public_key(pub), msg, sig)
    assert not wechat_sign.rsa_verify(keys.load_public_key(pub), msg.replace('"a":1', '"a":2'), sig)


def test_wechat_response_verify_rejects_forged_old_and_wrong_serial():
    key, _, pub = new_rsa()
    other, _, _ = new_rsa()
    body = b'{"code_url":"weixin://wxpay/bizpayurl?pr=abc"}'
    pk = keys.load_public_key(pub)
    good = wechat_sign.signed_headers(key, body, serial="PUB_KEY_ID_1")
    assert wechat_sign.verify_signature(pk, good, body, expect_serial="PUB_KEY_ID_1") == (True, "")
    assert not wechat_sign.verify_signature(pk, good, body + b" ", expect_serial="PUB_KEY_ID_1")[0]  # 改了内容
    forged = wechat_sign.signed_headers(other, body, serial="PUB_KEY_ID_1")
    assert wechat_sign.verify_signature(pk, forged, body)[1] == "签名不对"
    old = wechat_sign.signed_headers(key, body, serial="PUB_KEY_ID_1", timestamp=str(int(time.time()) - 600))
    assert "超过 5 分钟" in wechat_sign.verify_signature(pk, old, body)[1]
    assert "对不上" in wechat_sign.verify_signature(pk, good, body, expect_serial="PUB_KEY_ID_2")[1]
    assert not wechat_sign.verify_signature(pk, {}, body)[0]


def test_wechat_resource_decrypt_roundtrip_and_tamper():
    plain = json.dumps({"out_trade_no": "PS2611181200001ABCDE", "amount": {"total": 2990}}).encode()
    res = wechat_sign.encrypt_resource(APIV3, plain)
    assert wechat_sign.decrypt_resource(APIV3, nonce_str=res["nonce"], ciphertext=res["ciphertext"],
                                        associated_data=res["associated_data"]) == plain
    with pytest.raises(ValueError):
        wechat_sign.decrypt_resource("x" * 32, nonce_str=res["nonce"], ciphertext=res["ciphertext"],
                                     associated_data=res["associated_data"])
    bad = base64.b64encode(b"\x00" + base64.b64decode(res["ciphertext"])[1:]).decode()
    with pytest.raises(ValueError):
        wechat_sign.decrypt_resource(APIV3, nonce_str=res["nonce"], ciphertext=bad, associated_data=res["associated_data"])


def test_wechat_jsapi_pay_sign_verifies():
    key, _, pub = new_rsa()
    sig = wechat_sign.jsapi_pay_sign(key, appid="wx0000", timestamp="1700000000", nonce_str="n1", prepay_id="up_1")
    assert wechat_sign.rsa_verify(keys.load_public_key(pub), "wx0000\n1700000000\nn1\nprepay_id=up_1\n", sig)


def test_alipay_sign_notify_and_response_roundtrip():
    key, _, pub = new_rsa()
    pk = keys.load_public_key(pub)
    params = {"app_id": "2021000000000000", "method": "alipay.trade.page.pay", "charset": "utf-8", "sign_type": "RSA2",
              "biz_content": '{"out_trade_no":"PS1","total_amount":"29.90"}', "empty": ""}
    signed = alipay_sign.sign_params(key, params)
    assert alipay_sign.rsa2_verify(pk, alipay_sign.sign_content(signed), signed["sign"])
    assert "empty=" not in alipay_sign.sign_content(signed)  # 空值不参与
    # 异步通知：sign、sign_type 都不参与
    notify = {"out_trade_no": "PS1", "total_amount": "29.90", "trade_status": "TRADE_SUCCESS", "app_id": "2021000000000000"}
    notify["sign"] = alipay_sign.rsa2_sign(key, alipay_sign.sign_content(notify, drop=("sign", "sign_type")))
    notify["sign_type"] = "RSA2"
    assert alipay_sign.verify_notify(pk, notify)
    assert not alipay_sign.verify_notify(pk, {**notify, "total_amount": "0.01"})
    assert not alipay_sign.verify_notify(pk, {k: v for k, v in notify.items() if k != "sign"})
    # 同步应答：签的是 _response 那一段的原文
    text = alipay_sign.signed_response(key, "alipay.trade.query", {"code": "10000", "trade_status": "TRADE_SUCCESS",
                                                                  "extra": {"nested": [1, {"a": "}"}]}})
    ok, body = alipay_sign.verify_response(pk, text, "alipay.trade.query")
    assert ok and body["trade_status"] == "TRADE_SUCCESS"
    assert not alipay_sign.verify_response(pk, text.replace("TRADE_SUCCESS", "TRADE_CLOSED"), "alipay.trade.query")[0]


def test_keys_load_one_line_base64_like_alipay_console():
    key, priv_pem, pub_pem = new_rsa()
    der_priv = key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    der_pub = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    k1 = keys.load_private_key(base64.b64encode(der_priv).decode())
    p1 = keys.load_public_key(base64.b64encode(der_pub).decode())
    sig = alipay_sign.rsa2_sign(k1, "hello")
    assert alipay_sign.rsa2_verify(p1, "hello", sig) and alipay_sign.rsa2_verify(keys.load_public_key(pub_pem), "hello", sig)
    with pytest.raises(keys.KeyError_):
        keys.load_private_key("not a key")
    with pytest.raises(keys.KeyError_):
        keys.read_private_key(None)


def test_fake_sign():
    body = {"out_trade_no": "PS1", "amount_fen": 2990}
    body["sign"] = fake_sign.sign("s1", body)
    assert fake_sign.verify("s1", body)
    assert not fake_sign.verify("s2", body)
    assert not fake_sign.verify("s1", {**body, "amount_fen": 1})


def _finder_ok(m, x0, y0):
    for dy in range(7):
        for dx in range(7):
            ring = max(abs(dx - 3), abs(dy - 3))
            if m[y0 + dy][x0 + dx] != (ring != 2):
                return False
    return True


def test_qr_structure():
    """二维码画得对不对，本机另用 macOS CoreImage 解过（版本 3–10、中文都能解）；这里查结构：尺寸、三个定位块、两份格式信息一致。"""
    for text, size in (("weixin://wxpay/bizpayurl?pr=AbCdEf123", 29), ("A" * 150, 49), ("a" * 200, 57)):
        m = qr.encode(text)
        n = len(m)
        assert n == size and all(len(r) == n for r in m)
        assert _finder_ok(m, 0, 0) and _finder_ok(m, n - 7, 0) and _finder_ok(m, 0, n - 7)
        first = [m[y][8] for y in (0, 1, 2, 3, 4, 5, 7, 8)] + [m[8][x] for x in (7, 5, 4, 3, 2, 1, 0)]
        second = [m[8][x] for x in range(n - 1, n - 9, -1)] + [m[y][8] for y in range(n - 7, n)]
        assert first == second
        assert m[n - 8][8] is True  # 那个固定的深色块
    assert qr.rows("ab") == ["".join("1" if v else "0" for v in r) for r in qr.encode("ab")]
    with pytest.raises(ValueError):
        qr.encode("x" * 400)
