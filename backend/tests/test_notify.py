import base64
import hashlib
import hmac
import json

import httpx

from app.core.notify import FakeNotifier, FeishuNotifier, LogNotifier, build_notifier
from tests.conftest import make_settings


def test_fake_notifier_records(client, notifier):
    assert client.app.state.notifier is notifier
    assert notifier.send("这单可以开工了") is True
    assert notifier.send("新客户", link="/admin/conversations/1") is True
    assert notifier.sent == ["这单可以开工了", "新客户"]
    assert notifier.links == ["", "/admin/conversations/1"]


async def test_fake_notifier_async():
    n = FakeNotifier()
    assert await n.asend("异步也行") is True
    assert n.sent == ["异步也行"]


def test_empty_webhook_only_logs(tmp_path, caplog):
    n = build_notifier(make_settings(tmp_path, FEISHU_WEBHOOK=""))
    assert isinstance(n, LogNotifier)
    with caplog.at_level("INFO", logger="app.notify"):
        assert n.send("只写日志") is True
    assert "只写日志" in caplog.text


def test_build_feishu_when_configured(tmp_path):
    n = build_notifier(make_settings(tmp_path, FEISHU_WEBHOOK="https://example.invalid/hook"))
    assert isinstance(n, FeishuNotifier)


def test_feishu_payload_and_sign():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"code": 0, "msg": "success"})

    n = FeishuNotifier("https://example.invalid/hook", "s3cr3t", transport=httpx.MockTransport(handler))
    assert n.send("开工") is True
    body = seen["body"]
    assert body["msg_type"] == "text" and body["content"]["text"] == "开工"
    ts = body["timestamp"]
    expect = base64.b64encode(
        hmac.new(f"{ts}\ns3cr3t".encode(), b"", digestmod=hashlib.sha256).digest()
    ).decode()
    assert body["sign"] == expect


def test_feishu_webhook_appends_admin_link():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"code": 0, "msg": "success"})

    n = FeishuNotifier("https://example.invalid/hook", base_url="https://psyppt.example.cn/", transport=httpx.MockTransport(handler))
    assert n.send("出图失败", link="/admin/orders") is True
    assert seen["body"]["content"]["text"] == "出图失败\n后台：https://psyppt.example.cn/admin/orders"


def test_feishu_failure_returns_false_not_raise():
    def bad(request):
        return httpx.Response(200, json={"code": 19021, "msg": "sign match fail"})

    def boom(request):
        raise httpx.ConnectError("连不上")

    assert FeishuNotifier("https://x.invalid", transport=httpx.MockTransport(bad)).send("a") is False
    assert FeishuNotifier("https://x.invalid", transport=httpx.MockTransport(boom)).send("a") is False
