"""接待机器人（docs/任务单/12_接待机器人_设计.md 第十节「怎么验」的会失败的测试）：
知识库能改、改坏了拦；判断（规则对 36 句评测句的准确率、合规几类必须全对）；引导（一次只问一件、刚问过不追问）；
说话（禁用说法要重写、被问机器人必须说是 AI、不许说自己是真人、拆条、句末不打句号）；节奏（不秒回、有上限、夜里慢）；
接到 bot.py 里以后：开头表明身份、拆条按渠道封顶、到点才发、新消息顶掉没发出去的、转负责人后闭嘴、查东西先说一句。"""

from __future__ import annotations

import random
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from pydantic_ai.messages import ModelRequest, ModelResponse, RetryPromptPart, TextPart, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy import select

from app.core.db import Database, utcnow
from app.intake import clock, service
from app.intake.bot import BotRunner
from app.intake.models import Customer, Outbox
from app.intake.reception import guide, intent, kb as rkb, rhythm, style
from tests.conftest import TEST_PASSWORD
from tests.intake.helpers import claimed, make_app, make_ctx, scripted_model
from tests.intake.reception_cases import CASES, correct

KB = rkb.load(None)


@pytest.fixture
def ctx(tmp_path, notifier):
    qr = tmp_path / "owner.jpg"
    qr.write_bytes(b"\xff\xd8\xff fake jpg")
    return make_ctx(tmp_path, notifier, OWNER_WECHAT_QR=qr, RECEPTION_RHYTHM=True, RECEPTION_DISCLOSURE=True)


def _customer(database: Database, ctx, text: str, *, channel="wecom", key="key-rx-0123456789") -> int:
    with database.session() as db:
        c = service.get_or_create_customer(db, channel, key, nickname="青提")
        service.receive_text(db, ctx, c, text)
        return c.id


def _rows(database: Database, cid: int) -> list[Outbox]:
    with database.session() as db:
        rows = list(db.scalars(select(Outbox).where(Outbox.customer_id == cid).order_by(Outbox.id)))
        for r in rows:
            db.expunge(r)
        return rows


# ---------------------------------------------------------------- 知识库

def test_kb_defaults_valid_and_disclosure_must_say_ai_generated():
    assert {"ask_bot", "escalate", "chitchat", "ask_price", "send_material", "revise", "refund", "invoice"} <= {c.id for c in KB.intents}
    assert len(KB.intents) >= 15 and all(c.examples and c.reply for c in KB.intents)
    # Edison 11-19 定的一句（不要三选一），同时有「AI」和「生成」（GB 45438-2025 显式标识要素）
    assert KB.disclosure.text == "同学你好呀，这里是 PsyEngine，我是 AI 助手小鱼，下面的回复由 AI 生成，负责人随时看记录与接手"
    data = KB.model_dump(mode="json")
    data["disclosure"]["text"] = "你好呀，这里是 PsyEngine，有事随时说"
    with pytest.raises(ValidationError, match="AI"):
        rkb.ReceptionKB.model_validate(data)
    data = KB.model_dump(mode="json")
    data["intents"] = [c for c in data["intents"] if c["id"] != "ask_bot"]
    with pytest.raises(ValidationError, match="ask_bot"):
        rkb.ReceptionKB.model_validate(data)


def test_kb_has_no_hardcoded_prices():
    import re

    text = rkb.DEFAULTS_FILE.read_text(encoding="utf-8")
    assert not re.search(r"\d+\.9|\d+\s*元", text), "价格只在业务设置里（规矩 10），知识库写占位符"


# ---------------------------------------------------------------- 判断

def test_rules_accuracy_on_cases_and_compliance_classes_always_right():
    wrong = []
    for c in CASES:
        r = intent.classify_rules(KB, [c["text"]], c.get("kinds", ["text"]), c.get("last_bot", ""))
        if not correct(c, r.intents):
            wrong.append((c["id"], c["text"], r.intents))
    acc = 1 - len(wrong) / len(CASES)
    assert len(CASES) >= 30
    assert acc >= 0.75, f"规则准确率 {acc:.0%}，错的：{wrong}"
    must = [c for c in CASES if c["want"][0] in ("ask_bot", "escalate", "refund", "invoice", "send_code", "send_material")
            and c.get("kinds") != ["text"]]
    for c in must:  # 合规和转负责人这几类：关键词 / 平台事实直接定，不能错
        r = intent.classify_rules(KB, [c["text"]], c.get("kinds", ["text"]), c.get("last_bot", ""))
        if c["want"][0] in ("ask_bot", "escalate", "refund", "invoice"):
            assert r.intents[0] == c["want"][0] and r.how == "keyword", (c["id"], r)


async def test_model_classifier_used_and_bad_ids_fall_back_to_rules():
    def good(messages, info: AgentInfo):
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"intents": ["ask_time", "ask_price"], "answering": False})])

    r = await intent.classify(KB, FunctionModel(good), texts=["周三要，多少钱"], kinds=["text"], stage="访客", recent=[], last_bot="")
    assert r.intents == ["ask_time", "ask_price"] and r.how == "model"

    def bad(messages, info: AgentInfo):
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"intents": ["nope"], "answering": False})])

    r = await intent.classify(KB, FunctionModel(bad), texts=["多少钱呀"], kinds=["text"], stage="访客", recent=[], last_bot="")
    assert r.intents == ["ask_price"] and r.how == "rules"
    # 关键词定的几类不等模型（模型给错也不影响）
    r = await intent.classify(KB, FunctionModel(good), texts=["你是机器人吗"], kinds=["text"], stage="访客", recent=[], last_bot="")
    assert r.intents == ["ask_bot"] and r.how == "keyword"


# ---------------------------------------------------------------- 引导

def test_visitor_asks_only_what_quote_and_schedule_need_one_at_a_time():
    for c in [c for c in CASES if c["stage"] == "visitor" and "ask" in c]:
        texts = [c["text"]]
        keys = guide.needed_keys(serving=False, stage="", missing=[], brief_ok=True, customer_texts=texts, main_intent=c["want"][0])
        p = guide.plan(KB, keys=keys, intents=c["want"], bot_texts=[c["last_bot"]] if c.get("last_bot") else [],
                       last_bot=c.get("last_bot", ""), answering=c["want"][0] == "answer")
        assert (p.ask.key if p.ask else None) == c["ask"], (c["id"], p)


def test_dont_repeat_an_ask_he_ignored_and_stop_after_max_times():
    keys = ["present_date", "materials"]
    last = "你大概哪天汇报呀，人多的话我得排一下"
    p = guide.plan(KB, keys=keys, intents=["ask_scope"], bot_texts=[last], last_bot=last, answering=False)
    assert p.ask is not None and p.ask.key == "materials" and "刚问过" in p.held[0]
    p = guide.plan(KB, keys=["present_date"], intents=["ask_scope"], bot_texts=[last, "好的", last], last_bot="好的", answering=False)
    assert p.ask is None and "问过 2 次" in p.held[0]
    p = guide.plan(KB, keys=["present_date"], intents=["escalate"], bot_texts=[], last_bot="", answering=False)
    assert p.ask is None and "不追问" in p.why


def test_serve_keys_follow_missing_then_brief():
    assert guide.needed_keys(serving=True, stage="collecting", missing=["材料（论文）", "哪天汇报"], brief_ok=False,
                             customer_texts=[], main_intent="send_material") == ["materials", "present_date"]
    assert guide.needed_keys(serving=True, stage="collecting", missing=[], brief_ok=False, customer_texts=[],
                             main_intent="answer") == ["brief"]
    assert guide.needed_keys(serving=True, stage="making", missing=["哪天汇报"], brief_ok=True, customer_texts=[],
                             main_intent="ask_progress") == []


# ---------------------------------------------------------------- 说话

@pytest.mark.parametrize("text", ["亲，收到啦", "好的呢，马上安排", "希望对你有帮助", "1. 发论文\n2. 说时长", "我是真人哈",
                                  "这个我们保证明天给你", "**加粗**", "您好"])
def test_banned_phrases_are_caught(text):
    assert style.problems(text, KB), text


def test_plain_human_lines_pass_and_ask_bot_needs_truth():
    for ok in ["同学你好哦\n\n大概讲多久、几篇呀", "收到啦", "OK 的，来得及", "不敢保证哈，最早明天", "负责人亲自跟你说"]:
        assert not style.problems(ok, KB), ok
    assert style.problems("哈哈你猜", KB, ["ask_bot"])
    assert not style.problems("我是 AI 助手哈，负责人会看每段对话", KB, ["ask_bot"])
    assert style.problems("收到啦，周三前给你", KB, recent=["收到啦，周三前给你"])  # 同一句不说两遍


def test_segments_split_on_blank_lines_cap_and_drop_trailing_full_stop():
    assert style.segments("收到啦。\n\n你哪天汇报呀？", max_segments=3) == ["收到啦", "你哪天汇报呀？"]
    assert style.segments("一\n\n二\n\n三", max_segments=2) == ["一", "二，三"]


# ---------------------------------------------------------------- 节奏

def test_rhythm_never_instant_has_cap_and_night_is_slower():
    r = KB.rhythm
    now = datetime(2026, 11, 19, 6, 0, tzinfo=clock.TZ).astimezone()
    day = datetime(2026, 11, 19, 14, 0, tzinfo=clock.TZ)
    night = datetime(2026, 11, 19, 2, 0, tzinfo=clock.TZ)
    segs = ["收到啦", "你大概哪天汇报呀，人多的话我得排一下"]
    for seed in range(20):
        t = rhythm.schedule(r, last_customer_at=now, now=now, local_now=day, customer_chars=10, segments=segs, rng=random.Random(seed))
        first = (t[0] - now).total_seconds()
        assert r.first_min_s <= first <= r.first_max_s and t[1] > t[0]
        tn = rhythm.schedule(r, last_customer_at=now, now=now, local_now=night, customer_chars=10, segments=segs,
                             rng=random.Random(seed))
        assert (tn[0] - now).total_seconds() <= r.night_max_s
    avg_day = sum((rhythm.schedule(r, last_customer_at=now, now=now, local_now=day, customer_chars=10, segments=segs,
                                   rng=random.Random(s))[0] - now).total_seconds() for s in range(30)) / 30
    avg_night = sum((rhythm.schedule(r, last_customer_at=now, now=now, local_now=night, customer_chars=10, segments=segs,
                                     rng=random.Random(s))[0] - now).total_seconds() for s in range(30)) / 30
    assert avg_night > avg_day
    # 模型想得久、已经超过该回的时间：马上发（最多晚一秒），不再多等
    late = now + timedelta(seconds=90)
    t = rhythm.schedule(r, last_customer_at=now, now=late, local_now=day, customer_chars=10, segments=segs, rng=random.Random(1))
    assert (t[0] - late).total_seconds() <= 1.01


# ---------------------------------------------------------------- 接到 bot.py 里

async def test_wecom_first_reply_discloses_ai_splits_and_is_scheduled(database, ctx):
    cid = _customer(database, ctx, "小红书来的")
    runner = BotRunner(scripted_model([([], "同学你好哦\n\n是要做汇报 PPT 吗，大概讲多久、几篇呀")]))
    run = await runner.run_for_customer(database, ctx, cid)
    assert "【判断】客人这几句是：打招呼" in run.situation and "【这一轮最多问一件】讲多久、几篇" in run.situation
    rows = _rows(database, cid)
    texts = [r.text for r in rows]
    assert texts[0] == KB.disclosure.text and "disclosure" in rows[0].reasons  # 开头表明身份
    assert len(rows) == 2  # 微信客服默认最多 2 条：表明身份 + 合成一条
    assert "同学你好哦" in texts[1] and "几篇呀" in texts[1]
    assert all(r.send_after is not None for r in rows) and rows[1].send_after > rows[0].send_after
    with database.session() as db:  # 没到点不发
        assert service.approved_outbox(db) == []
        due = service.approved_outbox(db, now=utcnow() + timedelta(minutes=5))
        assert [o.id for o in due] == [r.id for r in rows]
    # 第二次说话不再表明身份
    with database.session() as db:
        for o in db.scalars(select(Outbox).where(Outbox.customer_id == cid)):
            service.mark_sent(db, o)
        service.receive_text(db, ctx, db.get(Customer, cid), "20分钟，一篇")
    runner2 = BotRunner(scripted_model([([], "OK 的\n\n你哪天汇报呀")]))
    await runner2.run_for_customer(database, ctx, cid)
    new = _rows(database, cid)[2:]
    assert [r.text for r in new] == ["OK 的", "你哪天汇报呀"]


async def test_web_chat_no_disclosure_line_up_to_three_messages(database, ctx):
    cid = _customer(database, ctx, "多少钱呀", channel="web", key="key-rx-web-0123456789")
    runner = BotRunner(scripted_model([([], "按讲多久和几篇定\n\n你大概讲多久呀\n\n几篇也说下")]))
    await runner.run_for_customer(database, ctx, cid)
    assert [r.text for r in _rows(database, cid)] == ["按讲多久和几篇定", "你大概讲多久呀", "几篇也说下"]


async def test_new_message_withdraws_unsent_reply(database, ctx):
    cid = _customer(database, ctx, "多少钱")
    runner = BotRunner(scripted_model([([], "你大概讲多久、几篇呀"), ([], "15 分钟一篇的话我给你算下")]))
    await runner.run_for_customer(database, ctx, cid)
    first = [r for r in _rows(database, cid) if r.author == "bot"]
    with database.session() as db:
        service.receive_text(db, ctx, db.get(Customer, cid), "15分钟的，一篇")
    await runner.run_for_customer(database, ctx, cid)
    rows = {r.id: r for r in _rows(database, cid)}
    assert all(rows[r.id].status == "rejected" and "重新回" in rows[r.id].error for r in first)
    assert any(r.text == "15 分钟一篇的话我给你算下" and r.status == "approved" for r in rows.values())


async def test_banned_reply_is_rewritten_by_model(database, ctx):
    seen = {"retry": 0}

    def fn(messages, info: AgentInfo):
        last = messages[-1]
        feedback = " ".join(str(p.content) for p in last.parts if isinstance(p, (RetryPromptPart, UserPromptPart)))
        if len(messages) > 1 and "重写" in feedback:  # 输出校验没过：带着「哪里要改」再问一次
            seen["retry"] += 1
            assert "亲" in feedback and "希望对你有帮助" in feedback
            return ModelResponse(parts=[TextPart("收到啦，讲多久、几篇呀")])
        return ModelResponse(parts=[TextPart("亲，好的呢，希望对你有帮助")])

    cid = _customer(database, ctx, "在吗", channel="web", key="key-rx-web2-0123456789")
    await BotRunner(FunctionModel(fn)).run_for_customer(database, ctx, cid)
    rows = _rows(database, cid)
    assert seen["retry"] == 1 and [r.text for r in rows] == ["收到啦，讲多久、几篇呀"]
    assert any("重写过" in x for x in rows[0].reasons)


async def test_handoff_gives_wechat_line_and_mutes_bot(database, ctx, notifier):
    cid = _customer(database, ctx, "你们这是骗人吧，我要投诉")
    runner = BotRunner(scripted_model([([("send_owner_wechat", {"reason": "投诉", "detail": "客人说骗人"})],
                                        "这个负责人直接跟你对更快\n\n负责人微信：15068998671，同号")]))
    run = await runner.run_for_customer(database, ctx, cid)
    assert "15068998671" in run.tool_calls[0]["result"] and "不再回" not in run.tool_calls[0]["result"]
    assert "【判断】客人这几句是：要找负责人、不满" in run.situation
    with database.session() as db:
        assert db.get(Customer, cid).human_takeover is True
    assert any("交还机器人" in s for s in notifier.sent)
    assert _rows(database, cid)[-1].asset == "owner_qr"


async def test_progress_question_gets_a_filler_first(database, ctx):
    with database.session() as db:
        c, o = claimed(db, ctx, name="进度", channel="web")
        o.started_at = utcnow()
        cid = c.id
        service.receive_text(db, ctx, c, "ppt做好了嘛")
    runner = BotRunner(scripted_model([([("check_progress", {})], "在做了，今晚九点前先发你水印版")]))
    await runner.run_for_customer(database, ctx, cid)
    rows = [r for r in _rows(database, cid) if r.author == "bot"]
    assert rows[0].text in KB.style.fillers and "filler" in rows[0].reasons
    assert rows[1].text.startswith("在做了") and rows[1].send_after > rows[0].send_after


# ---------------------------------------------------------------- 后台

def test_admin_reception_kb_edit_validate_and_try(settings, notifier, tmp_path):
    app = make_app(settings, notifier, tmp_path)
    with TestClient(app) as c:
        assert c.get("/api/admin/reception").status_code == 401
        c.post("/api/auth/login", json={"password": TEST_PASSWORD})
        kb = c.get("/api/admin/reception").json()["kb"]
        assert "AI" in kb["disclosure"]["text"] and kb["owner"]["wechat"]
        kb["disclosure"]["text"] = "同学你好，我是 AI 助手小鱼，回复由 AI 生成"
        kb["rhythm"]["first_max_s"] = 30
        r = c.put("/api/admin/reception", json={"kb": kb})
        assert r.status_code == 200 and r.json()["kb"]["disclosure"]["text"].startswith("同学你好") and r.json()["kb"]["rhythm"]["first_max_s"] == 30
        bad = {**kb, "disclosure": {**kb["disclosure"], "text": "同学你好，我是小鱼"}}
        assert c.put("/api/admin/reception", json={"kb": bad}).status_code == 400
        t = c.post("/api/admin/reception/try", json={"text": "你是机器人吗", "reply": "亲，我是真人\n\n有事说"}).json()
        assert t["intents"][0]["id"] == "ask_bot" and t["how"] == "keyword"
        assert len(t["reply"]) == 2 and t["reply"][0]["after_s"] >= 4 and any("真人" in p for p in t["problems"])
