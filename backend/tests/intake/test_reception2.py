"""接待机器人第二轮（Edison 11-19 审了审核页后改的，docs/任务单/12_接待机器人_设计.md 第十五节）：
- 开头只用他定的那一句；
- 时间只照工具算的说：没调报价、查进度就说「今晚能给」「明天就能交」→ 重写；
- 超出最长一档（60 分钟）或超过 5 篇：直接转负责人，不报价不硬接（规则直接定，不等模型）；
- 想看样张：小鱼在聊天里直接发带水印的 PDF；样张后台可换（上传接口不出存储位置）；
- 「注意事项」「发卡站」这类词换成人话。"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.db import Database
from app.intake import service
from app.intake.bot import BotRunner, build_agent, load_rules
from app.intake.config_store import load_config, terms_message
from app.intake.models import Customer, FileRecord, Outbox
from app.intake.reception import intent, kb as rkb, style
from tests.conftest import TEST_PASSWORD
from tests.intake.helpers import make_app, make_ctx, scripted_model

KB = rkb.load(None)
PDF = b"%PDF-1.4\n% sample\n%%EOF\n"


@pytest.fixture
def ctx(tmp_path, notifier):
    qr = tmp_path / "owner.jpg"
    qr.write_bytes(b"\xff\xd8\xff fake jpg")
    return make_ctx(tmp_path, notifier, OWNER_WECHAT_QR=qr)


def _customer(database: Database, ctx, text: str, *, channel="web", key="key-rx2-0123456789") -> int:
    with database.session() as db:
        c = service.get_or_create_customer(db, channel, key, nickname="同学")
        service.receive_text(db, ctx, c, text)
        return c.id


def test_disclosure_is_his_one_sentence_and_welcome_follows():
    assert KB.disclosure.text == "同学你好呀，这里是 PsyEngine，我是 AI 助手小鱼，下面的回复由 AI 生成，负责人随时看记录与接手"
    from app.intake.config_store import DEFAULT_CONFIG

    assert DEFAULT_CONFIG["welcome_text"].startswith(KB.disclosure.text)
    assert DEFAULT_CONFIG["entry_texts"]["welcome_plain"].startswith(KB.disclosure.text)


@pytest.mark.parametrize("text,over", [
    ("我要讲一个半小时，8篇文献，能做吗", True), ("讲 90 分钟", True), ("两个小时左右", True), ("一个多小时", True),
    ("6 篇文献", True), ("讲二十五分钟，三篇", False), ("半小时，一篇", False), ("60 分钟，5 篇", False),
])
def test_over_limit_goes_straight_to_owner(text, over):
    r = intent.classify_rules(KB, [text], ["text"], limits=(60, 5))
    assert (r.intents == ["special"] and r.note.startswith("超出档位")) is over, r


def test_no_invented_time_and_no_price_when_over_limit():
    assert style.problems("今晚就能给你", KB, time_checked=False)
    assert style.problems("明天上午就能发你一版", KB, time_checked=False)
    assert not style.problems("明天上午就能发你一版", KB, time_checked=True)  # 工具算过的可以说
    assert not style.problems("常规档开工后 7 小时内交水印版", KB, time_checked=False)
    assert style.problems("这个要 79.9", KB, no_price=True) and not style.problems("这个超出档了", KB, no_price=True)


async def test_over_limit_turn_hands_off_and_never_quotes(database, ctx):
    cid = _customer(database, ctx, "我要讲一个半小时，8篇文献，能做吗", channel="wecom", key="key-rx2-wecom-0123456789")
    runner = BotRunner(scripted_model([([("send_owner_wechat", {"reason": "档位", "detail": "90 分钟 8 篇"})],
                                        "这个超出我们现在的档了，负责人直接跟你对一下更快\n\n负责人微信 15068998671（同号）")]))
    run = await runner.run_for_customer(database, ctx, cid)
    assert "【超出档位】讲 90 分钟，超过最长一档 60 分钟；8 篇，超过最多 5 篇" in run.situation
    assert "【判断】客人这几句是：特殊、复杂" in run.situation
    with database.session() as db:
        assert db.get(Customer, cid).human_takeover is True


async def test_invented_time_gets_rewritten(database, ctx):
    from pydantic_ai.messages import ModelResponse, TextPart, UserPromptPart
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    seen = {"retry": 0}

    def fn(messages, info: AgentInfo):
        fb = " ".join(str(p.content) for p in messages[-1].parts if isinstance(p, UserPromptPart))
        if len(messages) > 1 and "重写" in fb:
            seen["retry"] += 1
            return ModelResponse(parts=[TextPart("讲多久、几篇呀，我按标准时限给你算下")])
        return ModelResponse(parts=[TextPart("今晚就能给你")])

    cid = _customer(database, ctx, "今晚能出吗")
    await BotRunner(FunctionModel(fn)).run_for_customer(database, ctx, cid)
    with database.session() as db:
        texts = [o.text for o in db.scalars(select(Outbox).where(Outbox.customer_id == cid))]
    assert seen["retry"] == 1 and texts == ["讲多久、几篇呀，我按标准时限给你算下"]


def _upload_sample(database, ctx, slot=0):
    with database.session() as db:
        key = ctx.storage.save(PDF, folder="reception/samples", filename="样张1.pdf")
        kb = rkb.load(db)
        samples = [s.model_dump() for s in kb.samples]
        samples[slot].update(filename="样张1.pdf", storage_key=key, size=len(PDF))
        rkb.save(db, rkb.ReceptionKB.model_validate({**kb.model_dump(mode="json"), "samples": samples}))


async def test_sample_pdf_sent_as_file_and_not_resent_within_a_day(database, ctx):
    _upload_sample(database, ctx)
    cid = _customer(database, ctx, "有做好的样例可以先看看吗")
    runner = BotRunner(scripted_model([([("send_sample", {"which": 1})], "发你一份我们做的组会稿，带水印的"),
                                       ([("send_sample", {"which": 1})], "上面那份就是")]))
    run = await runner.run_for_customer(database, ctx, cid)
    assert "【样张】1. 《从常规化验中识别抑郁线索》" in run.situation and "公众号 PsyEngine 每天" in run.situation
    with database.session() as db:
        obs = list(db.scalars(select(Outbox).where(Outbox.customer_id == cid).order_by(Outbox.id)))
        assert [(o.kind, o.category) for o in obs] == [("text", "一般回复"), ("file", "样张")]
        f = db.get(FileRecord, obs[1].file_id)
        assert f.role == "sample" and f.order_id is None and f.content_type == "application/pdf"
        for o in obs:
            service.mark_sent(db, o)
        service.receive_text(db, ctx, db.get(Customer, cid), "再发一次")
    run2 = await runner.run_for_customer(database, ctx, cid)
    assert "24 小时内都发过了" in run2.tool_calls[0]["result"]


def test_send_sample_in_visitor_tools_and_plain_words():
    names = {t.name for t in build_agent(None, "visitor_qa")._function_toolset.tools.values()}
    assert "send_sample" in names
    rules = load_rules()
    assert "注意事项" not in rules and "发卡" not in rules
    from app.intake.config_store import DEFAULT_PAYMENT_TEXT, BizConfig, DEFAULT_CONFIG

    assert "发卡" not in DEFAULT_PAYMENT_TEXT
    msg = terms_message(BizConfig.model_validate(DEFAULT_CONFIG))
    assert "先说清楚的几条" in msg and "注意事项：" not in msg


def test_admin_uploads_sample_without_exposing_storage(settings, notifier, tmp_path):
    app = make_app(settings, notifier, tmp_path)
    with TestClient(app) as c:
        c.post("/api/auth/login", json={"password": TEST_PASSWORD})
        r = c.post("/api/admin/reception/samples/0", files={"file": ("样张1.pdf", io.BytesIO(PDF), "application/pdf")},
                   data={"title": "从常规化验中识别抑郁线索"})
        assert r.status_code == 200
        s0 = r.json()["kb"]["samples"][0]
        assert s0["ready"] and s0["filename"] == "样张1.pdf" and "storage_key" not in s0
        assert c.post("/api/admin/reception/samples/0", files={"file": ("x.txt", io.BytesIO(b"hello"), "text/plain")}).status_code == 400
        assert c.post("/api/admin/reception/samples/5", files={"file": ("x.pdf", io.BytesIO(PDF), "application/pdf")}).status_code == 400
        kb = c.get("/api/admin/reception").json()["kb"]
        kb["samples"][0]["about"] = "组会文献汇报，16 页"
        assert c.put("/api/admin/reception", json={"kb": kb}).status_code == 200  # 改说明不丢文件
        from app.intake.runtime import get_runtime

        with get_runtime(app).database.session() as db:
            got = rkb.load(db).samples[0]
            assert got.ready and got.about == "组会文献汇报，16 页"
