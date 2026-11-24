"""日志：JSON 一行一条、请求号贯穿、访问日志只写路由模板、敏感字段打码；webhook 不进日志、事件、设置接口；日志样例干净。"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.events import Event
from app.core.redact import SENSITIVE_SAMPLE_PATTERNS, redact, redact_text
from app.ops.runtime import get_ops
from tests.ops.helpers import LogCapture, Recorder, fake_hook, login, ops_app, write

REPO = Path(__file__).resolve().parents[3]


def _load_sample_script():
    spec = importlib.util.spec_from_file_location("ops_log_sample", REPO / "scripts" / "ops_log_sample.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ops_log_sample"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_redact_patterns():
    s = redact_text("电话 138 1234 5678 / +86-13912345678，税号 91330110MA27XY1234，码 PSY-K7Q2M9XZ4，"
                    "Bearer abcdefghijkl12345，交付 /d/abcDEF123456789，邮箱 lab@example.edu.cn")
    for bad in ("1234 5678", "13912345678", "91330110MA27XY1234", "PSY-K7Q2M9XZ4", "abcdefghijkl12345", "abcDEF123456789", "lab@"):
        assert bad not in s, bad
    assert "PSY-*******Z4" in s and "@example.edu.cn" in s
    d = redact({"phone": "13800000000", "status_code": 200, "webhook_configured": True, "nested": {"token": "x", "n": 1}})
    assert d == {"phone": "***", "status_code": 200, "webhook_configured": True, "nested": {"token": "***", "n": 1}}


def test_request_id_through_access_log(settings, notifier):
    app = ops_app(settings, notifier)
    with TestClient(app, raise_server_exceptions=False) as c, LogCapture() as cap:
        r = c.get("/api/delivery/" + "t" * 30)
        rid = r.headers["x-request-id"]
        c.get("/api/_boom", headers={"x-request-id": "boom-request-01"})
    lines = cap.lines()
    access = [x for x in lines if x.get("logger") == "app.access"]
    first = next(x for x in access if x.get("rid") == rid)
    assert first["route"] == "/api/delivery/{token}" and "t" * 30 not in cap.text  # 只写路由模板，不写令牌
    boom = [x for x in lines if x.get("rid") == "boom-request-01"]
    assert any(x["level"] == "ERROR" and x.get("status") == 500 for x in boom)  # 同一个请求号把出错那几行串起来
    assert "13812345678" not in cap.text


def test_webhook_never_in_logs_or_events(settings, notifier, tmp_path):
    """规矩 19：webhook 地址不进日志、事件、库、后台接口；发送失败也只记飞书回的错误码。"""
    hook = fake_hook()
    token = hook.rsplit("/", 1)[-1]
    f = write(tmp_path / "secrets" / "feishu_ops_webhook", hook + "\nsign-secret-abc\n")
    rec = Recorder(feishu_code=19021)  # 第一次：飞书说签名不对
    app = ops_app(settings, notifier, recorder=rec, OPS_SENDER="auto", OPS_FEISHU_WEBHOOK_FILE=f)
    with TestClient(app) as c, LogCapture() as cap:
        login(c)
        st = c.get("/api/admin/ops/settings").json()
        assert st["sender"]["sender"] == "feishu_webhook" and st["sender"]["signed"] is True
        r = c.post("/api/admin/ops/test-send")
        assert r.status_code == 502 and "19021" in r.json()["detail"]
        rec.feishu_code = 0
        assert c.post("/api/admin/ops/test-send").status_code == 200
        body = rec.feishu_bodies()[-1]
        assert body["msg_type"] == "post" and body["sign"] and body["timestamp"]  # 开了签名校验就带签名
        assert c.post("/api/admin/ops/report/send", json={}).status_code == 200
        ov = json.dumps(c.get("/api/admin/ops/overview").json(), ensure_ascii=False)
        ctx = get_ops(app)
        with ctx.database.session() as db:
            dumped = json.dumps([[e.type, e.content] for e in db.scalars(select(Event))], ensure_ascii=False)
    for where in (cap.text, dumped, json.dumps(st, ensure_ascii=False), ov):
        assert token not in where and "sign-secret-abc" not in where
    assert "ops.send_failed" in dumped and "ops.sent" in dumped


def test_feishu_disabled_without_webhook(settings, notifier):
    app = ops_app(settings, notifier, OPS_SENDER="auto")  # 底座通知是 FakeNotifier（不是飞书）、没配 webhook：整块关掉
    with TestClient(app) as c:
        login(c)
        st = c.get("/api/admin/ops/settings").json()
        assert st["sender"]["configured"] is False
        r = c.post("/api/admin/ops/test-send")
        assert r.status_code == 409 and "OPS_FEISHU_WEBHOOK_FILE" in r.json()["detail"]
        assert c.post("/api/admin/ops/report/send", json={}).status_code == 409
        assert c.get("/api/admin/ops/report/preview").status_code == 200  # 预览照样能看


def test_log_sample_has_no_sensitive_fields(tmp_path):
    """规矩 19：用带敏感信息的假请求跑一遍，线上格式的日志里一个都不许出现；仓库里那份样例也要干净。"""
    mod = _load_sample_script()
    text = mod.generate(tmp_path / "sample.jsonl")
    assert len(text.splitlines()) >= 8 and all(json.loads(x) for x in text.splitlines())
    for name, pat in SENSITIVE_SAMPLE_PATTERNS.items():
        assert not pat.search(text), f"{name} 出现在日志里"
    for raw in (mod.PHONE, mod.TAX_ID, mod.CODE, mod.HOOK, "LongSecretToken"):
        assert raw not in text
    committed = REPO / "deploy" / "ops" / "日志样例.jsonl"
    assert committed.is_file()
    ctext = committed.read_text(encoding="utf-8")
    assert not any(p.search(ctext) for p in SENSITIVE_SAMPLE_PATTERNS.values())
