"""需求卡的客人页面（/api/channels/brief/*）和「2 小时没确认提醒一次」（09 需求引导）：
兑换页认领 → 需求卡全部按推荐 → 选样张 → 传旧材料 → 确认卡 → 对，开工 → 制作中；选项从设置来；不调模型。"""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.channels import brief_web
from app.channels.runtime import get_channels
from app.core.db import utcnow
from app.intake import brief, clock, service
from app.intake.models import FileRecord, Order, Outbox
from tests.channels.entry_helpers import CountingModel, entry_app, pool_code
from tests.intake.helpers import CONSENTS, PDF_BYTES


def _claim(c: TestClient, app) -> tuple[str, str, int]:
    rt = get_channels(app)
    with rt.intake.database.session() as db:
        code = pool_code(db)
    r = c.post(f"/api/channels/redeem/{code}/web", json={}).json()
    with rt.intake.database.session() as db:
        oid = db.scalar(select(Order.id).where(Order.delivery_token == r["brief_path"][3:]))
    return r["key"], r["brief_path"][3:], oid


def test_brief_page_all_default_to_making(tmp_path, notifier, settings):
    model = CountingModel()
    app = entry_app(settings, notifier, tmp_path, model=model.model)
    with TestClient(app) as c:
        key, token, oid = _claim(c, app)
        rt = get_channels(app)
        # 客人先在聊天里交了资料（助手记事实这一步直接写库，省掉模型）
        c.post(f"/api/channels/web/{key}/files", files={"file": ("paper.pdf", PDF_BYTES, "application/pdf")})
        with rt.intake.database.session() as db:
            o = db.get(Order, oid)
            db.scalar(select(FileRecord).where(FileRecord.order_id == oid)).purpose = "论文"
            service.update_order(db, rt.intake.ctx, o, {"occasion": "组会文献", "present_date": clock.today() + timedelta(days=8)})
            assert o.stage == "collecting"
        h = {"X-Web-Key": key}
        v = c.get(f"/api/channels/brief/{token}", headers=h).json()
        assert v["state"] == "open" and v["chat_path"] == f"/chat/{key}" and v["minutes"]["high"] == 25
        assert [q["key"] for q in v["settings"]["questions"]][:2] == ["occasion", "audience"]
        assert len(v["settings"]["style"]["samples"]) == 4 and v["settings"]["texts"]["confirm_label"] == "对，开工"
        # 一题一题按推荐（页面每点一下存一次）
        for q in v["settings"]["questions"]:
            v = c.put(f"/api/channels/brief/{token}", headers=h, json={"answers": {q["key"]: {"choice": "__default__"}}}).json()
        v = c.put(f"/api/channels/brief/{token}", headers=h, json={"answers": {"style": {"choice": "n07"}}}).json()
        v = c.post(f"/api/channels/brief/{token}/files", headers=h, data={"kind": "ref"},
                   files={"file": ("导师批注.png", b"\x89PNG....", "image/png")}).json()
        assert [f["name"] for f in v["files"]] == ["导师批注.png"] and not v["missing"]
        lines = {x["key"]: x["value"] for x in v["card"]}
        assert lines["style"] == "最像「色块标题，范式一步一格」" and lines["refs"].startswith("1 份")
        assert c.post(f"/api/channels/brief/{token}/confirm", headers=h, json={"version": 1, **CONSENTS}).status_code == 409  # 旧版本
        v = c.post(f"/api/channels/brief/{token}/confirm", headers=h, json={"version": v["version"], **CONSENTS}).json()
        assert v["state"] == "confirmed" and v["confirm_method"] == "customer" and "开工" in v["next"]["text"]
        with rt.intake.database.session() as db:
            assert db.get(Order, oid).stage == "making"
        chat = c.get(f"/api/channels/web/{key}").json()
        assert chat["brief"]["confirmed"] is True
        assert c.put(f"/api/channels/brief/{token}", json={"answers": {"audience": {"choice": "lab"}}}).status_code == 409
        assert model.calls == 0  # 这条链路不调模型


def test_brief_page_rejects_bad_input(tmp_path, notifier, settings):
    app = entry_app(settings, notifier, tmp_path)
    with TestClient(app) as c:
        _, token, _ = _claim(c, app)
        assert c.get("/api/channels/brief/not-a-token").status_code == 404
        r = c.put(f"/api/channels/brief/{token}", json={"answers": {"minutes": {"choice": "40"}}})
        assert r.status_code == 400 and "最多 25 分钟" in r.json()["detail"]
        assert c.put(f"/api/channels/brief/{token}", json={"answers": {"occasion": {"choice": "party"}}}).status_code == 400
        r = c.post(f"/api/channels/brief/{token}/files", data={"kind": "ref"}, files={"file": ("a.exe", b"MZ", "application/x-msdownload")})
        assert r.status_code == 400
        r = c.post(f"/api/channels/brief/{token}/confirm", json={})  # 平台单：三项同意没勾，后端不让确认
        assert r.status_code == 422 and "开工前还要勾上" in r.json()["detail"] and "境外" in r.json()["detail"]
        r = c.post(f"/api/channels/brief/{token}/confirm", json={**CONSENTS, "consents": ["terms_privacy", "custom_no_refund"]})
        assert r.status_code == 422 and "AI" in r.json()["detail"]  # 出境那项单独要勾
        r = c.post(f"/api/channels/brief/{token}/confirm", json=CONSENTS)
        assert r.status_code == 409 and "还有没选的" in r.json()["detail"]
        assert c.get(f"/api/channels/brief/{token}").json()["consent_needed"] is True  # 确认没成，勾选也一起回滚


def test_remind_once_after_two_hours(tmp_path, notifier, settings):
    """认领 2 小时没确认：入口发一次提醒（带需求卡链接）、告诉负责人；再跑不重发；不开工。"""
    app = entry_app(settings, notifier, tmp_path)
    with TestClient(app) as c:
        key, token, oid = _claim(c, app)
        rt = get_channels(app)
        assert brief_web.remind_tick(rt) == []
        with rt.intake.database.session() as db:
            db.get(Order, oid).claimed_at = utcnow() - timedelta(hours=2, minutes=5)
        assert brief_web.remind_tick(rt) == [oid]
        assert brief_web.remind_tick(rt) == []
        with rt.intake.database.session() as db:
            texts = [ob.text for ob in db.scalars(select(Outbox).where(Outbox.order_id == oid))]
            assert any("需求确认卡还没确认" in t and f"/b/{token}" in t for t in texts)
            assert db.get(Order, oid).stage == "claimed"
            assert brief.get(db, db.get(Order, oid)).reminded_at is not None
        assert any("还没确认需求卡" in m for m in notifier.sent)


def test_all_default_in_one_go(tmp_path, notifier, settings):
    """第一题上方「全部按推荐」：一次存下所有题（可选的、样张也算）都按推荐 → 确认卡每行标「按推荐」、能确认；后台看到的一样。"""
    app = entry_app(settings, notifier, tmp_path)
    with TestClient(app) as c:
        _, token, oid = _claim(c, app)
        v = c.get(f"/api/channels/brief/{token}").json()
        assert v["settings"]["texts"]["all_default_label"] == "全部按推荐，直接看确认卡"
        answers = {q["key"]: {"choice": "__default__"} for q in v["settings"]["questions"]} | {"style": {"choice": "__default__"}}
        v = c.put(f"/api/channels/brief/{token}", json={"answers": answers}).json()
        assert not v["missing"] and all(x["by_default"] for x in v["card"] if x["key"] != "refs")
        assert all("（按推荐" in x["value"] for x in v["card"] if x["key"] != "refs")
        v = c.post(f"/api/channels/brief/{token}/confirm", json={"version": v["version"], **CONSENTS}).json()
        assert v["state"] == "confirmed"
        rt = get_channels(app)
        with rt.intake.database.session() as db:
            assert "听众：导师和同门（按推荐）" in brief.get(db, db.get(Order, oid)).card_text
