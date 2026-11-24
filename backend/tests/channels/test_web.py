"""网页聊天：开会话、发字、没认领不收文件（11-18 先认领再收资料）、发码当场认领、传文件、只看得到自己的、
待批的客户看不到、批了才出现。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.channels.dispatch import dispatch_approved
from app.channels.runtime import get_channels
from app.channels.settings import ChannelsSettings
from app.intake.config_store import load_config, save_config
from app.intake.models import Job, Outbox
from app.intake.runtime import get_runtime
from app.intake.worker import run_due_jobs
from tests.conftest import TEST_PASSWORD
from tests.intake.helpers import PDF_BYTES, file_ids, make_app, scripted_model


def _code(app, sku="regular-p1") -> str:
    from app.intake import codes

    with get_runtime(app).database.session() as db:
        return codes.generate_batch(db, sku=sku, count=1)[1][0].code


def _script(prompt):
    ids = file_ids(prompt)
    if ids:
        return [("register_file", {"file_id": i, "purpose": "论文"}) for i in ids], "收到论文啦"
    return [("record_info", {"occasion": "组会文献"})], "好滴，论文发我就行"


@pytest.fixture
def web(settings, notifier, tmp_path):
    app = make_app(settings, notifier, tmp_path, model=scripted_model(_script))
    with TestClient(app) as c:
        yield app, c


def test_session_text_file_and_visibility(web):
    app, c = web
    key = c.post("/api/channels/web/sessions").json()["key"]
    assert len(key) >= 24
    r = c.get(f"/api/channels/web/{key}").json()
    assert r["messages"] == [] and r["welcome"].startswith("同学你好呀，这里是 PsyEngine，我是 AI 助手小鱼") and r["status"] == ""
    # 接待机器人（12 设计第八节）：顶上一直挂着「回复由 AI 生成」；没有排着的回复就不显示「正在输入」
    assert "AI 生成" in r["notice"] and r["typing"] is False
    refused = c.post(f"/api/channels/web/{key}/files", files={"file": ("论文.pdf", PDF_BYTES, "application/pdf")})
    assert refused.status_code == 409 and "激活码" in refused.json()["detail"]  # 没认领不收资料

    m = c.post(f"/api/channels/web/{key}/messages", json={"text": f"组会汇报，下周三，码 {_code(app)}"}).json()
    assert m["sender"] == "me" and m["text"].startswith("组会汇报，下周三")
    assert c.get(f"/api/channels/web/{key}").json()["status"] == "已认领"  # 发码当场认领
    up = c.post(f"/api/channels/web/{key}/files", files={"file": ("论文.pdf", PDF_BYTES, "application/pdf")}).json()
    assert up["kind"] == "file" and up["file"]["name"] == "论文.pdf" and "storage" not in str(up)
    assert c.get(up["file"]["url"]).content == PDF_BYTES

    rt = get_runtime(app)
    c.portal.call(run_due_jobs, rt)
    c.portal.call(dispatch_approved, get_channels(app))  # 发件员（测试里关着，手动跑一圈）
    msgs = c.get(f"/api/channels/web/{key}").json()["messages"]
    # 认领那一刻系统发固定话术（认领结果 + 资料清单，entry.notice）；后面助手回一趟（接单 v2：回复直接发）
    assert [x["sender"] for x in msgs] == ["me", "bot", "me", "bot"]
    assert msgs[1]["text"].startswith("已对上你的订单") and "资料齐了才开工" in msgs[1]["text"]
    assert msgs[-1]["text"] == "收到论文啦" and msgs[-1]["card"] is None

    # 设置里打开「先给我看」的类别：机器人写好了要后台批了才出现
    with rt.database.session() as db:
        cfg = load_config(db)
        cfg.approval["一般回复"] = True
        save_config(db, cfg)
    c.post(f"/api/channels/web/{key}/messages", json={"text": "在吗"})
    c.portal.call(run_due_jobs, rt)
    c.portal.call(dispatch_approved, get_channels(app))
    msgs = c.get(f"/api/channels/web/{key}").json()["messages"]
    # 这一趟助手记下了场合（组会文献）：系统把这个场合要的资料原样发一遍（资料清单这一类没打开「先给我看」，直接发）；
    # 助手自己那句（一般回复）等后台批，客户还看不到
    assert msgs[-2]["sender"] == "me" and msgs[-1]["card"] == "materials" and "组会读文献要发这几样" in msgs[-1]["text"]
    assert "（收到了）" in msgs[-1]["text"] and all(x["text"] != "好滴，论文发我就行" for x in msgs)
    c.post("/api/auth/login", json={"password": TEST_PASSWORD})
    with rt.database.session() as db:
        ob = db.scalar(select(Outbox).where(Outbox.status == "pending"))
    assert c.post(f"/api/admin/intake/outbox/{ob.id}/approve", json={"text": "在的，大概讲几分钟？"}).json()["status"] == "sent"
    msgs = c.get(f"/api/channels/web/{key}").json()["messages"]
    assert msgs[-1]["sender"] == "bot" and msgs[-1]["text"] == "在的，大概讲几分钟？"


def test_other_key_cannot_see_or_download(web):
    app, c = web
    a = c.post("/api/channels/web/sessions").json()["key"]
    b = c.post("/api/channels/web/sessions").json()["key"]
    c.post(f"/api/channels/web/{a}/messages", json={"text": _code(app)})
    up = c.post(f"/api/channels/web/{a}/files", files={"file": ("a.pdf", PDF_BYTES, "application/pdf")}).json()
    assert c.get(f"/api/channels/web/{b}/files/{up['file']['id']}").status_code == 404
    assert c.get("/api/channels/web/short").status_code == 404
    assert c.get("/api/channels/web/" + "x" * 30).status_code == 404


def test_bad_type_and_too_big(settings, notifier, tmp_path):
    app = make_app(settings, notifier, tmp_path)
    app.state.channels_settings = ChannelsSettings(_env_file=None, CHANNELS_DISPATCH=False, WEB_UPLOAD_MAX_MB=1)
    with TestClient(app) as c:
        key = c.post("/api/channels/web/sessions").json()["key"]
        c.post(f"/api/channels/web/{key}/messages", json={"text": _code(app)})
        r = c.post(f"/api/channels/web/{key}/files", files={"file": ("run.exe", b"MZ", "application/octet-stream")})
        assert r.status_code == 400
        r = c.post(f"/api/channels/web/{key}/files", files={"file": ("big.pdf", b"0" * (1024 * 1024 + 10), "application/pdf")})
        assert r.status_code == 413
        assert c.post(f"/api/channels/web/{key}/messages", json={"text": ""}).status_code == 422


def test_message_queues_bot_job(web):
    app, c = web
    key = c.post("/api/channels/web/sessions").json()["key"]
    c.post(f"/api/channels/web/{key}/messages", json={"text": "在吗"})
    rt = get_runtime(app)
    with rt.database.session() as db:
        assert db.scalar(select(Job)).status == "pending"


def test_session_rate_limit(web):
    app, c = web
    from app.channels.web import SESSION_LIMIT_PER_HOUR

    codes = [c.post("/api/channels/web/sessions").status_code for _ in range(SESSION_LIMIT_PER_HOUR + 1)]
    assert codes[-1] == 429 and set(codes[:-1]) == {200}
