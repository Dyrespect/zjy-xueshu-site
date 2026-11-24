"""兑换网页 /c/{CODE}：各种状态、留在网页做（当场认领、幂等）、不泄露（C10）、限流、微信按钮跟着开关走。"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.channels.runtime import get_channels
from app.channels.wecom import sync_messages
from app.intake.models import CodeRedemption, Customer
from app.intake.runtime import get_runtime
from tests.channels.entry_helpers import REDEEM_LINK, enable_wecom, entry_app, paid_code, pool_code, set_entry, wecom_settings
from tests.channels.fake_wecom import KFID, FakeWecom


def _codes(app, n: int = 1, **kw):
    with get_runtime(app).database.session() as db:
        return [pool_code(db, **kw) for _ in range(n)]


def test_redeem_states_and_web_claim(tmp_path, notifier, settings):
    app = entry_app(settings, notifier, tmp_path)
    with TestClient(app) as c:
        meta = c.get("/api/channels/redeem").json()
        assert meta["state"] == "invalid" and meta["buy"] and "PSY-" in meta["code_hint"]
        assert c.get("/api/channels/redeem/abc").json()["state"] == "invalid"
        assert c.get("/api/channels/redeem/PSY-ABCDEFGHJ").json()["state"] == "not_found"
        (code,) = _codes(app)
        v = c.get(f"/api/channels/redeem/{code.lower().replace('-', ' ')}").json()  # 大小写、空格都认
        assert v["state"] == "unclaimed" and v["sku_name"] == "常规 · 1 篇" and v["hours"] == 5 + 2  # 含余量
        assert [a["kind"] for a in v["actions"]] == ["claim_web"]  # 微信客服没开：第二个按钮不出现
        r = c.post(f"/api/channels/redeem/{code}/web", json={}).json()
        key = r["key"]
        assert r["chat_path"] == f"/chat/{key}" and r["brief_path"].startswith("/b/")  # 认领完先去需求卡（09 需求引导）
        chat = c.get(f"/api/channels/web/{key}").json()
        assert chat["order"]["sku_name"] == "常规 · 1 篇" and chat["status"] == "已认领"
        assert chat["messages"][0]["text"].startswith("已对上你的订单") and "资料齐了才开工" in chat["messages"][0]["text"]
        assert r["brief_path"] in chat["messages"][0]["text"] and chat["brief"] == {
            "path": r["brief_path"], "confirmed": False, "text": "需求确认卡还没确认，确认了才开工"}
        # 同一个浏览器再点：直接跳聊天，不重复认领、不重复发清单
        again = c.post(f"/api/channels/redeem/{code}/web", json={"key": key}).json()
        assert again["key"] == key
        assert len(c.get(f"/api/channels/web/{key}").json()["messages"]) == 1
        mine = c.get(f"/api/channels/redeem/{code}", headers={"X-Web-Key": key}).json()
        assert mine["state"] == "yours" and mine["progress"]
        assert [a["url"] for a in mine["actions"][:2]] == [r["brief_path"], f"/chat/{key}"] and mine["actions"][0]["primary"]
        stranger = c.get(f"/api/channels/brief/{r['brief_path'][3:]}").json()  # 转发出去的链接：拿不到聊天地址
        assert stranger["chat_path"] == "" and c.get(f"/api/channels/brief/{r['brief_path'][3:]}",
                                                     headers={"X-Web-Key": key}).json()["chat_path"] == f"/chat/{key}"
        # 作废的码
        rt = get_runtime(app)
        with rt.database.session() as db:
            from app.intake.models import ActivationCode

            (code2,) = [pool_code(db)]
            db.scalar(select(ActivationCode).where(ActivationCode.code == code2)).status = "void"
        assert c.get(f"/api/channels/redeem/{code2}").json()["state"] == "void"
        assert c.post(f"/api/channels/redeem/{code2}/web", json={}).status_code == 409
        # 加购码：没有在走的单不能用
        (addon,) = _codes(app, sku="addon-revision")
        assert c.get(f"/api/channels/redeem/{addon}").json()["state"] == "addon"
        assert c.post(f"/api/channels/redeem/{addon}/web", json={}).status_code == 409
        # 有在走的单：挂上去
        assert c.post(f"/api/channels/redeem/{addon}/web", json={"key": key}).status_code == 200
        with rt.database.session() as db:
            assert db.scalar(select(func.count()).select_from(CodeRedemption)) == 2


def test_redeem_page_no_leak_and_rate_limit(tmp_path, notifier, settings):
    app = entry_app(settings, notifier, tmp_path)
    with TestClient(app) as c:
        rt = get_runtime(app)
        with rt.database.session() as db:
            code, oid = paid_code(db, rt.ctx)
        key = c.post(f"/api/channels/redeem/{code}/web", json={}).json()["key"]
        other = c.post("/api/channels/web/sessions").json()["key"]
        v = c.get(f"/api/channels/redeem/{code}", headers={"X-Web-Key": other}).json()
        assert v["state"] == "taken"
        assert v["sku_name"] == "" and v["progress"] == "" and v["stage_label"] == "" and v["hours"] is None
        assert "order_id" not in v and key not in str(v)
        r = c.post(f"/api/channels/redeem/{code}/web", json={"key": other})
        assert r.status_code == 409 and "认领过了" in r.json()["detail"]
        # 同一 IP 一小时超了 → 429
        set_entry(app, redeem_ip_hourly=3)
        for _ in range(3):
            c.get("/api/channels/redeem/PSY-ABCDEFGHJ")
        assert c.get("/api/channels/redeem/PSY-ABCDEFGHJ").status_code == 429


def test_wecom_button_follows_switch_and_joinable(tmp_path, notifier):
    fake = FakeWecom(page_size=10)
    app = entry_app(wecom_settings(tmp_path), notifier, tmp_path, wecom=fake)
    with TestClient(app) as c:
        (code,) = _codes(app)
        assert [a["kind"] for a in c.get(f"/api/channels/redeem/{code}").json()["actions"]] == ["claim_web"]
        enable_wecom(app)
        acts = c.get(f"/api/channels/redeem/{code}").json()["actions"]
        assert [a["kind"] for a in acts] == ["claim_web", "link"]
        assert acts[1]["url"] == f"{REDEEM_LINK}&scene_param={code}" and acts[1]["hint"]
        # 码在微信里认领了（还没有网页门）→ 别的浏览器看到「在网页继续」，点了两个门并成一个人
        fake.enter_session("wm_a", "e1", scene_param=code, welcome_code="")
        rt = get_channels(app)
        c.portal.call(sync_messages, rt, KFID, "")
        v = c.get(f"/api/channels/redeem/{code}").json()
        assert v["state"] == "taken_joinable" and v["sku_name"] == ""
        key = c.post(f"/api/channels/redeem/{code}/web", json={}).json()["key"]
        with rt.intake.database.session() as db:
            web = db.scalar(select(Customer).where(Customer.external_id == key))
            wx = db.scalar(select(Customer).where(Customer.external_id == "wm_a"))
            assert web.person_id == wx.person_id is not None
        chat = c.get(f"/api/channels/web/{key}").json()
        assert chat["order"] is not None and chat["status"] == "已认领"  # 微信认领的单，网页里也看得到
        # 第三个浏览器：两个门都满了 → 只说认领过了
        assert c.get(f"/api/channels/redeem/{code}").json()["state"] == "taken"
