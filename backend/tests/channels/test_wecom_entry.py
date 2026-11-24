"""微信客服入口（假企业微信，不连真接口）：回调只入队（C3）、只在会话状态 0/1 发（C4）、欢迎语不调模型且按时（C5）、
带码链接合法（C11）、进入事件重放只认领一次（C2 的一部分）、开关关着不入队。"""

from __future__ import annotations

import time
from urllib.parse import quote

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from wechatpy.enterprise.crypto import WeChatCrypto

from app.channels.dispatch import dispatch_approved
from app.channels.models import WecomCursor, WecomInbox
from app.channels.nodes.entry_wecom import resume_link
from app.channels.runtime import get_channels
from app.channels.wecom import sync_messages
from app.channels.wecom_inbox import process_inbox
from app.intake.models import BotRun, CodeRedemption, Customer, Outbox
from tests.channels.entry_helpers import CountingModel, enable_wecom, entry_app, pool_code, set_entry, wecom_settings
from tests.channels.fake_wecom import CORPID, KFID, FakeWecom


def _post_kf_event(c, crypto: WeChatCrypto):
    import xmltodict
    from wechatpy.utils import to_text

    xml = (f"<xml><ToUserName><![CDATA[{CORPID}]]></ToUserName><CreateTime>1348831860</CreateTime>"
           "<MsgType><![CDATA[event]]></MsgType><Event><![CDATA[kf_msg_or_event]]></Event>"
           f"<Token><![CDATA[ENCtoken]]></Token><OpenKfId><![CDATA[{KFID}]]></OpenKfId></xml>")
    enc = to_text(crypto.encrypt_message(xml, "1372623149", "1409659813"))
    d = xmltodict.parse(enc)["xml"]
    qs = {"msg_signature": d["MsgSignature"], "timestamp": d["TimeStamp"], "nonce": d["Nonce"]}
    t0 = time.monotonic()
    r = c.post("/api/channels/wecom/callback", params=qs, content=enc)
    return r, time.monotonic() - t0


def _app(tmp_path, notifier, fake, **kw):
    app = entry_app(wecom_settings(tmp_path), notifier, tmp_path, wecom=fake, **kw)
    return app


def _code(app):
    with get_channels(app).intake.database.session() as db:
        return pool_code(db)


def test_callback_only_enqueues_and_returns_fast(tmp_path, notifier):
    fake = FakeWecom(page_size=10)
    app = _app(tmp_path, notifier, fake)
    with TestClient(app) as c:
        rt = get_channels(app)
        r, took = _post_kf_event(c, rt.crypto)
        assert r.text == "success" and took < 1.0
        with rt.intake.database.session() as db:
            assert db.scalar(select(func.count()).select_from(WecomInbox)) == 0  # 开关关着：不入队
        enable_wecom(app)
        fake.customer_says("wm_q", "在吗", "m1")
        r, took = _post_kf_event(c, rt.crypto)
        assert r.text == "success" and took < 1.0
        assert "/kf/sync_msg" not in fake.calls  # 回调里一条都没拉
        with rt.intake.database.session() as db:
            assert db.scalar(select(func.count()).select_from(WecomInbox).where(WecomInbox.status == "pending")) == 1
        # 工人：第一次企业微信报错 → 退避重试；第二次成功
        fake.fail_sync = 1
        c.portal.call(process_inbox, rt)
        with rt.intake.database.session() as db:
            row = db.scalar(select(WecomInbox))
            assert row.status == "pending" and row.attempts == 1 and row.error
            row.run_after = row.received_at  # 到点了
        c.portal.call(process_inbox, rt)
        with rt.intake.database.session() as db:
            assert db.scalar(select(WecomInbox)).status == "done"
            assert db.scalar(select(Customer).where(Customer.external_id == "wm_q")) is not None
        # 连着失败 3 次：标失败、通知负责人
        fake.fail_sync = 5
        _post_kf_event(c, rt.crypto)
        for _ in range(3):
            with rt.intake.database.session() as db:
                for row in db.scalars(select(WecomInbox).where(WecomInbox.status == "pending")):
                    row.run_after = row.received_at
            c.portal.call(process_inbox, rt)
        with rt.intake.database.session() as db:
            assert db.scalar(select(func.count()).select_from(WecomInbox).where(WecomInbox.status == "failed")) == 1
        assert any("连着失败" in t for t in notifier.sent)


def test_welcome_without_model_and_in_time(tmp_path, notifier):
    fake = FakeWecom(page_size=10)
    model = CountingModel()
    app = _app(tmp_path, notifier, fake, model=model.model)
    enable_wecom(app)
    with TestClient(app) as c:
        code = _code(app)
        fake.enter_session("wm_new", "e1", scene_param=code, welcome_code="WC1")
        rt = get_channels(app)
        c.portal.call(sync_messages, rt, KFID, "")
        assert len(fake.events_sent) == 1 and fake.events_sent[0]["code"] == "WC1"
        text = fake.events_sent[0]["text"]["content"]
        assert text.startswith("已对上你的订单") and "资料齐了才开工" in text and len(text.encode()) <= 2048
        assert model.calls == 0
        with rt.intake.database.session() as db:
            assert db.scalar(select(func.count()).select_from(BotRun)) == 0  # 欢迎语全由代码拼，不调模型
            assert db.scalar(select(func.count()).select_from(CodeRedemption)) == 1
        # 进入事件重放（游标回退）：不再认领、不再发欢迎语
        with rt.intake.database.session() as db:
            db.get(WecomCursor, KFID).cursor = ""
        c.portal.call(sync_messages, rt, KFID, "")
        assert len(fake.events_sent) == 1
        with rt.intake.database.session() as db:
            assert db.scalar(select(func.count()).select_from(CodeRedemption)) == 1
        # 凭证过了时限（事件来晚了）：不用凭证，留在待发，客人一开口先补发
        code2 = _code(app)
        fake.enter_session("wm_late", "e2", scene_param=code2, welcome_code="WC2", send_time=int(time.time()) - 60)
        c.portal.call(sync_messages, rt, KFID, "")
        assert [e["code"] for e in fake.events_sent] == ["WC1"]
        c.portal.call(dispatch_approved, rt)
        with rt.intake.database.session() as db:
            late = db.scalar(select(Customer).where(Customer.external_id == "wm_late"))
            ob = db.scalar(select(Outbox).where(Outbox.customer_id == late.id))
            assert ob.status == "failed" and ob.error.startswith("客户最后一次说话已经超过 48 小时")
        fake.customer_says("wm_late", "你好", "m9", send_time=int(time.time()) + 1)
        c.portal.call(sync_messages, rt, KFID, "")
        c.portal.call(dispatch_approved, rt)
        assert any(s["touser"] == "wm_late" and s["text"]["content"].startswith("已对上你的订单") for s in fake.sent)


def test_send_only_when_state_allows(tmp_path, notifier):
    fake = FakeWecom(page_size=10)
    app = _app(tmp_path, notifier, fake)
    enable_wecom(app)
    fake.customer_says("wm_s", "在吗", "m1")
    with TestClient(app) as c:
        rt = get_channels(app)
        c.portal.call(sync_messages, rt, KFID, "")
        with rt.intake.database.session() as db:
            from app.intake import service

            cust = db.scalar(select(Customer).where(Customer.external_id == "wm_s"))
            ob = service.create_outbox(db, rt.intake.ctx, cust, None, text="你好", approved=True)
            oid = ob.id
        fake.service_state = 3  # 有人在企业微信里把会话转成了人工
        c.portal.call(dispatch_approved, rt)
        assert fake.sent == [] and "/kf/send_msg" not in fake.calls
        with rt.intake.database.session() as db:
            ob = db.get(Outbox, oid)
            assert ob.status == "failed" and ob.error.startswith("会话状态现在不能发")
        fake.service_state = 1  # 客人再开口：自动重排、能发
        fake.customer_says("wm_s", "还在吗", "m2", send_time=int(time.time()) + 1)
        c.portal.call(sync_messages, rt, KFID, "")
        c.portal.call(dispatch_approved, rt)
        assert [s["text"]["content"] for s in fake.sent] == ["你好"]
        # 开关关了：一条都不发
        set_entry(app, wecom_enabled=False)
        with rt.intake.database.session() as db:
            cust = db.scalar(select(Customer).where(Customer.external_id == "wm_s"))
            ob = service.create_outbox(db, rt.intake.ctx, cust, None, text="再来一句", approved=True)
            oid = ob.id
        c.portal.call(dispatch_approved, rt)
        with rt.intake.database.session() as db:
            assert "开关" in db.get(Outbox, oid).error
        assert len(fake.sent) == 1


def test_resume_link_is_valid(tmp_path, notifier, settings):
    import re

    app = entry_app(settings, notifier, tmp_path)
    link = "https://work.weixin.qq.com/kf/kfcABC?enc_scene=ENCxyz"
    set_entry(app, wecom_enabled=True, wecom_links={"redeem": link})
    with TestClient(app):
        rt = get_channels(app)
        with rt.intake.database.session() as db:
            code = pool_code(db)
            url = resume_link(db, code)
        assert url.startswith(link + "&scene_param=")  # 原链接一个字不改，只在末尾拼
        param = url[len(link + "&scene_param="):]
        assert param == quote(code, safe="") and len(param.encode()) <= 128
        assert re.fullmatch(r"[0-9a-zA-Z_-]{1,32}", "redeem")
    # scene 不合规的存不进去
    import pytest
    from pydantic import ValidationError

    from app.channels.entry_config import EntryConfig

    with pytest.raises(ValidationError):
        EntryConfig(wecom_links={"有中文": link})
