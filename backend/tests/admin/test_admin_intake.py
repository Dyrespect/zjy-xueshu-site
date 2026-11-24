"""后台接单接口：要登录；会话页（访客 / 有单）；订单卡按流程手动推一步、非法推进 409；手动开单；上传成品 → 交这一版 →
平台已完成 → 发最终版；作废两种；设置（新价目）能改、对外文字过红线词表、改价记事件；从工厂选成品只读。"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.events import Event
from app.intake import clock, codes, orders, service
from app.intake.adapters import PaidIn
from app.intake.models import Order
from app.intake.runtime import get_runtime
from app.intake.worker import run_due_jobs
from tests.conftest import TEST_PASSWORD
from tests.intake.helpers import CONSENTS, PDF_BYTES, file_ids, give_consent, make_app, png, pptx_bytes, scripted_model


def _script(prompt):
    if "还没有订单" in prompt:
        return [], "先把激活码发我哦"
    ids = file_ids(prompt)
    calls = [("record_info", {"occasion": "组会文献", "duration_min": 15, "paper_count": 1,
                              "present_date": (clock.today() + timedelta(days=6)).isoformat()})]
    calls += [("register_file", {"file_id": i, "purpose": "论文"}) for i in ids]
    return calls, "收到啦，论文、15 分钟、汇报日都记下了"


@pytest.fixture
def env(settings, notifier, tmp_path):
    jobs = tmp_path / "jobs" / "2026-11-15_组会文献_何小懒_AI采用" / "成品"
    jobs.mkdir(parents=True)
    (jobs / "deck.pptx").write_bytes(pptx_bytes(2))
    (jobs / "讲稿.md").write_text("讲稿", encoding="utf-8")
    app = make_app(settings, notifier, tmp_path, model=scripted_model(_script))
    with TestClient(app) as c:
        yield app, c, tmp_path


def _code(app, sku="regular-p1") -> str:
    rt = get_runtime(app)
    with rt.database.session() as db:
        return codes.generate_batch(db, sku=sku, count=1)[1][0].code


def _claimed_web_customer(app, c, *, claim=True):
    key = c.post("/api/channels/web/sessions").json()["key"]
    text = f"组会汇报，讲 15 分钟，码 {_code(app)}" if claim else "组会汇报，讲 15 分钟，多少钱"
    c.post(f"/api/channels/web/{key}/messages", json={"text": text})
    c.portal.call(run_due_jobs, get_runtime(app))
    return key


def _confirm_brief_on_page(app, c, key: str) -> dict:
    """客人在需求卡页面上全部选「按推荐」、点「对，开工」（09 需求引导）。"""
    from sqlalchemy import select

    from app.intake.models import Customer, Order

    rt = get_runtime(app)
    with rt.database.session() as db:
        cust = db.scalar(select(Customer).where(Customer.external_id == key))
        token = db.scalar(select(Order.delivery_token).where(Order.customer_id == cust.id))
    v = c.get(f"/api/channels/brief/{token}").json()
    answers = {q["key"]: {"choice": "__default__"} for q in v["settings"]["questions"] if not q["optional"]}
    v = c.put(f"/api/channels/brief/{token}", json={"answers": answers}).json()
    return c.post(f"/api/channels/brief/{token}/confirm", json={"version": v["version"], **CONSENTS}).json()


def test_requires_login(env):
    app, c, _ = env
    for path in ("/api/admin/intake/conversations", "/api/admin/intake/orders", "/api/admin/intake/settings", "/api/admin/nodes"):
        assert c.get(path).status_code == 401


def test_conversation_page_visitor_and_order(env):
    app, c, _ = env
    key = _claimed_web_customer(app, c)
    c.post(f"/api/channels/web/{key}/files", files={"file": ("SMJ-2026-Alekseeva.pdf", PDF_BYTES, "application/pdf")})
    c.portal.call(run_due_jobs, get_runtime(app))
    assert _confirm_brief_on_page(app, c, key)["state"] == "confirmed"
    _claimed_web_customer(app, c, claim=False)
    c.post("/api/auth/login", json={"password": TEST_PASSWORD})
    rows = c.get("/api/admin/intake/conversations").json()
    assert {r["status_label"] for r in rows} >= {"访客（没认领）", "制作中"}
    mine = next(r for r in rows if r["status_label"] == "制作中")
    d = c.get(f"/api/admin/intake/conversations/{mine['id']}").json()
    o = d["order"]
    assert o["sku_name"] == "常规 · 1 篇" and o["max_pages"] == 30 and o["platform"] == "fk" and o["code"].startswith("PSY-")
    assert [s["label"] for s in o["stage_track"]][:3] == ["已付款", "已认领", "收资料"] and o["stage"] == "making"
    assert o["can_void"] and not o["can_return_code"]  # 开工了：只能退款作废，码不能退回
    assert o["required"] == [{"purpose": "论文", "ok": True}] and d["bot_ready"] is True
    assert {b["sku"] for b in d["base_skus"]} >= {"light-p1", "regular-p2_3"}
    visitor = next(r for r in rows if r["status_label"] == "访客（没认领）")
    assert c.get(f"/api/admin/intake/conversations/{visitor['id']}").json()["order"] is None


def test_manual_order_push_package_confirm_and_illegal(env):
    app, c, tmp = env
    key = _claimed_web_customer(app, c, claim=False)
    c.post("/api/auth/login", json={"password": TEST_PASSWORD})
    cid = c.get("/api/admin/intake/conversations").json()[0]["id"]
    c.patch(f"/api/admin/intake/conversations/{cid}", json={"nickname": "何小懒"})
    o = c.post(f"/api/admin/intake/conversations/{cid}/manual-order", json={"sku": "regular-p1", "why": "师妹"}).json()
    assert (o["platform"], o["stage"]) == ("manual", "claimed")
    assert c.post(f"/api/admin/intake/conversations/{cid}/manual-order", json={"sku": "regular-p1"}).status_code == 409
    oid = o["id"]
    assert c.post(f"/api/admin/intake/orders/{oid}/push", json={"on": "start_now"}).status_code == 409  # 已认领这步没有这条
    r = c.patch(f"/api/admin/intake/orders/{oid}", json={"occasion": "组会文献", "school": "厦门大学", "page_count": 25,
                                                         "requirement_quotes": ["需要有厦大管理学院的logo"]})
    assert r.json()["school"] == "厦门大学" and r.json()["stage"] == "collecting"
    assert [m["on"] for m in r.json()["manual"]] == ["start_now"]
    bad = c.post(f"/api/admin/intake/orders/{oid}/push", json={"on": "start_now"})  # 09 需求引导：需求卡没确认，现在开工也不行
    assert bad.status_code == 409 and "需求卡还没确认" in bad.json()["detail"]
    nc = c.post(f"/api/admin/brief/orders/{oid}/confirm", json={"note": "师妹在微信里说按你们的来"})
    assert nc.status_code == 409 and "本人单独同意" in nc.json()["detail"]  # 客人没勾过同意（含出境）：不能代确认
    give_consent(app, oid)  # 客人在确认卡上勾了三项
    pb = c.post(f"/api/admin/brief/orders/{oid}/confirm", json={"note": "师妹在微信里说按你们的来"}).json()  # 代客人确认
    assert pb["state"] == "confirmed" and pb["confirm_method"] == "proxy" and pb["history"][0]["what"] == "负责人代确认"
    r = c.post(f"/api/admin/intake/orders/{oid}/push", json={"on": "start_now"}).json()
    assert r["stage"] == "making" and r["handoff_folder"] == "何小懒"
    req = (tmp / "inbox" / "何小懒" / "要求.md").read_text(encoding="utf-8")
    assert "负责人代确认（依据：师妹在微信里说按你们的来）" in req
    assert "需要有厦大管理学院的logo" in (tmp / "inbox" / "何小懒" / "要求.md").read_text(encoding="utf-8")
    assert c.post(f"/api/admin/intake/orders/{oid}/push", json={"on": "completed"}).status_code == 409
    jobs = c.get("/api/admin/intake/factory-jobs").json()
    r = c.post(f"/api/admin/intake/orders/{oid}/deliverables/from-factory",
               json={"job": jobs[0]["job"], "filename": "deck.pptx", "kind": "PPT"}).json()
    assert r["has_new_deliverable"] and r["can_submit_package"]
    c.post(f"/api/admin/intake/orders/{oid}/deliverables/from-factory",
           json={"job": jobs[0]["job"], "filename": "讲稿.md", "kind": "讲稿"})  # 模块 E：讲稿也是必交的最终版
    bad = c.post(f"/api/admin/intake/orders/{oid}/deliver")
    assert bad.status_code == 409 and "整页图" in bad.json()["detail"]
    small = c.post(f"/api/admin/intake/orders/{oid}/deliverables", files={"file": ("p1.png", png(600, 400), "image/png")},
                   data={"kind": "页图"})
    assert small.status_code == 400
    for i in (1, 2):
        c.post(f"/api/admin/intake/orders/{oid}/deliverables", files={"file": (f"page-{i}.png", png(), "image/png")}, data={"kind": "页图"})
    r = c.post(f"/api/admin/intake/orders/{oid}/deliver").json()
    assert r["stage"] == "watermarked" and r["pages"] == 0 and r["delivery_round"] == 1
    msgs = c.get(f"/api/channels/web/{key}").json()["messages"]
    assert any("先给你看" in m["text"] for m in msgs) and not any(m["kind"] == "file" and m["sender"] == "bot" for m in msgs)
    assert [m["on"] for m in r["manual"]] == ["completed"]
    r = c.post(f"/api/admin/intake/orders/{oid}/confirm").json()  # 你在平台后台看到确认收货了
    assert r["stage"] == "delivered" and r["finished_at"]
    msgs = c.get(f"/api/channels/web/{key}").json()["messages"]
    assert {m["file"]["name"] for m in msgs if m["kind"] == "file" and m["sender"] == "bot"} == {"deck.pptx", "讲稿.md"}
    v = c.post(f"/api/admin/intake/orders/{oid}/void", json={"code_action": "void"})
    assert v.status_code == 409 and "平台售后" in v.json()["detail"]


def test_void_endpoint_and_orders_list_with_unclaimed_paid(env):
    app, c, _ = env
    rt = get_runtime(app)
    with rt.database.session() as db:
        r = orders.receive_paid(db, rt.ctx, PaidIn(platform="xy", platform_order_id="XY9", sku="long-p2_3"), by="test")
        paid_id = r.order.id
    key = _claimed_web_customer(app, c)
    c.post("/api/auth/login", json={"password": TEST_PASSWORD})
    rows = c.get("/api/admin/intake/orders").json()
    paid = next(x for x in rows if x["id"] == paid_id)
    assert paid["stage"] == "paid" and paid["customer_id"] is None and paid["sku_name"] == "长 · 2–3 篇" and "XY9" in paid["name"]
    cid = c.get("/api/admin/intake/conversations").json()[0]["id"]
    oid = c.get(f"/api/admin/intake/conversations/{cid}").json()["order"]["id"]
    r = c.post(f"/api/admin/intake/orders/{oid}/void", json={"code_action": "return", "why": "客户不做了"}).json()
    assert r["stage"] == "void" and r["void_reason"] == "return" and r["voided_from_label"] == "收资料"
    assert c.post(f"/api/admin/intake/orders/{oid}/void", json={"code_action": "void"}).status_code == 409


def test_edit_send_reject_and_edison_message(env):
    app, c, _ = env
    c.post("/api/auth/login", json={"password": TEST_PASSWORD})
    s = c.get("/api/admin/intake/settings").json()["config"]
    s["approval"]["一般回复"] = True
    assert c.put("/api/admin/intake/settings", json={"config": s}).status_code == 200
    key = _claimed_web_customer(app, c, claim=False)
    cid = c.get("/api/admin/intake/conversations").json()[0]["id"]
    ob = c.get(f"/api/admin/intake/conversations/{cid}").json()["outbox"][0]
    assert c.post(f"/api/admin/intake/outbox/{ob['id']}/reject").json()["status"] == "rejected"
    assert c.post(f"/api/admin/intake/outbox/{ob['id']}/approve", json={}).status_code == 409
    r = c.post(f"/api/admin/intake/conversations/{cid}/messages", json={"text": "同学你好，我是负责人"}).json()
    assert r["status"] == "sent"
    assert c.get(f"/api/channels/web/{key}").json()["messages"][-1]["sender"] == "edison"
    t = c.post(f"/api/admin/intake/conversations/{cid}/takeover", json={"on": True}).json()
    assert t == {"takeover": True, "note": ""}  # 只停助手，不转人工


def test_settings_roundtrip_validation_and_change_event(env):
    app, c, _ = env
    c.post("/api/auth/login", json={"password": TEST_PASSWORD})
    s = c.get("/api/admin/intake/settings").json()
    cfg = s["config"]
    assert [t["name"] for t in cfg["duration_tiers"]] == ["轻量", "常规", "长", "超长"]
    assert cfg["duration_tiers"][1]["prices"] == {"p1": "29.9", "p2_3": "39.9", "p4_5": "49.9"}
    assert "tiers" not in cfg and "prices_tbd" not in cfg and cfg["addons"][2]["price"] == "9.9"
    assert cfg["visitor_daily_limit"] == 20 and cfg["delivery"]["confirm_sources_by_platform"]["xy"] == ["edison"]
    assert "页图" in s["deliverable_kinds"] and s["price_hash"]
    assert s["payment_ready"] is False and s["wecom"]["corpid"] is False and s["model"]["configured"] is True
    cfg["daily_quota"] = 5
    cfg["duration_tiers"][1]["prices"]["p1"] = "27.9"
    cfg["payment"]["link"] = "https://fk.example.cn/buy"
    r = c.put("/api/admin/intake/settings", json={"config": cfg})
    assert r.status_code == 200 and r.json()["config"]["duration_tiers"][1]["prices"]["p1"] == "27.9"
    ev = c.get("/api/admin/intake/events").json()
    changed = next(e for e in ev if e["type"] == "intake.config_changed")
    assert changed["content"]["price_hash_before"] != changed["content"]["price_hash_after"]
    assert "duration_tiers" in changed["content"]["fields"] and "daily_quota" in changed["content"]["fields"]
    bad = {**cfg, "delivery_templates": {**cfg["delivery_templates"], "code_only": "激活码：{code}，加微信 abc 发资料"}}
    r = c.put("/api/admin/intake/settings", json={"config": bad})
    assert r.status_code == 422 and "微信" in str(r.json()["detail"])  # 发货内容不许导流（红线词表）
    bad = {**cfg, "duration_tiers": cfg["duration_tiers"] + [{**cfg["duration_tiers"][0]}]}
    assert c.put("/api/admin/intake/settings", json={"config": bad}).status_code == 422  # 档位代号重复
    bad = {**cfg, "duration_tiers": [{**cfg["duration_tiers"][0], "prices": {"p9": "1"}}]}
    assert c.put("/api/admin/intake/settings", json={"config": bad}).status_code == 422
    bad = {**cfg, "payment": {**cfg["payment"], "qr_image": "/nope/qr.png"}}
    assert c.put("/api/admin/intake/settings", json={"config": bad}).status_code == 400
    assert c.post("/api/admin/intake/wecom/contact-way", json={"scene": "gzh"}).status_code == 503


def test_needs_resolve_and_purpose_fix(env):
    app, c, _ = env
    key = _claimed_web_customer(app, c)
    c.post(f"/api/channels/web/{key}/files", files={"file": ("notes.pdf", PDF_BYTES, "application/pdf")})
    rt = get_runtime(app)
    c.post("/api/auth/login", json={"password": TEST_PASSWORD})
    cid = c.get("/api/admin/intake/conversations").json()[0]["id"]
    o = c.get(f"/api/admin/intake/conversations/{cid}").json()["order"]
    with rt.database.session() as db:
        service.add_need(db.get(Order, o["id"]), "价格", "问多少钱")
    assert c.post(f"/api/admin/intake/orders/{o['id']}/needs/0/resolve").json()["ok"]
    fid = o["materials"][0]["id"]
    r = c.post(f"/api/admin/intake/orders/{o['id']}/files/{fid}/purpose", json={"purpose": "材料"}).json()
    assert r["required"] == [{"purpose": "论文", "ok": False}] and r["stage"] == "collecting"
    assert r["needs"][0]["resolved"] is True and "论文" in r["progress"]
