"""第一层（不调模型）：收消息（没认领不收资料）、待发、48 小时窗口、开工判断和排期（按小时）、交接给工厂 inbox
（临时目录）、成品包 → 出水印图 → 发布、逐页改稿。订单本身的建、认领、作废、确认收货在 test_orders.py。"""

import re
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.core.db import utcnow
from app.intake import clock, orders, service
from app.intake.config_store import load_config, save_config
from app.intake.handoff import render_chat_log
from app.intake.models import Customer, FileRecord, Job, Message, Order, Outbox
from tests.intake.helpers import PDF_BYTES, claimed, confirm_brief, make_ctx, package, png, ready

# 工厂 inbox 里现有 聊天记录.md 的样子（PPT工厂/inbox/青提/聊天记录.md 等）：昵称 / 时间 / 内容，条间空一行
CHAT_BLOCK = re.compile(r"^(?P<who>[^\n]+)\n(?P<t>\d{4}年\d{2}月\d{2}日 [ \d]\d:\d{2})\n(?P<body>.+)$", re.S)


@pytest.fixture
def ctx(tmp_path, notifier):
    return make_ctx(tmp_path, notifier)


def test_receive_text_before_claim_has_no_order(database, ctx, notifier):
    with database.session() as db:
        c = service.get_or_create_customer(db, "wecom", "wm_abc", nickname="度量海的湛蓝")
        m = service.receive_text(db, ctx, c, "汇报时长：15min，下周三下午四五点汇报", channel_msgid="m1")
        cid = c.id
        assert m is not None and m.order_id is None  # 11-18：订单在付款时建，开口不建单
        assert db.scalar(select(func.count()).select_from(Order)) == 0
        assert service.receive_text(db, ctx, c, "重复推送", channel_msgid="m1") is None
        assert db.scalar(select(func.count()).select_from(Job).where(Job.status == "pending")) == 1
        service.receive_text(db, ctx, c, "什么时候可以完成，加急")
        assert db.scalar(select(func.count()).select_from(Job)) == 1
    assert notifier.sent[0].startswith("新客户 度量海的湛蓝（微信客服）")
    assert notifier.links[0] == f"/admin/conversations/{cid}"  # 飞书里点一下就到这段对话
    assert notifier.levels[0] == "count"  # 11-19：新客户不推，日报里数个数


def test_takeover_stops_bot_jobs(database, ctx):
    with database.session() as db:
        c = service.get_or_create_customer(db, "web", "key-takeover-0123456789")
        c.human_takeover = True
        service.receive_text(db, ctx, c, "你是真人吗")
        assert db.scalar(select(func.count()).select_from(Job)) == 0
        service.set_takeover(db, ctx, c, False)  # 交还机器人：期间说过的话让机器人接着看
        assert db.scalar(select(func.count()).select_from(Job)) == 1


def test_outbox_sends_directly_unless_category_needs_approval(database, ctx, notifier):
    with database.session() as db:
        c = service.get_or_create_customer(db, "web", "key-auto-0123456789")
        o = None
        # 默认一类都不批：机器人、系统写的话直接发（价格也直接报）
        a = service.create_outbox(db, ctx, c, o, text="研究·标准 29.9 元，最早周三交", category="报价")
        b = service.create_outbox(db, ctx, c, o, text="这个我这边处理不了，可以加负责人的微信", category="负责人微信")
        assert (a.status, a.auto) == ("approved", True) and b.status == "approved"
        # 设置里打开了某一类「先给我看」才进待批
        cfg = load_config(db)
        cfg.approval["报价"] = True
        save_config(db, cfg)
        g = service.create_outbox(db, ctx, c, o, text="文献·标准 19.9 元", category="报价")
        h = service.create_outbox(db, ctx, c, o, text="好滴", category="一般回复")
        e = service.create_outbox(db, ctx, c, o, text="我来接一下", author="edison")
        assert g.status == "pending" and h.status == "approved" and e.status == "approved"
        assert any("等你批（报价）" in s for s in notifier.sent)


def test_approve_edit_reject_and_mark_sent(database, ctx):
    with database.session() as db:
        cfg = load_config(db)
        cfg.approval["一般回复"] = True  # 开了「先给我看」的类别才有待批
        save_config(db, cfg)
        c = service.get_or_create_customer(db, "web", "key-approve-0123456789")
        o = None
        ob = service.create_outbox(db, ctx, c, o, text="同学你好哦", category="一般回复")
        service.approve_outbox(db, ob, text="同学你好哦，材料发我就行")
        assert ob.status == "approved" and ob.original_text == "同学你好哦"
        msg = service.mark_sent(db, ob)
        assert msg.direction == "out" and msg.text == "同学你好哦，材料发我就行" and ob.status == "sent"
        with pytest.raises(ValueError):
            service.approve_outbox(db, ob)
        ob2 = service.create_outbox(db, ctx, c, o, text="多余的一句", category="一般回复")
        service.reject_outbox(db, ob2)
        assert ob2.status == "rejected"


def test_wecom_window_48h_and_5(database, ctx):
    with database.session() as db:
        c = service.get_or_create_customer(db, "wecom", "wm_win")
        assert service.window_info(db, c)["can_send"] is False  # 客户还没说过话
        service.receive_text(db, ctx, c, "在吗")
        w = service.window_info(db, c)
        assert w["can_send"] and w["sends_left"] == 5 and 47.9 < w["hours_left"] <= 48
        o = None
        for i in range(5):
            ob = service.create_outbox(db, ctx, c, o, text=f"第{i}条", approved=True)
            service.mark_sent(db, ob)
        w = service.window_info(db, c)
        assert w["sends_left"] == 0 and not w["can_send"]
        service.receive_text(db, ctx, c, "收到")  # 客户再说一句，重新计
        assert service.window_info(db, c)["sends_left"] == 5
        c.last_customer_msg_at = utcnow() - timedelta(hours=49)
        assert service.window_info(db, c) == {"limited": True, "can_send": False, "sends_left": 0, "hours_left": 0.0}
        web = service.get_or_create_customer(db, "web", "key-web-0123456789")
        assert service.window_info(db, web)["limited"] is False


def test_ready_order_queues_hands_off_and_writes_requirements(database, ctx, notifier, tmp_path):
    with database.session() as db:
        c, o = claimed(db, ctx, name="青柠", sku="regular-p1", addons=["rush"])
        service.update_order(db, ctx, o, {"occasion": "组会文献", "duration_min": 20})
        assert o.stage == "collecting"
        confirm_brief(db, ctx, o)  # 09 需求引导：客人点了「对，开工」才开工
        service.receive_text(db, ctx, c, "组会汇报，讲 20 分钟")
        _, f = service.receive_file(db, ctx, c, filename="Affiliation in human-AI interactions.pdf", data=PDF_BYTES)
        f.purpose = "论文"
        service.update_order(db, ctx, o, {"occasion": "组会文献", "duration_min": 20, "paper_count": 1,
                                          "present_date": clock.today() + timedelta(days=7),
                                          "requirement_quotes": ["1.封面：中英标题，作者名字，期刊IF\n2.研究背景（3-5页）"]})
        # 资料齐 + 今天有名额 → 排队 → 当场交接；付了加急、材料齐、常规档 → 按加急 3 小时
        assert o.stage == "making" and o.started_at is not None and o.rush and o.due_hours == 3 + 2  # 含余量
        ob = db.scalar(select(Outbox).where(Outbox.category == "排期通知"))
        assert ob is not None and "5 小时内先发你水印版" in ob.text and ob.status == "approved"
        brief = service.production_messages(db, o)
        assert [(m.direction, m.kind) for m in brief] == [("to_maker", "开单说明")]
        req = (tmp_path / "inbox" / "青柠" / "要求.md").read_text(encoding="utf-8")
        assert "档位：常规 · 1 篇 + 加急；页数上限 30 页（页数按内容页算" in req
        assert "交付：开工后 5 小时内交第一版水印版" in req and "篇数：1 篇" in req
        # 确认卡并进「客人的需求和偏好」那一段（不另起一份）
        assert "客人的需求和偏好：" in req and "需求确认卡（" in req and "客人自己点了「对，开工」" in req
        assert "听众：导师和同门（按推荐）" in req
        assert "1.封面：中英标题，作者名字，期刊IF\n2.研究背景（3-5页）" in req
        assert "- Affiliation in human-AI interactions.pdf（论文）" in req
        log = (tmp_path / "inbox" / "青柠" / "聊天记录.md").read_text(encoding="utf-8")
        assert all(CHAT_BLOCK.match(b) for b in log.strip("\n").split("\n\n"))
        assert any("这单开工了" in s for s in notifier.sent)


def test_chat_log_time_format_matches_factory():
    from datetime import datetime, timezone

    c = Customer(id=1, channel="wecom", external_id="x", nickname="Carrie")
    m = Message(direction="in", sender="customer", kind="text", text="我是14号汇报",
                created_at=datetime(2026, 11, 2, 21, 44, tzinfo=timezone.utc))  # 北京 11-03 05:44
    out = render_chat_log(c, [m], {})
    assert out == "Carrie\n2026年11月03日  5:44\n我是14号汇报\n"  # 跟 inbox/Carrie/聊天记录.md 一样：时不补零、空格占位


def test_daily_quota_pushes_fourth_to_tomorrow(database, ctx, tmp_path):
    with database.session() as db:
        names = ["一一", "二二", "三三", "四四"]
        os_ = [ready(db, ctx, name=n, days=9)[1] for n in names]
        today = clock.today()
        assert [o.stage for o in os_[:3]] == ["making"] * 3
        assert os_[3].stage == "collecting" and os_[3].start_date == today + timedelta(days=1)
        assert "排在" in orders.progress(db, os_[3])
        assert not (tmp_path / "inbox" / "四四").exists()
        # 第二天到了：工人那一圈让它开工
        monkey = clock.today
        try:
            clock.today = lambda now=None: today + timedelta(days=1)  # noqa: E731
            done = service.handoff_due_orders(db, ctx, today=today + timedelta(days=1))
        finally:
            clock.today = monkey
        assert done == [os_[3].id] and (tmp_path / "inbox" / "四四" / "要求.md").exists()


def test_paid_rush_that_cannot_be_done_goes_standard_with_refund_note(database, ctx, notifier):
    with database.session() as db:
        cfg = load_config(db)
        cfg.rush_daily_quota = 0  # 今天加急名额满了
        save_config(db, cfg)
        c, o = ready(db, ctx, name="加急没名额", addons=["rush"])
        assert o.stage == "making" and not o.rush and o.due_hours == 5 + 2  # 含余量
        assert o.needs_edison[-1]["type"] == "退款" and "加急" in o.needs_edison[-1]["detail"]


def test_wrong_tier_blocks_start(database, ctx):
    with database.session() as db:
        c, o = ready(db, ctx, name="买小了", sku="light-p1", minutes=20)
        assert o.stage == "collecting"
        conds = {x.key: x for x in service.conditions_for(db, o)}
        assert not conds["materials"].ok and "常规档" in conds["materials"].detail  # intake.collect 报超档


def test_folder_name_never_overwrites(database, ctx, tmp_path):
    (tmp_path / "inbox" / "青柠").mkdir(parents=True)
    with database.session() as db:
        c, o = ready(db, ctx)
        assert o.handoff_folder == f"青柠_{clock.today().strftime('%m-%d')}"


def test_package_watermark_publish_revision_loop(database, ctx, notifier):
    with database.session() as db:
        c, o = ready(db, ctx)
        with pytest.raises(ValueError, match="整页图"):
            service.add_deliverable(db, ctx, o, filename="deck.pptx", data=b"pptx", kind="PPT")
            service.submit_package(db, ctx, o, by="maker")  # 只交 pptx 不收：要整页图出水印版
        n = package(db, ctx, o, pages=3)
        assert n == 1 and o.stage == "watermarked" and o.delivery_round == 1
        previews = list(db.scalars(select(FileRecord).where(FileRecord.order_id == o.id, FileRecord.purpose == "水印版")
                                   .order_by(FileRecord.page_no)))
        assert [p.page_no for p in previews] == [1, 2, 3] and all(p.content_type == "image/jpeg" for p in previews)
        assert ctx.storage.read_bytes(previews[0].storage_key)[:2] == b"\xff\xd8"  # JPEG
        link = db.scalar(select(Outbox).where(Outbox.category == "交付").order_by(Outbox.id.desc()))
        assert f"/d/{o.delivery_token}" in link.text and "确认收货" in link.text and link.kind == "text"
        assert not db.scalar(select(func.count()).select_from(Outbox).where(Outbox.kind == "file"))
        rev = service.submit_revision(db, ctx, o, items=[{"page": 5, "text": "图换成原文图 2"}, {"page": None, "text": "标题大一号"}],
                                      files=[("批注.pdf", PDF_BYTES, "application/pdf")], source="delivery")
        assert rev.free and o.stage == "revising" and rev.items[0]["page"] == 5 and rev.based_on_round == 1
        sheet = service.production_messages(db, o)[-1]
        assert sheet.kind == "改稿单" and "1. 第 5 页：图换成原文图 2" in sheet.text and "2. 整体：标题大一号" in sheet.text
        assert "批注.pdf" in sheet.text and "请在 3 小时内交下一版" in sheet.text
        package(db, ctx, o)
        assert o.stage == "watermarked" and o.delivery_round == 2
        rev2 = service.submit_revision(db, ctx, o, text="再改一下配色")
        assert not rev2.free and o.stage == "watermarked" and o.needs_edison[-1]["type"] == "再改"


def test_small_page_images_are_refused(database, ctx):
    from app.intake.watermark import WatermarkError, check_page

    with pytest.raises(WatermarkError, match="缩略图"):
        check_page(png(1334, 750))
    assert check_page(png(1920, 1080)) == (1920, 1080)


def test_voice_before_claim_is_refused_like_files(database, ctx):
    with database.session() as db:
        c = service.get_or_create_customer(db, "wecom", "wm_voice")
        service.receive_voice(db, ctx, c, filename="v.amr", data=b"#!AMR\n...")
        assert db.scalar(select(func.count()).select_from(FileRecord)) == 0
        assert "激活码" in db.scalar(select(Outbox)).text
        c2, o = claimed(db, ctx, name="语音", channel="wecom")
        service.receive_voice(db, ctx, c2, filename="v2.amr", data=b"#!AMR\n...")
        ob = db.scalar(select(Outbox).where(Outbox.customer_id == c2.id, Outbox.category == "语音提示"))
        assert ob.text == "语音我这边听不了，打字或者发文字稿哦"
        assert db.scalar(select(FileRecord)).role == "voice"


def test_handoff_refuses_real_inbox_under_pytest(database, tmp_path, notifier):
    from pathlib import Path

    from app.intake.flow import StageError

    ctx = make_ctx(tmp_path, notifier, FACTORY_INBOX=Path("/Users/edison/Desktop/学术汇报/PPT工厂/inbox"))
    with database.session() as db:
        c, o = claimed(db, make_ctx(tmp_path, notifier), name="保险")
        service.update_order(db, make_ctx(tmp_path, notifier), o, {"occasion": "组会文献"})
        confirm_brief(db, make_ctx(tmp_path, notifier), o)
        with pytest.raises(RuntimeError, match="拒绝写"):
            service.start_now(db, ctx, o)
        db.rollback()


def test_cancel_returns_code_and_returning_customer_gets_new_order(database, ctx):
    with database.session() as db:
        c, o = claimed(db, ctx, name="回头")
        service.cancel_order(db, ctx, o, by="bot", why="不做了")
        assert o.stage == "void"
        service.receive_text(db, ctx, c, "又来啦，这次是开题")
        assert orders.current_order(db, c) is None  # 没有在走的单：访客问答
        _, o2 = claimed(db, ctx, name="回头")
        assert o2.id != o.id and orders.current_order(db, c).id == o2.id


def test_window_failed_outbox_requeued_when_customer_speaks(database, ctx):
    with database.session() as db:
        c = service.get_or_create_customer(db, "wecom", "wm_requeue")
        service.receive_text(db, ctx, c, "在吗")
        o = None
        ob = service.create_outbox(db, ctx, c, o, text="做好啦，在这里下载", category="交付")
        service.mark_failed(db, ob, "客户最后一次说话已经超过 48 小时，等客户再说一句才能发")
        other = service.create_outbox(db, ctx, c, o, text="x", category="一般回复")
        service.mark_failed(db, other, "企业微信接口出错：45009")
        service.receive_text(db, ctx, c, "PPT 好了吗")
        assert ob.status == "approved" and ob.error == ""  # 窗口重新开了：重新排队发
        assert other.status == "failed"  # 别的原因的失败不动


