"""保险：这一包的测试里工厂 inbox 指临时目录、不读真密钥（支付配置全由测试现给，密钥是测试里现生成的）。"""

import pytest


@pytest.fixture(autouse=True)
def _isolate_env(tmp_path, monkeypatch):
    monkeypatch.setenv("FACTORY_INBOX", str(tmp_path / "inbox-env"))
    monkeypatch.setenv("FACTORY_JOBS", str(tmp_path / "jobs-env"))
    monkeypatch.setenv("PAY_QR_IMAGE", "")
    monkeypatch.setenv("LLM_API_KEY", "")
    for k in ("WECHATPAY_PRIVATE_KEY_PATH", "WECHATPAY_PUBLIC_KEY_PATH", "WECHATPAY_APIV3_KEY", "ALIPAY_PRIVATE_KEY_PATH",
              "ALIPAY_PUBLIC_KEY_PATH", "SHOP_METHODS", "SHOP_FAKE_PAY"):
        monkeypatch.delenv(k, raising=False)
