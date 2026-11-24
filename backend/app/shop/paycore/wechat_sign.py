"""微信支付 APIv3 的签名、验签、解密（照净界AI server/wxpay.mjs 的做法，用 cryptography 手写，不装 wechatpayv3）。

- 请求签名：SHA256-RSA（PKCS#1 v1.5），签名串「方法\\n路径\\n时间戳\\n随机串\\n请求体\\n」，放进 Authorization 头。
- 应答 / 通知验签：签名串「时间戳\\n随机串\\n应答体\\n」，用微信支付公钥验；时间戳和现在差超过 5 分钟不认（防重放）。
- 通知解密：AEAD_AES_256_GCM，钥匙是 APIv3 密钥（32 字节）。
- JSAPI 调起支付的 paySign：「appId\\n时间戳\\n随机串\\nprepay_id=…\\n」。
出处：微信支付 APIv3 文档「签名生成」「签名验证」「证书和回调报文解密」「JSAPI 调起支付」。
"""

from __future__ import annotations

import base64
import secrets
import time

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

SCHEMA = "WECHATPAY2-SHA256-RSA2048"
MAX_SKEW_SECONDS = 300


def rsa_sign(private_key: RSAPrivateKey, message: str) -> str:
    sig = private_key.sign(message.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(sig).decode()


def rsa_verify(public_key: RSAPublicKey, message: str, signature_b64: str) -> bool:
    try:
        public_key.verify(base64.b64decode(signature_b64), message.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def nonce(n: int = 16) -> str:
    return secrets.token_hex(n)


def request_message(method: str, url_path: str, timestamp: str, nonce_str: str, body: str) -> str:
    """url_path 是去掉域名的部分（带查询串），GET 的 body 是空串。"""
    return f"{method.upper()}\n{url_path}\n{timestamp}\n{nonce_str}\n{body}\n"


def authorization(*, mchid: str, serial_no: str, private_key: RSAPrivateKey, method: str, url_path: str, body: str,
                  timestamp: str | None = None, nonce_str: str | None = None) -> str:
    ts = timestamp or str(int(time.time()))
    nc = nonce_str or nonce()
    sig = rsa_sign(private_key, request_message(method, url_path, ts, nc, body))
    return f'{SCHEMA} mchid="{mchid}",nonce_str="{nc}",signature="{sig}",timestamp="{ts}",serial_no="{serial_no}"'


def response_message(timestamp: str, nonce_str: str, body: str) -> str:
    return f"{timestamp}\n{nonce_str}\n{body}\n"


def _h(headers: dict[str, str], name: str) -> str:
    low = {k.lower(): v for k, v in headers.items()}
    return low.get(name.lower(), "")


def verify_signature(public_key: RSAPublicKey, headers: dict[str, str], body: bytes, *, expect_serial: str = "",
                     now: float | None = None) -> tuple[bool, str]:
    """验应答或通知的签名。返回（对不对，不对的原因）。"""
    ts, nc, sig, serial = (_h(headers, "Wechatpay-Timestamp"), _h(headers, "Wechatpay-Nonce"),
                           _h(headers, "Wechatpay-Signature"), _h(headers, "Wechatpay-Serial"))
    if not (ts and nc and sig):
        return False, "缺 Wechatpay-Timestamp / Nonce / Signature 头"
    if expect_serial and serial and serial != expect_serial:
        return False, f"签名用的公钥序列号 {serial} 跟配置的 {expect_serial} 对不上"
    try:
        skew = abs((now if now is not None else time.time()) - int(ts))
    except ValueError:
        return False, "时间戳不是数字"
    if skew > MAX_SKEW_SECONDS:
        return False, f"时间戳和现在差 {int(skew)} 秒，超过 5 分钟"
    if sig.startswith("WECHATPAY/SIGNTEST/"):
        return False, "微信的签名探测请求（故意给的错签名）"
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return False, "应答体不是 UTF-8"
    if not rsa_verify(public_key, response_message(ts, nc, text), sig):
        return False, "签名不对"
    return True, ""


def signed_headers(private_key: RSAPrivateKey, body: bytes, *, serial: str, timestamp: str | None = None,
                   nonce_str: str | None = None) -> dict[str, str]:
    """按微信的规矩给一段应答体签名（测试里假装是微信；pay.fake 不用它）。"""
    ts = timestamp or str(int(time.time()))
    nc = nonce_str or nonce()
    sig = rsa_sign(private_key, response_message(ts, nc, body.decode("utf-8")))
    return {"Wechatpay-Timestamp": ts, "Wechatpay-Nonce": nc, "Wechatpay-Signature": sig, "Wechatpay-Serial": serial}


def decrypt_resource(apiv3_key: str, *, nonce_str: str, ciphertext: str, associated_data: str = "") -> bytes:
    """解通知里的 resource。钥匙不对、被改过都会抛 ValueError。"""
    key = apiv3_key.encode("utf-8")
    if len(key) != 32:
        raise ValueError("APIv3 密钥要 32 个字符")
    try:
        return AESGCM(key).decrypt(nonce_str.encode("utf-8"), base64.b64decode(ciphertext),
                                   associated_data.encode("utf-8") if associated_data else None)
    except (InvalidTag, ValueError) as e:
        raise ValueError("通知解不开（APIv3 密钥不对或内容被改过）") from e


def encrypt_resource(apiv3_key: str, plaintext: bytes, *, nonce_str: str | None = None,
                     associated_data: str = "transaction") -> dict[str, str]:
    """跟上面反过来（测试里造通知用）。"""
    nc = nonce_str or secrets.token_hex(6)
    ct = AESGCM(apiv3_key.encode("utf-8")).encrypt(nc.encode("utf-8"), plaintext, associated_data.encode("utf-8"))
    return {"algorithm": "AEAD_AES_256_GCM", "ciphertext": base64.b64encode(ct).decode(), "nonce": nc,
            "associated_data": associated_data}


def jsapi_pay_message(*, appid: str, timestamp: str, nonce_str: str, prepay_id: str) -> str:
    """JSAPI 调起支付的签名串：四行（appId、时间戳、随机串、prepay_id=…），每行以 \\n 结尾、包括最后一行。
    出处：微信支付「JSAPI调起支付签名」https://pay.weixin.qq.com/doc/v3/merchant/4012365339 第 2 节。"""
    return f"{appid}\n{timestamp}\n{nonce_str}\nprepay_id={prepay_id}\n"


def jsapi_pay_sign(private_key: RSAPrivateKey, *, appid: str, timestamp: str, nonce_str: str, prepay_id: str) -> str:
    """用商户 API 证书私钥做 SHA256 with RSA，再 Base64（同上第 3 节；「调起支付与下单计算签名使用的商户API证书需保持一致」）。"""
    return rsa_sign(private_key, jsapi_pay_message(appid=appid, timestamp=timestamp, nonce_str=nonce_str, prepay_id=prepay_id))
