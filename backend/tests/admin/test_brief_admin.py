"""后台需求卡（/api/admin/brief，09 需求引导）：要登录；设置能改（选项、推荐值、样张），改坏了 400；
订单详情里看需求卡、确认卡、确认时间和方式；改了发回给客人重新确认（入口发话）；代确认必须写依据、留痕写明代确认。"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.intake import codes
from app.intake.models import Order, Outbox
from app.intake.runtime import get_runtime
from tests.conftest import TEST_PASSWORD
from tests.intake.helpers import give_consent, make_app


def _web_order(app, c) -> int:
    rt = get_runtime(app)
    with rt.database.session() as db:
        code = codes.generate_batch(db, sku="light-p1", count=1)[1][0].code
    r = c.post(f"/api/channels/redeem/{code}/web", json={}).json()
    with rt.database.session() as db:
        return db.scalar(select(Order.id).where(Order.delivery_token == r["brief_path"][3:]))


def test_brief_admin_settings_view_send_back_and_proxy(settings, notifier, tmp_path):
    app = make_app(settings, notifier, tmp_path)
    with TestClient(app) as c:
        assert c.get("/api/admin/brief/settings").status_code == 401
        oid = _web_order(app, c)
        c.post("/api/auth/login", json={"password": TEST_PASSWORD})
        # 设置：改一个选项的字和样张；推荐值写错 400
        s = c.get("/api/admin/brief/settings").json()["settings"]
        assert s["remind_after_hours"] == 2 and [x["key"] for x in s["style"]["samples"]] == ["n01", "n07", "n10", "n13"]
        s["questions"][0]["options"][0]["label"] = "组会（读文献）"
        s["style"]["samples"][0]["image"] = "/site-assets/v2/n02-960.webp"
        assert c.put("/api/admin/brief/settings", json={"settings": s}).status_code == 200
        bad = {**s, "questions": [{**s["questions"][0], "default": "nope"}, *s["questions"][1:]]}
        r = c.put("/api/admin/brief/settings", json={"settings": bad})
        assert r.status_code == 400 and "推荐值" in r.json()["detail"]
        # 订单详情里的需求卡：客人还没填
        v = c.get(f"/api/admin/brief/orders/{oid}").json()
        assert v["state"] == "open" and v["condition"] == {"ok": False, "detail": "客人还没填需求卡"}
        assert v["settings"]["questions"][0]["options"][0]["label"] == "组会（读文献）" and v["minutes"]["high"] == 15
        assert v["url"].endswith(f"/b/{v['url'].rsplit('/', 1)[1]}")
        # 负责人改了发回：客人那边收到一句话 + 链接，状态是 sent_back
        v = c.put(f"/api/admin/brief/orders/{oid}", json={"answers": {"minutes": {"choice": "10"}}, "note": "时长按你说的改成 10 分钟"}).json()
        assert v["state"] == "sent_back" and v["sent_back_note"] == "时长按你说的改成 10 分钟"
        rt = get_runtime(app)
        with rt.database.session() as db:
            texts = [ob.text for ob in db.scalars(select(Outbox).where(Outbox.order_id == oid))]
        assert any("按你说的改了需求卡（时长按你说的改成 10 分钟）" in t and "/b/" in t for t in texts)
        # 代确认：不写依据 422；写了 → 确认，方式是代确认，记录里写明
        assert c.post(f"/api/admin/brief/orders/{oid}/confirm", json={"note": ""}).status_code == 422
        give_consent(app, oid)  # 客人本人勾过同意，才能代确认
        v = c.post(f"/api/admin/brief/orders/{oid}/confirm", json={"note": "客人在聊天里说「行」"}).json()
        assert v["state"] == "confirmed" and v["confirm_method"] == "proxy" and v["confirmed_by"] == "edison"
        assert v["confirm_note"] == "客人在聊天里说「行」" and "时长：10 分钟" in v["card_text"]
        assert v["history"][0]["what"] == "负责人代确认" and v["history"][0]["who"] == "你"
        assert {h["what"] for h in v["history"]} >= {"发回给客人重新确认", "改了需求卡"}
        # 客人那边看到的是「负责人代你确认了」
        token = v["url"].rsplit("/", 1)[1]
        cv = c.get(f"/api/channels/brief/{token}").json()
        assert cv["state"] == "confirmed" and cv["confirm_method"] == "proxy"
