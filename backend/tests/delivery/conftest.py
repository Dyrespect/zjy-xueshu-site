"""保险：这一包的测试里 FACTORY_INBOX 一律指临时目录（环境变量比 .env 优先），绝不碰真的工厂 inbox。"""

import pytest


@pytest.fixture(autouse=True)
def _factory_inbox_to_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv("FACTORY_INBOX", str(tmp_path / "inbox-env"))
    monkeypatch.setenv("FACTORY_JOBS", str(tmp_path / "jobs-env"))
    monkeypatch.setenv("PAY_QR_IMAGE", "")
    monkeypatch.setenv("LLM_API_KEY", "")


@pytest.fixture(autouse=True)
def _delivery_settings_reset():
    """交付设置是进程里一份（app 起来时配）：每个测试前后清掉，前一个测试改的不漏给后一个。"""
    from app.delivery import runtime

    runtime.reset()
    yield
    runtime.reset()


@pytest.fixture
def ctx(tmp_path, notifier):
    from tests.intake.helpers import make_ctx

    return make_ctx(tmp_path, notifier)
