"""微信客服：官方文档的加解密示例 + 假企业微信把整条链路测通（回调 → 拉消息 → 机器人 → 待发 → 批准 → send_msg）。"""

from __future__ import annotations

import time
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from wechatpy.enterprise.crypto import WeChatCrypto

from app.channels.dispatch import dispatch_approved
from app.channels.entry_config import EntryConfig, save_entry_config
from app.channels.models import WecomCursor, WecomInbox
from app.channels.wecom_inbox import process_inbox
from app.channels.runtime import get_channels
from app.channels.wecom import sync_messages
from app.core.db import utcnow
from app.intake import service
from app.intake.config_store import load_config, save_config
from app.intake.models import Customer, FileRecord, Message, Outbox
from app.intake.runtime import get_runtime
from app.intake.worker import run_due_jobs
from tests.channels.fake_wecom import CORPID, KFID, SECRET, FakeWecom
from tests.conftest import TEST_PASSWORD, make_settings
from tests.intake.helpers import file_ids, make_app, scripted_model

# 企业微信官方「加解密方案说明」里的示例（wechatpy 的测试也用这一组）
OFFICIAL_TOKEN = "QDG6eK"
OFFICIAL_AES = "jWmYm7qr5nMoAUwZRjGtBxmz3KA1tkAj3ykkR6q2B2C"
OFFICIAL_ECHO = dict(msg_signature="5c45ff5e21c57e6ad56bac8758b79b1d9ac89fd3", timestamp="1409659589", nonce="263014780",
                     echostr="P9nAzCzyDtyTWESHep1vC5X9xho/qYX3Zpb4yKa9SKld1DsH3Iyt3tP3zNdtp+4RPcs8TgAE7OaBO+FZXvnaqQ==")
OFFICIAL_POST_QS = dict(msg_signature="477715d11cdb4164915debcba66cb864d751f3e6", timestamp="1409659813", nonce="1372623149")
OFFICIAL_POST_BODY = (
    "<xml><ToUserName><![CDATA[wx5823bf96d3bd56c7]]></ToUserName><Encrypt><![CDATA[RypEvHKD8QQKFhvQ6QleEB4J58tiPdvo+rtK1I9qca6aM/wvqnLSV5zEPeusUiX5L5X/0lWfrf0QADHHhGd3QczcdCUpj911L3vg3W/sYYvuJTs3TUUkSUXxaccAS0qhxchrRYt66wiSpGLYL42aM6A8dTT+6k4aSknmPj48kzJs8qLjvd4Xgpue06DOdnLxAUHzM6+kDZ+HMZfJYuR+LtwGc2hgf5gsijff0ekUNXZiqATP7PF5mZxZ3Izoun1s4zG4LUMnvw2r+KqCKIw+3IQH03v+BCA9nMELNqbSf6tiWSrXJB3LAVGUcallcrw8V2t9EL4EhzJWrQUax5wLVMNS0+rUPA3k22Ncx4XXZS9o0MBH27Bo6BpNelZpS+/uh9KsNlY6bHCmJU9p8g7m3fVKn28H3KDYA5Pl/T8Z1ptDAVe0lXdQ2YoyyH2uyPIGHBZZIs2pDBS8R07+qN+E7Q==]]></Encrypt><AgentID><![CDATA[218]]></AgentID></xml>"
)


def test_official_example_decrypts():
    crypto = WeChatCrypto(OFFICIAL_TOKEN, OFFICIAL_AES, CORPID)
    e = OFFICIAL_ECHO
    assert crypto.check_signature(e["msg_signature"], e["timestamp"], e["nonce"], e["echostr"]) == "1616140317555161061"
    q = OFFICIAL_POST_QS
    plain = crypto.decrypt_message(OFFICIAL_POST_BODY, q["msg_signature"], q["timestamp"], q["nonce"])
    assert "<Content><![CDATA[hello]]></Content>" in plain


def _settings(tmp_path, **over):
    from app.core.migrate import upgrade_to_heads

    s = make_settings(tmp_path, WECOM_CORPID=CORPID, WECOM_KF_SECRET=SECRET, WECOM_TOKEN=OFFICIAL_TOKEN,
                      WECOM_AES_KEY=OFFICIAL_AES, WECOM_OPEN_KFID=KFID, **over)
    upgrade_to_heads(s.DATABASE_URL)
    return s


def test_callback_verify_url_with_official_example(tmp_path, notifier):
    app = make_app(_settings(tmp_path), notifier, tmp_path)
    with TestClient(app) as c:
        r = c.get("/api/channels/wecom/callback", params=OFFICIAL_ECHO)
        assert r.status_code == 200 and r.text == "1616140317555161061"
        bad = dict(OFFICIAL_ECHO, msg_signature="0" * 40)
        assert c.get("/api/channels/wecom/callback", params=bad).status_code == 403
        # 官方示例的 POST 是一条普通文字消息（不是微信客服事件）：解得开、回 success、不拉消息
        r = c.post("/api/channels/wecom/callback", params=OFFICIAL_POST_QS, content=OFFICIAL_POST_BODY)
        assert r.status_code == 200 and r.text == "success"


def test_callback_not_configured_is_503(client):
    assert client.get("/api/channels/wecom/callback", params=OFFICIAL_ECHO).status_code == 503


def _kf_event_post(crypto: WeChatCrypto) -> tuple[dict[str, str], str]:
    xml = (f"<xml><ToUserName><![CDATA[{CORPID}]]></ToUserName><CreateTime>1348831860</CreateTime>"
           "<MsgType><![CDATA[event]]></MsgType><Event><![CDATA[kf_msg_or_event]]></Event>"
           f"<Token><![CDATA[ENCApHxnGDNAVNY4AaSJKj4Tb5mwsEMzxhFmHVGcra996NR]]></Token><OpenKfId><![CDATA[{KFID}]]></OpenKfId></xml>")
    from wechatpy.utils import to_text
    import xmltodict

    enc = to_text(crypto.encrypt_message(xml, "1372623149", "1409659813"))
    d = xmltodict.parse(enc)["xml"]
    return {"msg_signature": d["MsgSignature"], "timestamp": d["TimeStamp"], "nonce": d["Nonce"]}, enc


def _wait(pred, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.05)
    return False


def _bot_script(prompt: str):
    ids = file_ids(prompt)
    if ids:
        return ([("record_info", {"occasion": "开题"})] + [("register_file", {"file_id": i, "purpose": "开题报告"}) for i in ids],
                "收到开题报告啦。大概讲几分钟、哪天汇报？")
    return [], "同学你好哦，材料发我就行"


REDEEM_LINK = "https://work.weixin.qq.com/kf/kfcfake?enc_scene=ENCredeem"


def enable_wecom(app, on: bool = True) -> None:
    """后台「入口」页打开微信客服开关、存好兑换用的客服链接（默认关）。另开一个库连接：不提前建运行时（测试还要改设置）。"""
    from app.core.db import Database

    d = Database(app.state.settings.DATABASE_URL)
    with d.session() as db:
        save_entry_config(db, EntryConfig(wecom_enabled=on, wecom_links={"redeem": REDEEM_LINK}))
    d.dispose()


@pytest.fixture
def wecom_app(tmp_path, notifier):
    fake = FakeWecom(page_size=2)
    app = make_app(_settings(tmp_path), notifier, tmp_path, model=scripted_model(_bot_script),
                   wecom_transport=fake.transport())
    enable_wecom(app)
    return app, fake


def _code(app, sku="regular-p1") -> str:
    from app.intake import codes

    with get_runtime(app).database.session() as db:
        return codes.generate_batch(db, sku=sku, count=1)[1][0].code


def test_full_chain_callback_sync_bot_approve_send(wecom_app):
    app, fake = wecom_app
    fake.enter_session("wm_hang", "e1", scene_param="gzh_article")
    with TestClient(app):
        code = _code(app)
    fake.customer_says("wm_hang", f"师兄 我想要做PPT，激活码 {code}", "m1")  # 发码当场认领，后面的文件就收了
    fake.customer_sends_file("wm_hang", "MEDIA_PDF", "m2")
    with TestClient(app) as c:
        rt = get_channels(app)
        qs, body = _kf_event_post(rt.crypto)
        t0 = time.monotonic()
        r = c.post("/api/channels/wecom/callback", params=qs, content=body)
        assert r.text == "success" and time.monotonic() - t0 < 1.0  # 先回 success，拉消息在后台
        db_ = rt.intake.database
        with db_.session() as db:
            assert db.scalar(select(func.count()).select_from(WecomInbox).where(WecomInbox.status == "pending")) == 1
        assert fake.calls.count("/kf/sync_msg") == 0  # 回调里一条消息都没拉（只入队）
        c.portal.call(process_inbox, rt)  # 工人（测试里关着后台圈，手动跑一圈）

        def synced():
            with db_.session() as db:
                n_in = db.scalar(select(func.count()).select_from(Message).where(Message.direction == "in"))
                return n_in == 2 and db.get(WecomCursor, KFID) is not None
        assert _wait(synced)
        with db_.session() as db:
            cust = db.scalar(select(Customer).where(Customer.external_id == "wm_hang"))
            assert (cust.channel, cust.nickname, cust.source, cust.open_kfid) == ("wecom", "杭杭杭吖", "gzh_article", KFID)
            f = db.scalar(select(FileRecord))
            assert f.filename == "开题报告-阿杭.pdf"
            assert db.get(WecomCursor, KFID).cursor == "3"  # 分了两页拉完，游标存库
        assert fake.calls.count("/kf/sync_msg") == 2
        assert [e["code"] for e in fake.events_sent] == ["WELCOME"]  # 欢迎语直接发（welcome_code 等不了人批）
        assert fake.events_sent[0]["text"]["content"].startswith(load_welcome(rt))

        c.portal.call(run_due_jobs, rt.intake)
        with db_.session() as db:
            ob = db.scalar(select(Outbox).where(Outbox.author == "bot"))
            assert ob.status == "approved"  # 接单 v2：回复直接发，不进待批
            assert ob.text.startswith("收到开题报告啦") and ob.channel == "wecom" and ob.recipient == "wm_hang"
            o = service.current_order(db, db.get(Customer, ob.customer_id))
            assert o.occasion == "开题" and o.wechat_external_userid == "wm_hang" and o.source == "gzh_article"
            ob_id = ob.id

        c.portal.call(dispatch_approved, rt)
        with db_.session() as db:
            assert db.get(Outbox, ob_id).status == "sent"
        assert fake.sent[-2] == {"touser": "wm_hang", "open_kfid": KFID, "msgtype": "text",
                                 "text": {"content": "收到开题报告啦。大概讲几分钟、哪天汇报？"}, "msgid": f"ob{ob_id}"}
        # 助手记下了场合（开题）：资料清单（设置里的原文）跟在助手那句后面发，收到的标「收到了」
        mats = fake.sent[-1]["text"]["content"]
        assert mats.startswith("开题要发这几样") and "开题报告（或开题 PPT 初稿）：研究问题、方法、预期都从这里出（收到了）" in mats
        assert "资料齐了才开工" in mats and len(mats.encode()) <= 2048

        # 同一批消息再推一遍（游标回到开头）：msgid 去重，不重复收
        with db_.session() as db:
            db.get(WecomCursor, KFID).cursor = ""
        c.portal.call(sync_messages, rt, KFID, "")
        with db_.session() as db:
            assert db.scalar(select(func.count()).select_from(Message).where(Message.direction == "in")) == 2


def test_window_blocks_sixth_message_before_wecom_does(wecom_app):
    app, fake = wecom_app
    fake.customer_says("wm_dlh", "汇报时长：15min，下周三下午四五点汇报", "m1")
    with TestClient(app) as c:
        rt = get_channels(app)
        c.portal.call(sync_messages, rt, KFID, "")
        c.post("/api/auth/login", json={"password": TEST_PASSWORD})
        with rt.intake.database.session() as db:
            cid = db.scalar(select(Customer).where(Customer.external_id == "wm_dlh")).id
        results = [c.post(f"/api/admin/intake/conversations/{cid}/messages", json={"text": f"第 {i + 1} 条"}).json() for i in range(6)]
        assert [r["status"] for r in results] == ["sent"] * 5 + ["failed"]
        assert "48 小时内已经发满 5 条" in results[5]["error"]
        assert len(fake.sent) == 5  # 第 6 条根本没打到企业微信
        detail = c.get(f"/api/admin/intake/conversations/{cid}").json()
        assert detail["window"]["sends_left"] == 0
        # 客户又说了一句 → 重新计 5 条；后台把失败那条再批一次就能发
        # （微信的 send_time 只到秒；同一秒里的算在前面，宁可少发一条也不撞上限，所以这里让客户晚一秒说）
        fake.customer_says("wm_dlh", "好的", "m2", send_time=int(time.time()) + 1)
        c.portal.call(sync_messages, rt, KFID, "")
        with rt.intake.database.session() as db:  # 窗口重新开了：因为窗口发不出去的那条自动重新排队
            assert db.get(Outbox, results[5]["id"]).status == "approved"
        c.portal.call(dispatch_approved, rt)
        with rt.intake.database.session() as db:
            assert db.get(Outbox, results[5]["id"]).status == "sent"


def test_over_48_hours_is_blocked(wecom_app):
    app, fake = wecom_app
    old = int(time.time()) - 49 * 3600
    fake.customer_says("wm_old", "之前问过", "m1", send_time=old)
    with TestClient(app) as c:
        rt = get_channels(app)
        c.portal.call(sync_messages, rt, KFID, "")
        c.post("/api/auth/login", json={"password": TEST_PASSWORD})
        with rt.intake.database.session() as db:
            cid = db.scalar(select(Customer).where(Customer.external_id == "wm_old")).id
        r = c.post(f"/api/admin/intake/conversations/{cid}/messages", json={"text": "回访一下"}).json()
        assert r["status"] == "failed" and "超过 48 小时" in r["error"]
        assert fake.sent == []


def test_file_image_voice_welcome_takeover_contact_way_and_token_refresh(wecom_app, tmp_path):
    app, fake = wecom_app
    qr = tmp_path / "pay.png"
    qr.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    app.state.intake_settings = app.state.intake_settings.model_copy(update={"PAY_QR_IMAGE": qr})
    fake.enter_session("wm_hang", "e1", welcome_code="WC1")
    with TestClient(app):
        code = _code(app)
    fake.customer_says("wm_hang", f"在吗 {code}", "m1")
    fake.customer_sends_file("wm_hang", "MEDIA_VOICE", "m2", msgtype="voice")
    with TestClient(app) as c:
        rt = get_channels(app)
        c.portal.call(sync_messages, rt, KFID, "")
        assert fake.events_sent[0]["code"] == "WC1" and fake.events_sent[0]["text"]["content"].startswith(load_welcome(rt))
        db_ = rt.intake.database
        with db_.session() as db:
            cust = db.scalar(select(Customer).where(Customer.external_id == "wm_hang"))
            voice_reply = db.scalar(select(Outbox).where(Outbox.category == "语音提示"))
            assert voice_reply is not None and voice_reply.status == "approved"
            order = service.current_order(db, cust)
            rec = service.add_deliverable(db, rt.intake.ctx, order, filename="deck.pptx", data=b"PK\x03\x04pptx", kind="PPT")
            f_ob = service.create_outbox(db, rt.intake.ctx, cust, order, kind="file", file_id=rec.id, text="deck.pptx", approved=True)
            q_ob = service.create_outbox(db, rt.intake.ctx, cust, order, kind="image", asset="pay_qr", text="付款二维码", approved=True)
            ids = (f_ob.id, q_ob.id)
            cid = cust.id
        fake.expire_next = True  # 令牌过期：自动换一个再发
        c.portal.call(dispatch_approved, rt)
        assert [u["type"] for u in fake.uploads] == ["file", "image"]
        assert [s["msgtype"] for s in fake.sent] == ["text", "text", "file", "image"]  # 先是认领结果、语音那句固定回复
        assert fake.sent[0]["text"]["content"].startswith("已对上你的订单")
        assert fake.tokens_issued == 2
        with db_.session() as db:
            assert all(db.get(Outbox, i).status == "sent" for i in ids)

        # 发送失败的事后通知：那条标成失败
        fake.send_fail_event("wm_hang", "SENT3", "e9")
        c.portal.call(sync_messages, rt, KFID, "")
        with db_.session() as db:
            assert db.get(Outbox, ids[0]).status == "failed"

        c.post("/api/auth/login", json={"password": TEST_PASSWORD})
        r = c.post(f"/api/admin/intake/conversations/{cid}/takeover", json={"on": True}).json()
        assert r == {"takeover": True, "note": ""}
        c.post(f"/api/admin/intake/conversations/{cid}/takeover", json={"on": False})
        assert fake.trans == []  # 「我来接」只停助手，不把微信会话转人工（转了接口就发不了，主窗口裁决 K3）

        r = c.post("/api/admin/intake/wecom/contact-way", json={"scene": "gallery"})
        assert r.json()["url"].endswith("enc_scene=gallery")
        assert c.post("/api/admin/intake/wecom/contact-way", json={"scene": "有中文"}).status_code == 422


def load_welcome(rt) -> str:
    with rt.intake.database.session() as db:
        return load_config(db).welcome_text


def test_wecom_not_configured_marks_failed(tmp_path, notifier, settings):
    app = make_app(settings, notifier, tmp_path)
    with TestClient(app):
        rt = get_runtime(app)
        with rt.database.session() as db:
            cust = service.get_or_create_customer(db, "wecom", "wm_x")
            service.receive_text(db, rt.ctx, cust, "你好")
            ob = service.create_outbox(db, rt.ctx, cust, None, text="好滴", approved=True)
            oid = ob.id
        import asyncio

        asyncio.run(dispatch_approved(get_channels(app)))
        with rt.database.session() as db:
            ob = db.get(Outbox, oid)
            assert ob.status == "failed" and "凭证还没配" in ob.error
