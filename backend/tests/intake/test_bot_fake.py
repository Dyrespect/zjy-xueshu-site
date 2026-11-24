"""第二层：假模型（PydanticAI FunctionModel）跑整段对话。11-18 起分两种模式：
- 没认领（访客问答）：只许报价、发交付和注意事项、发购买方式、发负责人微信；不收资料；每天有上限。
- 认领后（serve）：记信息、登记材料、跟进度、转告制作方、逐页收修改、撤单。
客户发来的激活码在调模型之前由代码认领（order.claim 节点）。"""

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.core.db import Database, utcnow
from app.intake import clock, codes, orders, service
from app.intake.bot import VISITOR_TOOLS, BotRunner, build_agent, load_rules, take_snapshot
from app.intake.config_store import load_config, save_config, terms_message
from app.intake.models import ActivationCode, Customer, Order, Outbox, ProductionMessage
from app.intake.runtime import IntakeRuntime
from app.intake.worker import run_due_jobs
from tests.intake.helpers import PDF_BYTES, claimed, confirm_brief, file_ids, make_ctx, package, ready, scripted_model


@pytest.fixture
def ctx(tmp_path, notifier):
    qr = tmp_path / "owner.jpg"
    qr.write_bytes(b"\xff\xd8\xff fake jpg")
    return make_ctx(tmp_path, notifier, OWNER_WECHAT_QR=qr)


def _customer(database: Database, ctx, text: str | None = None, *, key="key-bot-0123456789", name="青提", channel="wecom"):
    with database.session() as db:
        c = service.get_or_create_customer(db, channel, key, nickname=name)
        if text:
            service.receive_text(db, ctx, c, text)
        return c.id


def _say(database, ctx, cid, text):
    with database.session() as db:
        service.receive_text(db, ctx, db.get(Customer, cid), text)


def _send_file(database, ctx, cid, name):
    with database.session() as db:
        service.receive_file(db, ctx, db.get(Customer, cid), filename=name, data=PDF_BYTES)


def _sent_all(database):
    with database.session() as db:
        for ob in db.scalars(select(Outbox).where(Outbox.status.in_(("pending", "approved")))):
            if ob.status == "pending":
                service.approve_outbox(db, ob)
            service.mark_sent(db, ob)


def _order(database, cid) -> Order | None:
    with database.session() as db:
        o = orders.current_order(db, db.get(Customer, cid))
        if o is not None:
            db.expunge(o)
        return o


def _outbox(database, cid):
    with database.session() as db:
        return [(o.kind, o.asset, o.category, o.text) for o in db.scalars(
            select(Outbox).where(Outbox.customer_id == cid).order_by(Outbox.id))]


def _set_payment(database, link="https://fk.example.cn/buy"):
    with database.session() as db:
        cfg = load_config(db)
        cfg.payment.link = link
        save_config(db, cfg)


def test_visitor_mode_only_has_four_tools():
    names = {t.name for t in build_agent(None, "visitor_qa")._function_toolset.tools.values()}
    assert names == set(VISITOR_TOOLS)
    serve = {t.name for t in build_agent(None, "serve")._function_toolset.tools.values()}
    assert "record_info" in serve and "send_terms" not in serve and "redeem_code" not in serve


async def test_visitor_quotes_sends_terms_then_payment(database, ctx):
    _set_payment(database)
    turns = [
        ([("quote_price", {"minutes": 20, "papers": 1, "rush": True})], "常规档 29.9 元，加急再加 9.9"),
        ([("send_terms", {"minutes": 20, "papers": 1, "rush": True})], "上面是做完你会拿到的东西，还有几条先说清楚的，你看下"),
        ([("send_payment", {})], "付完拿到激活码发给我就行"),
    ]
    runner = BotRunner(scripted_model(turns))
    cid = _customer(database, ctx, "讲 20 分钟 1 篇文献多少钱，能加急吗")
    run = await runner.run_for_customer(database, ctx, cid)
    res = run.tool_calls[0]["result"]
    assert "常规档（25 分钟以内，30 页以内）· 1 篇：29.9 元" in res and "加急 +9.9 元" in res and "合计 39.8 元" in res
    assert "开工后 5 小时内交第一版" in res and "【价目】" in run.situation and "还没有订单" in run.situation  # 加急 3 + 余量 2
    _sent_all(database)
    _say(database, ctx, cid, "好的，就要加急的")
    await runner.run_for_customer(database, ctx, cid)
    with database.session() as db:
        cfg = load_config(db)
        assert db.get(Customer, cid).terms_sent_at is not None
    out = _outbox(database, cid)[-2:]
    assert out[0][1] == "terms" and out[0][3].startswith("常规·1 篇：29.9 元，开工后 7 小时内交水印版。加急 +9.9 元")
    assert cfg.deliver_text in out[0][3] and cfg.notes_text in out[0][3]
    _sent_all(database)
    _say(database, ctx, cid, "可以")
    await runner.run_for_customer(database, ctx, cid)
    assert _outbox(database, cid)[-1][1] == "payment"
    assert _order(database, cid) is None  # 还没付款：没有订单


async def test_payment_before_terms_blocked_and_channel_unset_sends_owner(database, ctx):
    turns = [([("send_payment", {})], "先看下做完会拿到什么哦"),
             ([("send_terms", {}), ("send_payment", {})], "x"),
             ([("send_payment", {})], "付款方式这边还没弄好，可以加负责人的微信")]
    runner = BotRunner(scripted_model(turns))
    cid = _customer(database, ctx, "怎么买")
    run = await runner.run_for_customer(database, ctx, cid)
    assert "还没把交付和注意事项发给客户" in run.tool_calls[0]["result"]
    _sent_all(database)
    _say(database, ctx, cid, "发我看看")
    await runner.run_for_customer(database, ctx, cid)
    _sent_all(database)
    _say(database, ctx, cid, "可以，怎么付")
    run = await runner.run_for_customer(database, ctx, cid)
    assert "付款渠道还没设置好" in run.tool_calls[0]["result"]
    assert _outbox(database, cid)[-1][1] == "owner_qr"


async def test_code_in_message_is_claimed_before_model_then_collects(database, ctx, notifier, tmp_path):
    present = (clock.today() + timedelta(days=10)).isoformat()
    with database.session() as db:
        _, (row,) = codes.generate_batch(db, sku="regular-p1", count=1)
        code = row.code

    def script(prompt: str):
        if "【激活码】" in prompt and "认领上了" in prompt:
            return [], "认领好啦，把论文发我，再说下讲几分钟、哪天汇报"
        if file_ids(prompt):
            return [("register_file", {"file_id": file_ids(prompt)[0], "purpose": "论文"})], "收到论文啦"
        if "讲 20 分钟" in prompt:
            return ([("record_info", {"occasion": "组会文献", "duration_min": 20, "paper_count": 1, "present_date": present,
                                      "requirement_quote": "我们组重视实验流程"})], "好滴，收齐了")
        return [], "好滴"

    runner = BotRunner(scripted_model(script))
    cid = _customer(database, ctx, f"买好了，码是 {code.lower().replace('-', ' ')}")
    run = await runner.run_for_customer(database, ctx, cid)
    assert "认领上了" in run.situation and "【这单】" in run.situation and "常规 · 1 篇" in run.situation
    o = _order(database, cid)
    assert o is not None and o.stage == "claimed" and o.sku == "regular-p1"
    _sent_all(database)
    _send_file(database, ctx, cid, "Affiliation in human-AI interactions.pdf")
    run = await runner.run_for_customer(database, ctx, cid)
    assert [t["name"] for t in run.tool_calls] == ["register_file"]
    _sent_all(database)
    _say(database, ctx, cid, "组会，讲 20 分钟，1 篇，下下周三")
    run = await runner.run_for_customer(database, ctx, cid)
    o = _order(database, cid)
    assert (o.duration_min, o.paper_count, o.present_date.isoformat()) == (20, 1, present)
    # 09 需求引导：资料齐了，需求卡没确认就不开工；助手的情况里有需求卡那一行（链接），不自己问场合听众风格
    assert o.stage == "collecting" and o.started_at is None
    assert "【需求卡】没确认" in run.situation and "/b/" in run.situation
    with database.session() as db:
        confirm_brief(db, ctx, db.get(Order, o.id))
    o = _order(database, cid)
    assert o.stage == "making" and o.started_at is not None  # 客人点了「对，开工」→ 当场开工
    assert (tmp_path / "inbox" / "青提" / "要求.md").exists()


async def test_wrong_code_reason_shown_to_model(database, ctx):
    seen = []

    def script(prompt):
        seen.append(prompt)
        return [], "码对不上哦"

    runner = BotRunner(scripted_model(script))
    cid = _customer(database, ctx, "PSY-AAAAAAAAA")
    await runner.run_for_customer(database, ctx, cid)
    assert "PSY-AAAAAAAAA 没认领：码不对" in seen[0] and "再错 4 次" in seen[0]


async def test_serve_tools_refuse_in_visitor_mode_situation(database, ctx):
    """没认领时情况里写明只问答；文件已经被系统拒收（不调模型）。"""
    cid = _customer(database, ctx, channel="web", key="key-vis-0123456789")
    _send_file(database, ctx, cid, "paper.pdf")
    with database.session() as db:
        assert "激活码" in db.scalar(select(Outbox).where(Outbox.customer_id == cid)).text
        assert db.get(Customer, cid).bot_seen_msg_id == 0


async def test_default_duration_needs_nod(database, ctx):
    turns = [
        ([("record_info", {"occasion": "组会文献"}), ("default_duration", {"customer_agreed": False})], "那我按 15 分钟做，可以吗"),
        ([("default_duration", {"customer_agreed": True})], "好滴"),
    ]
    runner = BotRunner(scripted_model(turns))
    with database.session() as db:
        c, o = claimed(db, ctx, name="不设时间", channel="wecom")
        cid = c.id
        service.receive_text(db, ctx, c, "讲清楚就行，不设时间")
    await runner.run_for_customer(database, ctx, cid)
    o = _order(database, cid)
    assert (o.duration_min, o.duration_default, o.duration_confirmed) == (15, True, False)
    _say(database, ctx, cid, "可以")
    await runner.run_for_customer(database, ctx, cid)
    assert _order(database, cid).duration_confirmed is True


async def test_owner_wechat_qr_once_a_day(database, ctx, notifier):
    turns = [
        ([("send_owner_wechat", {"reason": "退款", "detail": "客户要退款"})], "这个我这边处理不了，可以加负责人的微信"),
        ([("send_owner_wechat", {"reason": "要真人", "detail": "客户要找真人"})], "可以加上面那个负责人微信哦"),
    ]
    runner = BotRunner(scripted_model(turns))
    cid = _customer(database, ctx, "我不想要了，能退款吗")
    run = await runner.run_for_customer(database, ctx, cid)
    assert "二维码图片会跟在你这条回复后面发" in run.tool_calls[0]["result"]
    assert [(k, a, cat) for k, a, cat, _ in _outbox(database, cid)] == [("text", "", "负责人微信"), ("image", "owner_qr", "负责人微信")]
    assert any("发了你的微信二维码：退款" in s for s in notifier.sent)
    _sent_all(database)
    # 接待机器人（12 设计第九节）：转了负责人以后机器人闭嘴，等负责人点「交还机器人」
    with database.session() as db:
        assert db.get(Customer, cid).human_takeover is True
    _say(database, ctx, cid, "我要找真人")
    assert await runner.run_for_customer(database, ctx, cid) is None
    with database.session() as db:
        service.set_takeover(db, ctx, db.get(Customer, cid), False)
    run = await runner.run_for_customer(database, ctx, cid)
    assert "24 小时内已经发过了" in run.tool_calls[0]["result"]


async def test_bad_tool_args_are_not_applied(database, ctx):
    past = (clock.today() - timedelta(days=3)).isoformat()
    with database.session() as db:
        c, o = claimed(db, ctx, name="坏参数", channel="wecom")
        cid = c.id
        service.receive_text(db, ctx, c, "上周五汇报")
    runner = BotRunner(scripted_model([([("record_info", {"present_date": past}), ("register_file", {"file_id": 999, "purpose": "论文"})], "好滴")]))
    run = await runner.run_for_customer(database, ctx, cid)
    assert run.error == "" and _order(database, cid).present_date is None


async def test_no_new_message_no_run_and_model_not_configured(database, ctx, notifier):
    """没配模型（第一阶段接单助手关着）：客人的话转后台人工——回一句「负责人本人在回复」（6 小时内只一次）、
    告诉负责人一声；不记助手失败、不留助手记录、不重试（工人那边算做完）。"""
    from app.core.events import Event
    from app.intake.models import BotRun

    cid = _customer(database, ctx)
    assert await BotRunner(scripted_model([([], "好滴")])).run_for_customer(database, ctx, cid) is None
    _say(database, ctx, cid, "在吗")
    _say(database, ctx, cid, "我想问下多少钱")
    assert await BotRunner(None).run_for_customer(database, ctx, cid) is None
    assert any("发来 2 条消息" in s and "后台「对话」" in s and "多少钱" in s for s in notifier.sent)
    i = next(i for i, s in enumerate(notifier.sent) if "发来 2 条消息" in s)
    assert (notifier.levels[i], notifier.kinds[i], notifier.whos[i]) == ("urgent", "客人消息", f"customer:{cid}")  # 助手没开：客人消息照推，同一位 10 分钟合并
    assert not any("没成功" in s for s in notifier.sent)
    with database.session() as db:
        c = db.get(Customer, cid)
        assert c.bot_seen_msg_id > 0
        acks = list(db.scalars(select(Outbox).where(Outbox.customer_id == cid, Outbox.category == "人工接待")))
        assert len(acks) == 1 and "负责人本人" in acks[0].text and acks[0].author == "system"
        assert db.scalar(select(func.count()).select_from(BotRun)) == 0
        assert db.scalar(select(func.count()).select_from(Event).where(Event.type == "intake.bot_failed")) == 0
    _say(database, ctx, cid, "资料发你了")
    assert await BotRunner(None).run_for_customer(database, ctx, cid) is None
    with database.session() as db:  # 6 小时内不再回那句，但还是告诉负责人
        assert db.scalar(select(func.count()).select_from(Outbox).where(Outbox.customer_id == cid, Outbox.category == "人工接待")) == 1
    assert any("发来 1 条消息" in s and "资料发你了" in s for s in notifier.sent)
    assert await BotRunner(None).run_for_customer(database, ctx, cid) is None  # 没有新话：什么都不做


async def test_worker_merges_burst_into_one_run(database, ctx):
    calls = []

    def script(prompt):
        calls.append(prompt)
        return [], "收到"

    rt = IntakeRuntime(ctx, BotRunner(scripted_model(script)), database)
    cid = _customer(database, ctx, "老师要求：主要汇报摘要、引言逻辑、创新点")
    _say(database, ctx, cid, "汇报时间不超过10分钟")
    assert await run_due_jobs(rt) == 1 and len(calls) == 1
    assert "不超过10分钟" in calls[0].split("【这次客户新说的】")[1]
    assert await run_due_jobs(rt) == 0


async def test_visitor_daily_limit_stops_model(database, ctx):
    with database.session() as db:
        cfg = load_config(db)
        cfg.visitor_daily_limit = 2
        save_config(db, cfg)
    calls = []

    def script(prompt):
        calls.append(prompt)
        return [], "好滴"

    runner = BotRunner(scripted_model(script))
    cid = _customer(database, ctx, "第一句")
    await runner.run_for_customer(database, ctx, cid)
    _say(database, ctx, cid, "第二句")
    _say(database, ctx, cid, "第三句")
    assert await runner.run_for_customer(database, ctx, cid) is None  # 超了：不调模型
    _say(database, ctx, cid, "第四句")
    assert await runner.run_for_customer(database, ctx, cid) is None
    assert len(calls) == 1
    limited = [x for x in _outbox(database, cid) if x[2] == "访客上限"]
    assert len(limited) == 1 and "激活码" in limited[0][3]  # 当天只回一次


async def test_maker_question_relayed_and_answer_goes_back(database, ctx):
    from app.intake.production import maker_says

    with database.session() as db:
        c, o = ready(db, ctx, name="转告", channel="wecom")
        cid, oid = c.id, o.id
        assert o.stage == "making"
    _sent_all(database)

    def script(prompt):
        if "【制作方新消息" in prompt:
            return [], "做 PPT 的同事问：研究团队那页要放几位作者？"
        return [("ask_maker", {"kind": "回答", "text": "客户说：放前三位作者就行"})], "好滴，已经转给同事了"

    runner = BotRunner(scripted_model(script))
    with database.session() as db:
        maker_says(db, ctx, db.get(Order, oid), "问题", "研究团队那页放几位作者？")
    run = await runner.run_for_customer(database, ctx, cid)
    assert run is not None and "研究团队那页放几位作者" in run.situation
    assert await runner.run_for_customer(database, ctx, cid) is None
    _sent_all(database)
    _say(database, ctx, cid, "放前三位就行")
    await runner.run_for_customer(database, ctx, cid)
    with database.session() as db:
        last = db.scalar(select(ProductionMessage).order_by(ProductionMessage.id.desc()))
        assert (last.direction, last.kind, last.author) == ("to_maker", "回答", "bot")


async def test_revision_items_then_used_up_then_addon_code(database, ctx):
    with database.session() as db:
        c, o = ready(db, ctx, name="改稿", channel="wecom")
        cid, oid = c.id, o.id
        package(db, ctx, o)
        assert o.stage == "watermarked"
        _, (extra,) = codes.generate_batch(db, sku="addon-revision", count=1)
        extra_code = extra.code
    _sent_all(database)
    turns = [
        ([("submit_revision", {"items": [{"page": 6, "text": "结果图换成原文的图 3"}, {"page": None, "text": "字少一点"}]})], "收到"),
        ([("submit_revision", {"items": [{"page": 2, "text": "配色再深一点"}]})], "修改轮数用完了"),
        ([], "加购好啦，说下要改哪里"),
    ]
    runner = BotRunner(scripted_model(turns))
    _say(database, ctx, cid, "第 6 页结果图换成原文的图 3，字少一点")
    await runner.run_for_customer(database, ctx, cid)
    with database.session() as db:
        o = db.get(Order, oid)
        sheet = service.production_messages(db, o)[-1]
        assert o.stage == "revising" and sheet.kind == "改稿单" and "1. 第 6 页：结果图换成原文的图 3" in sheet.text
        package(db, ctx, o)  # 改好的那版
    _sent_all(database)
    _say(database, ctx, cid, "配色再深一点")
    run = await runner.run_for_customer(database, ctx, cid)
    assert "轮数用完了" in run.tool_calls[0]["result"]
    _sent_all(database)
    _say(database, ctx, cid, f"我又买了一个 {extra_code}")
    run = await runner.run_for_customer(database, ctx, cid)
    assert "加购：再改一轮" in run.situation
    with database.session() as db:
        o = db.get(Order, oid)
        assert o.extra_revisions == 1 and service.revisions_left(o, load_config(db)) == 1


async def test_cancel_before_start_returns_code_via_bot(database, ctx):
    with database.session() as db:
        c, o = claimed(db, ctx, name="撤单", channel="wecom")
        cid, oid, code_id = c.id, o.id, o.code_id
        service.receive_text(db, ctx, c, "老师取消组会了，不做了")
    runner = BotRunner(scripted_model([([("cancel_order", {"reason": "老师取消组会了"})], "好的，撤好了")]))
    run = await runner.run_for_customer(database, ctx, cid)
    assert "激活码会退回去" in run.tool_calls[0]["result"]
    with database.session() as db:
        o = db.get(Order, oid)
        row = db.get(ActivationCode, code_id)
        assert o.stage == "void" and (row.status, row.order_id) == ("unused", None)


def test_situation_serve_has_facts(database, ctx):
    with database.session() as db:
        c, o = claimed(db, ctx, name="十二", channel="wecom")
        c.source = "xhs"
        service.receive_text(db, ctx, c, "需要把研究设计讲清楚")
        service.update_order(db, ctx, o, {"occasion": "组会文献", "duration_min": 8})
        orders.set_customer_memory(db, c.id, memory_brief="上次用了浙师大模板")
        s = take_snapshot(db, ctx, c).situation
    assert "【今天】" in s and "十二（微信客服，从「xhs」来）" in s
    assert "【老客户记得的】上次用了浙师大模板" in s and "【这单】" in s and "页数上限 30 页" in s
    assert "时长：8 分钟" in s and "还缺：论文" in s and "【清单】还要：" in s
    assert "需要把研究设计讲清楚" in s.split("【这次客户新说的】")[1]


def test_rules_prompt_is_short_and_states_flow():
    text = load_rules()
    assert len("".join(text.split())) <= 3000
    for must in ("AI 助手", "负责人的微信", "send_terms", "send_payment", "ask_maker", "submit_revision", "代写",
                 "不用表情", "问卷调查或访谈", "确认收货", "还没认领激活码"):
        assert must in text
    for gone in ("小戴", "文献·标准", "研究·标准", "redeem_code", "29.9", "9.9"):
        assert gone not in text


def test_returning_customer_sees_last_order(database, ctx):
    with database.session() as db:
        c, o = claimed(db, ctx, name="青柚", channel="wecom")
        service.update_order(db, ctx, o, {"occasion": "组会文献", "duration_min": 20})
        service.cancel_order(db, ctx, o, why="改天")
        service.receive_text(db, ctx, c, "又来啦，这次是开题")
        s = take_snapshot(db, ctx, c).situation
    assert "【上次的单子】" in s and "常规 · 1 篇，组会文献，作废" in s and "还没有订单" in s
