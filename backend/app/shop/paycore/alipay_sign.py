"""支付宝开放平台 RSA2 签名、验签（用 cryptography 手写，不装支付宝 SDK）。

- 请求签名：参数按键名排序，去掉 sign 和空值，拼成 k=v&k=v，SHA256WithRSA（PKCS#1 v1.5），base64。
- 异步通知验签：去掉 sign、sign_type，同样排序拼接，用支付宝公钥验。
- 同步应答验签：签的是应答 JSON 里「xxx_response」那一段的原文（不是重新序列化的），要从原文里截出来。
出处：支付宝开放平台「自行实现签名」「自行实现验签」「异步通知说明」。
"""

from __future__ import annotations

import base64
import json
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey


def sign_content(params: dict[str, Any], *, drop: tuple[str, ...] = ("sign",)) -> str:
    items = sorted((k, v) for k, v in params.items() if k not in drop and v not in (None, ""))
    return "&".join(f"{k}={v}" for k, v in items)


def rsa2_sign(private_key: RSAPrivateKey, content: str) -> str:
    return base64.b64encode(private_key.sign(content.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())).decode()


def rsa2_verify(public_key: RSAPublicKey, content: str, sign_b64: str) -> bool:
    try:
        public_key.verify(base64.b64decode(sign_b64), content.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def sign_params(private_key: RSAPrivateKey, params: dict[str, Any]) -> dict[str, Any]:
    """给请求参数签名，返回带 sign 的新字典（sign_type 参与签名）。"""
    return {**params, "sign": rsa2_sign(private_key, sign_content(params))}


def verify_notify(public_key: RSAPublicKey, params: dict[str, str]) -> bool:
    sign = params.get("sign", "")
    if not sign or params.get("sign_type", "RSA2") != "RSA2":
        return False
    return rsa2_verify(public_key, sign_content(params, drop=("sign", "sign_type")), sign)


def response_key(method: str) -> str:
    return method.replace(".", "_") + "_response"


def extract_response(text: str, method: str) -> tuple[str, str]:
    """从应答原文里截出「xxx_response」那一段的原文和 sign。截不出来抛 ValueError。"""
    key = f'"{response_key(method)}"'
    i = text.find(key)
    if i < 0:
        key = '"error_response"'
        i = text.find(key)
        if i < 0:
            raise ValueError("应答里没有 _response 段")
    start = text.index(":", i + len(key)) + 1
    while text[start] in " \t\r\n":
        start += 1
    _, end = json.JSONDecoder().raw_decode(text, start)
    raw = text[start:end]
    sign = json.loads(text).get("sign", "")
    return raw, sign


def verify_response(public_key: RSAPublicKey, text: str, method: str) -> tuple[bool, dict[str, Any]]:
    """验同步应答。返回（签名对不对，response 段解析后的字典）。"""
    raw, sign = extract_response(text, method)
    body = json.loads(raw)
    if not sign:
        return False, body
    return rsa2_verify(public_key, raw, sign), body


def signed_response(private_key: RSAPrivateKey, method: str, body: dict[str, Any]) -> str:
    """按支付宝的格式造一段带签名的应答原文（测试里假装是支付宝）。"""
    raw = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    return '{"' + response_key(method) + '":' + raw + ',"sign":"' + rsa2_sign(private_key, raw) + '"}'
