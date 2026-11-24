"""渠道与支付测试共用：建 app（假网关、定时任务关掉）、几种 User-Agent、现生成 RSA 密钥。不联网、不读 .env。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.shop.settings import ShopSettings
from tests.intake.helpers import make_app

PC_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
             "Version/17.0 Mobile/15E148 Safari/604.1")
WECHAT_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
             "Mobile/15E148 MicroMessenger/8.0.50(0x1800323c) NetType/WIFI Language/zh_CN")
FAKE_METHODS = "wechat_native=pay.fake,alipay_page=pay.fake,alipay_wap=pay.fake,wechat_jsapi=pay.fake"


def shop_settings(**over: Any) -> ShopSettings:
    values: dict[str, Any] = dict(SHOP_FAKE_PAY=True, SHOP_TIMER_ENABLED=False, SHOP_METHODS=FAKE_METHODS,
                                  SHOP_FAKE_SECRET="test-fake-secret-not-real", SHOP_IP_HOURLY_LIMIT=1000)
    values.update(over)
    return ShopSettings(_env_file=None, **values)


def make_shop_app(settings, notifier, tmp_path: Path, *, transports: dict | None = None, **shop_over: Any):
    app = make_app(settings, notifier, tmp_path)
    app.state.shop_settings = shop_settings(**shop_over)
    app.state.shop_transports = transports or {}
    return app


def new_rsa() -> tuple[rsa.RSAPrivateKey, bytes, bytes]:
    """现生成一对 RSA 2048 密钥：（私钥对象，私钥 PEM，公钥 PEM）。只在测试里用，用完就扔。"""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    pub = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    return key, priv, pub


CONSENTS = {"consents": ["terms_privacy", "ai_processing", "custom_no_refund"], "terms_version": "2026-11-18",
            "privacy_version": "2026-11-18"}


def checkout_body(**over: Any) -> dict[str, Any]:
    """下单的请求体：默认三项都勾了（后端没勾全不建单）。"""
    body: dict[str, Any] = {"tier": "regular", "band": "p2_3", "rush": False, "find_refs": False, "extra_revisions": 1,
                            "method": "wechat_native", **CONSENTS}
    body.update(over)
    return body
