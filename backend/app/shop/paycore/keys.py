"""读 RSA 密钥：PEM 文件，或支付宝后台给的那种只有一行 base64 的（DER）。只在真要签名 / 验签时读，不在启动时读。"""

from __future__ import annotations

import base64
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey


class KeyError_(ValueError):
    pass


def _raw(data: bytes | str) -> bytes:
    return data.encode() if isinstance(data, str) else data


def load_private_key(data: bytes | str) -> RSAPrivateKey:
    raw = _raw(data).strip()
    try:
        key = (serialization.load_pem_private_key(raw, password=None) if raw.startswith(b"-----")
               else serialization.load_der_private_key(base64.b64decode(b"".join(raw.split())), password=None))
    except (ValueError, TypeError) as e:
        raise KeyError_(f"私钥读不出来：{e}") from e
    if not isinstance(key, RSAPrivateKey):
        raise KeyError_("私钥不是 RSA 的")
    return key


def load_public_key(data: bytes | str) -> RSAPublicKey:
    """公钥：PEM 公钥、PEM 证书，或一行 base64 的公钥。"""
    raw = _raw(data).strip()
    try:
        if raw.startswith(b"-----BEGIN CERTIFICATE"):
            key = x509.load_pem_x509_certificate(raw).public_key()
        elif raw.startswith(b"-----"):
            key = serialization.load_pem_public_key(raw)
        else:
            key = serialization.load_der_public_key(base64.b64decode(b"".join(raw.split())))
    except (ValueError, TypeError) as e:
        raise KeyError_(f"公钥读不出来：{e}") from e
    if not isinstance(key, RSAPublicKey):
        raise KeyError_("公钥不是 RSA 的")
    return key


def read_private_key(path: Path | None) -> RSAPrivateKey:
    if path is None or not Path(path).is_file():
        raise KeyError_("私钥文件没配或不存在")
    return load_private_key(Path(path).read_bytes())


def read_public_key(path: Path | None) -> RSAPublicKey:
    if path is None or not Path(path).is_file():
        raise KeyError_("公钥文件没配或不存在")
    return load_public_key(Path(path).read_bytes())
