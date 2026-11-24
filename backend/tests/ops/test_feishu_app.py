"""飞书应用机器人（Ruler）：选哪种发法、换令牌和缓存、私聊发富文本带后台链接、先脱敏、限频重试；
凭证（App Secret、令牌、接收人编号）不进日志、事件、后台接口。全部用假飞书，不连外网。
推不推、合并、每小时上限归通知策略，测试在 tests/test_notify_policy.py。"""

from __future__ import annotations

import json
import logging

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.events import Event
from app.core.notify import (SEND_PATH, TOKEN_PATH, FeishuAppClient, FeishuAppCredentials, FeishuAppNotifier, FeishuNotifier,
                             LogNotifier, build_notifier, read_app_file)
from app.ops.models_io import MessageLine, MessageSection, OpsMessage
from app.ops.runtime import get_ops
from app.ops.sender import build_sender
from app.ops.settings import OpsSettings
from tests.conftest import make_settings
from tests.ops.helpers import LogCapture, login, ops_app, write

APP_ID = "cli_test000000000000"
SECRET = "fake-app-secret-for-tests"  # 假的；真的是 32 位字母数字，规矩 4 会拦
RID = "oc_" + "0123456789abcdef" * 2
BASE = "https://psyppt.example.cn"


class FakeFeishu:
    """假的飞书开放平台：换令牌、发消息两个接口；记下每个请求。send_codes 依次决定每次发消息回什么（429 = HTTP 限频）。"""

    def __init__(self, send_codes: list[int] | None = None, expire: int = 7200, down: bool = False) -> None:
        self.requests: list[httpx.Request] = []
        self.send_codes = list(send_codes or [])
        self.expire = expire
        self.down = down
        self.issued = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.down:
            raise httpx.ConnectError("连不上", request=request)
        if request.url.path == TOKEN_PATH:
            body = json.loads(request.content)
            if (body.get("app_id"), body.get("app_secret")) != (APP_ID, SECRET):
                return httpx.Response(200, json={"code": 10015, "msg": "wrong app secret"})
            self.issued += 1
            return httpx.Response(200, json={"code": 0, "msg": "ok", "expire": self.expire,
                                             "tenant_access_token": f"t-{'g' * 32}{self.issued:04d}"})
        if request.url.path == SEND_PATH:
            code = self.send_codes.pop(0) if self.send_codes else 0
            if code == 429:
                return httpx.Response(429, headers={"x-ogw-ratelimit-reset": "1"},
                                      json={"code": 99991400, "msg": "request trigger frequency limit"})
            # 飞书出错时说明里可能带上接收人编号：原因里要抹掉
            return httpx.Response(200 if code == 0 else 400, json={"code": code, "msg": "success" if code == 0 else f"bad receive_id {RID}"})
        return httpx.Response(404)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)

    def sends(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path == SEND_PATH]

    def tokens(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path == TOKEN_PATH]


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.slept.append(s)
        self.t += s


def creds() -> FeishuAppCredentials:
    return FeishuAppCredentials(app_id=APP_ID, app_secret=SECRET, receive_id=RID, receive_id_type="chat_id")


def notifier_for(fake: FakeFeishu, clock: Clock | None = None) -> FeishuAppNotifier:
    clock = clock or Clock()
    client = FeishuAppClient(creds(), transport=fake.transport(), sleep=clock.sleep, clock=clock)
    return FeishuAppNotifier(client, base_url=BASE)


def app_file(tmp_path, name: str = "feishu_ruler.json", **over) -> str:
    data = {"app_id": APP_ID, "app_secret": SECRET, "receive_id": RID, "receive_id_type": "chat_id", **over}
    return str(write(tmp_path / "secrets" / name, json.dumps(data)))


def post_rows(req: httpx.Request) -> list[list[dict]]:
    body = json.loads(req.content)
    assert body["msg_type"] == "post"
    return json.loads(body["content"])["zh_cn"]["content"]


# ---------------------------------------------------------------- 选哪种

def test_build_notifier_prefers_app_file_then_webhook(tmp_path, caplog):
    f = app_file(tmp_path)
    hook = "https://example.invalid/hook"
    assert isinstance(build_notifier(make_settings(tmp_path, FEISHU_APP_FILE=f, FEISHU_WEBHOOK=hook)), FeishuAppNotifier)
    assert isinstance(build_notifier(make_settings(tmp_path, FEISHU_APP_FILE=f, FEISHU_WEBHOOK=hook, FEISHU_SENDER="webhook")),
                      FeishuNotifier)
    assert isinstance(build_notifier(make_settings(tmp_path, FEISHU_APP_FILE=f, FEISHU_SENDER="log")), LogNotifier)
    assert isinstance(build_notifier(make_settings(tmp_path, FEISHU_SENDER="app")), LogNotifier)  # 点名要应用机器人但没配：只写日志
    broken = write(tmp_path / "secrets" / "broken.json", json.dumps({"app_id": APP_ID, "receive_id": RID}))
    with caplog.at_level(logging.WARNING, logger="app.notify"):
        n = build_notifier(make_settings(tmp_path, FEISHU_APP_FILE=broken, FEISHU_WEBHOOK=hook))
    assert isinstance(n, FeishuNotifier)  # 凭证文件坏了：退回群机器人
    assert "缺：app_secret" in caplog.text and RID not in caplog.text
    assert read_app_file(tmp_path / "nope.json") is None
    assert read_app_file(app_file(tmp_path, "phone.json", receive_id_type="phone")) is None
    good = read_app_file(f)
    assert good is not None and good.receive_id_type == "chat_id" and good.api_base == "https://open.feishu.cn"
    assert SECRET not in repr(good) and RID not in repr(good)


# ---------------------------------------------------------------- 发出去长什么样

def test_feishu_app_sends_post_to_receiver_with_token():
    fake = FakeFeishu()
    n = notifier_for(fake)
    assert n.send("新客户 小王（网页聊天）：老师好", link="/admin/conversations/3") is True
    tok, send = fake.tokens()[0], fake.sends()[0]
    assert json.loads(tok.content) == {"app_id": APP_ID, "app_secret": SECRET}
    assert send.url.params["receive_id_type"] == "chat_id"
    assert send.headers["authorization"] == f"Bearer t-{'g' * 32}0001"
    body = json.loads(send.content)
    assert body["receive_id"] == RID and len(body["uuid"]) <= 50
    rows = post_rows(send)
    assert rows[0] == [{"tag": "text", "text": "新客户 小王（网页聊天）：老师好"}]
    assert rows[1] == [{"tag": "a", "text": "打开后台", "href": f"{BASE}/admin/conversations/3"}]


def test_feishu_app_message_redacted_with_admin_link():
    """规矩 19：走应用机器人的业务通知先脱敏（手机号、激活码全文、邮箱用户名、带令牌的网址），没给链接也带后台首页。"""
    fake = FakeFeishu()
    n = notifier_for(fake)
    n.send("新客户 网页客户7：我电话 13812345678，码 PSY-K7Q2M9XZ4，邮箱 lab@example.edu.cn，交付页 /d/abcDEF1234567890xyz", level="urgent")
    text = json.dumps(post_rows(fake.sends()[0]), ensure_ascii=False)
    for bad in ("13812345678", "PSY-K7Q2M9XZ4", "lab@", "abcDEF1234567890xyz"):
        assert bad not in text, bad
    assert "<手机号>" in text and "PSY-*******Z4" in text
    assert post_rows(fake.sends()[0])[1][0]["href"] == f"{BASE}/admin"


def test_feishu_app_ops_message_post_with_links():
    fake = FakeFeishu()
    n = notifier_for(fake)
    os_ = OpsSettings(_env_file=None, OPS_SENDER="auto")
    s = build_sender(os_, n)
    assert s.name == "feishu_app" and s.configured
    msg = OpsMessage(kind="alert", title="【要立刻处理】网站报错变多", level="urgent", sections=[MessageSection(title="发生了什么", lines=[
        MessageLine(text="近 10 分钟 5xx 占 12%，客人 13912345678 报的"), MessageLine(text="后台：", link=f"{BASE}/admin/ops")])])
    out = s.send(msg)
    assert out.delivered and out.sender == "feishu_app"
    post = json.loads(json.loads(fake.sends()[0].content)["content"])["zh_cn"]
    assert post["title"] == "【要立刻处理】网站报错变多"
    flat = json.dumps(post, ensure_ascii=False)
    assert "13912345678" not in flat and f"{BASE}/admin/ops" in flat
    assert build_sender(OpsSettings(_env_file=None, OPS_SENDER="feishu_app"), LogNotifier()).name == "log"


# ---------------------------------------------------------------- 令牌、限频、失败

def test_feishu_app_token_cached_refreshed_and_retried():
    fake, clock = FakeFeishu(), Clock()
    n = notifier_for(fake, clock)
    n.send("一", level="urgent")
    n.send("二", level="urgent")
    assert len(fake.tokens()) == 1 and len(fake.sends()) == 2  # 令牌缓存着用
    clock.t += 7200 - 600 + 1  # 到期前 10 分钟换新
    n.send("三", level="urgent")
    assert len(fake.tokens()) == 2
    fake.send_codes = [99991663]  # 飞书说令牌失效：换一个重试一次
    assert n.client.send("post", {"zh_cn": {"content": [[{"tag": "text", "text": "四"}]]}}) == (True, "")
    assert len(fake.tokens()) == 3
    ids = [json.loads(r.content)["uuid"] for r in fake.sends()[-2:]]
    assert ids[0] == ids[1]  # 重试是同一条（飞书按 uuid 去重，不会发两遍）


def test_feishu_app_rate_limit_retries_once_and_paces():
    fake, clock = FakeFeishu(send_codes=[429]), Clock()
    n = notifier_for(fake, clock)
    assert n.send("限频了等一下", level="urgent") is True
    assert 1.0 in clock.slept and len(fake.sends()) == 2
    clock.slept.clear()
    n.send("紧接着又一条", level="urgent")
    assert clock.slept and max(clock.slept) <= 0.25  # 两条之间至少隔 0.25 秒（同一会话 5 QPS，和 Hermes 共用）
    fake.send_codes = [429, 429]
    ok, why = n.client.send("post", {"zh_cn": {"content": [[{"tag": "text", "text": "x"}]]}})
    assert not ok and "99991400" in why


def test_feishu_app_failure_returns_false_not_raise(caplog):
    with caplog.at_level(logging.WARNING, logger="app.notify"):
        assert notifier_for(FakeFeishu(down=True)).send("连不上") is False
        assert notifier_for(FakeFeishu(send_codes=[230013])).send("不在可用范围") is False
    assert "ConnectError" in caplog.text and "230013" in caplog.text
    assert RID not in caplog.text and SECRET not in caplog.text
    bad = FeishuAppClient(FeishuAppCredentials(app_id=APP_ID, app_secret="bad-secret-xyz", receive_id=RID), transport=FakeFeishu().transport())
    ok, why = bad.send("text", {"text": "x"})
    assert not ok and "10015" in why and "bad-secret-xyz" not in why
    ok, why = notifier_for(FakeFeishu()).client.send("post", {"zh_cn": {"content": [[{"tag": "text", "text": "长" * 20000}]]}})
    assert not ok and "30 KB" in why


# ---------------------------------------------------------------- 凭证不外泄

def test_feishu_app_credentials_never_in_logs_or_events(settings, tmp_path, caplog):
    """规矩 19：App Secret、令牌、接收人编号不进日志、事件、后台接口；发送失败也只记飞书回的错误码。"""
    fake = FakeFeishu(send_codes=[230013])  # 第一次：飞书说不在可用范围（说明里带着接收人编号）
    s = make_settings(tmp_path, FEISHU_APP_FILE=app_file(tmp_path))
    n = build_notifier(s, transport=fake.transport())
    assert isinstance(n, FeishuAppNotifier)
    app = ops_app(s, n, OPS_SENDER="auto")
    with TestClient(app) as c, LogCapture() as cap, caplog.at_level(logging.DEBUG):
        login(c)
        st = c.get("/api/admin/ops/settings").json()
        assert st["sender"]["sender"] == "feishu_app" and st["sender"]["label"] == "飞书应用机器人（私聊）"
        assert "feishu_ruler.json" in st["sender"]["source"]
        r = c.post("/api/admin/ops/test-send")
        assert r.status_code == 502 and "230013" in r.json()["detail"]
        assert c.post("/api/admin/ops/test-send").status_code == 200
        assert "【试发】" in json.loads(json.loads(fake.sends()[-1].content)["content"])["zh_cn"]["title"]
        assert c.post("/api/admin/ops/report/send", json={}).status_code == 200
        n.send("小李 发来 1 条消息：你好", link="/admin/conversations/1", level="urgent", kind="客人消息", who="customer:1")
        ov = json.dumps(c.get("/api/admin/ops/overview").json(), ensure_ascii=False)
        with get_ops(app).database.session() as db:
            dumped = json.dumps([[e.type, e.content] for e in db.scalars(select(Event))], ensure_ascii=False)
    tokens = [f"t-{'g' * 32}{i:04d}" for i in range(1, fake.issued + 1)]
    assert tokens
    for where in (cap.text, caplog.text, dumped, json.dumps(st, ensure_ascii=False), ov):
        for bad in (SECRET, RID, *tokens):
            assert bad not in where
    assert "ops.send_failed" in dumped and "ops.sent" in dumped
