"""假订单闭环（假企业微信、假模型；入口设计第十节验收 3、4、5）：
付款建单 → 兑换页显示没认领 → 微信带码进会话 → 认领 + 一条欢迎语（含清单）→ 客人发材料和信息 → 资料齐 → 开工（制作中）；
网页同一条：兑换页「留在网页做」→ 聊天第一条是清单 → 传文件 → 收资料；
合并：网页认领后同一枚码从微信进 → 同一个客户，第二单的情况里有【老客户记得的】。"""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.channels.dispatch import dispatch_approved
from app.channels.runtime import get_channels
from app.channels.wecom import sync_messages
from app.intake import clock
from app.intake.bot import take_snapshot
from app.intake.models import Customer, Order
from app.intake.worker import run_due_jobs
from tests.channels.entry_helpers import enable_wecom, entry_app, paid_code, pool_code, wecom_settings
from tests.channels.fake_wecom import KFID, FakeWecom
from tests.intake.helpers import CONSENTS, PDF_BYTES, file_ids, scripted_model


def _script(prompt: str):
    ids = file_ids(prompt)
    day = (clock.today() + timedelta(days=7)).isoformat()
    calls = [("record_info", {"occasion": "组会文献", "duration_min": 15, "present_date": day})]
    calls += [("register_file", {"file_id": i, "purpose": "论文"}) for i in ids]
    return calls, "收到，资料齐了我就排期。"


def test_wecom_claim_to_making(tmp_path, notifier):
    fake = FakeWecom(page_size=10)
    app = entry_app(wecom_settings(tmp_path), notifier, tmp_path, wecom=fake, model=scripted_model(_script))
    enable_wecom(app)
    with TestClient(app) as c:
        rt = get_channels(app)
        with rt.intake.database.session() as db:
            code, oid = paid_code(db, rt.intake.ctx)
        v = c.get(f"/api/channels/redeem/{code}").json()
        assert v["state"] == "unclaimed" and [a["kind"] for a in v["actions"]] == ["claim_web", "link"]
        fake.enter_session("wm_e2e", "e1", scene_param=code, welcome_code="WCE")
        c.portal.call(sync_messages, rt, KFID, "")
        welcome = fake.events_sent[0]["text"]["content"]
        assert welcome.startswith("已对上你的订单") and "论文" in welcome and "讲几分钟" in welcome
        assert "/b/" in welcome and len(welcome.encode("utf-8")) <= 2048  # 09 需求引导：认领那句话后面接需求卡入口
        token = welcome.split("/b/", 1)[1].split()[0]
        with rt.intake.database.session() as db:
            assert db.get(Order, oid).stage == "claimed"
        fake.customer_sends_file("wm_e2e", "MEDIA_PDF", "m1")
        fake.customer_says("wm_e2e", "组会文献汇报，讲 15 分钟，下周汇报", "m2")
        c.portal.call(sync_messages, rt, KFID, "")
        assert "/media/get" in fake.calls  # 认领后才下载文件
        c.portal.call(run_due_jobs, rt.intake)
        with rt.intake.database.session() as db:
            assert db.get(Order, oid).stage == "collecting"  # 资料齐了，需求卡没确认：不开工
        # 客人在微信里点开需求卡：全部按推荐，勾三项同意（平台单下单时没勾过），点「对，开工」
        v = c.get(f"/api/channels/brief/{token}").json()
        assert v["state"] == "open" and v["chat_path"] == ""  # 微信里打开：没有网页聊天地址
        answers = {q["key"]: {"choice": "__default__"} for q in v["settings"]["questions"] if not q["optional"]}
        v = c.put(f"/api/channels/brief/{token}", json={"answers": answers}).json()
        assert v["consent_needed"] is True
        v = c.post(f"/api/channels/brief/{token}/confirm", json={"version": v["version"], **CONSENTS}).json()
        assert v["state"] == "confirmed" and v["next"]["where"] == "回到微信客服里发给助手"
        with rt.intake.database.session() as db:
            o = db.get(Order, oid)
            assert o.stage == "making", (o.stage, o.flow_step)
            assert o.wechat_external_userid == "wm_e2e"
        c.portal.call(dispatch_approved, rt)
        assert any(s["touser"] == "wm_e2e" for s in fake.sent)


def test_web_redeem_to_collecting_and_memory_across_doors(tmp_path, notifier):
    fake = FakeWecom(page_size=10)
    app = entry_app(wecom_settings(tmp_path), notifier, tmp_path, wecom=fake, model=scripted_model(_script))
    enable_wecom(app)
    with TestClient(app) as c:
        rt = get_channels(app)
        with rt.intake.database.session() as db:
            code = pool_code(db)
        key = c.post(f"/api/channels/redeem/{code}/web", json={}).json()["key"]
        first = c.get(f"/api/channels/web/{key}").json()["messages"][0]["text"]
        assert first.startswith("已对上你的订单") and "资料齐了才开工" in first
        up = c.post(f"/api/channels/web/{key}/files", files={"file": ("论文.pdf", PDF_BYTES, "application/pdf")})
        assert up.status_code == 200
        assert c.get(f"/api/channels/web/{key}").json()["status"] in ("收资料", "已认领")
        # 同一枚码从微信进：同一个客户（两个门），微信里也看得到这单
        fake.enter_session("wm_same", "e9", scene_param=code, welcome_code="WCS")
        c.portal.call(sync_messages, rt, KFID, "")
        assert fake.events_sent[-1]["text"]["content"].startswith("这单已经在你这里了")
        with rt.intake.database.session() as db:
            web = db.scalar(select(Customer).where(Customer.external_id == key))
            wx = db.scalar(select(Customer).where(Customer.external_id == "wm_same"))
            assert web.person_id == wx.person_id is not None
            # 上一单做完了 → 下一单在微信开口时，助手的情况里有【老客户记得的】
            o = db.scalar(select(Order).where(Order.customer_id == web.id))
            o.stage, o.school, o.title = "delivered", "华中师范大学", "情绪调节"
            o.finished_at = clock.local_now().astimezone() - timedelta(days=20)
            from app.channels import memory

            memory.refresh(db, web.person_id)
            code2 = pool_code(db)
        fake.customer_says("wm_same", f"又买了一单 {code2}", "m5")
        c.portal.call(sync_messages, rt, KFID, "")
        with rt.intake.database.session() as db:
            wx = db.scalar(select(Customer).where(Customer.external_id == "wm_same"))
            assert "华中师范大学" in wx.memory_brief
            wx.bot_seen_msg_id = 0
            snap = take_snapshot(db, rt.intake.ctx, wx)
            assert "【老客户记得的】" in snap.situation and "华中师范大学" in snap.situation
