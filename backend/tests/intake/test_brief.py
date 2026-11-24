"""需求卡（docs/任务单/09_需求引导_方案.md）：没确认不开工、代确认留痕、确认后又改要重新确认、确认卡由代码拼（不调模型）、
选项和默认值从设置读、事实写回订单、旧材料标「参考」不算必交、2 小时没确认只提醒一次。"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.db import utcnow
from app.core.events import Event
from app.core.nodes import NodeCall, run_node
from app.intake import brief, flow, service
from app.intake.models import Order
from tests.intake.helpers import PDF_BYTES, claimed, confirm_brief, make_ctx, ready


@pytest.fixture
def ctx(tmp_path, notifier):
    return make_ctx(tmp_path, notifier)


def _defaults(db) -> dict:
    s = brief.load_settings(db)
    return {q.key: {"choice": brief.DEFAULT_CHOICE} for q in s.questions if not q.optional}


def test_no_making_without_brief_confirmed(database, ctx):
    """资料齐了、需求卡没确认 → 停在收资料（开工条件最后一行写明）；客人点「对，开工」→ 制作中。"""
    with database.session() as db:
        _, o = ready(db, ctx, name="没确认", brief=False)
        assert o.stage == "collecting" and o.started_at is None and o.queued_at is None
        last = service.conditions_for(db, o)[-1]
        assert (last.key, last.ok) == ("brief", False) and "还没填" in last.detail
        flow.ensure_nodes()
        assert run_node("gate.brief_confirmed", NodeCall(db, ctx, "t", o.id), {"order_id": o.id}).exit == "wait"
        with pytest.raises(ValueError, match="还有没选的"):
            brief.confirm(db, ctx, o, method="customer", by="customer")
        brief.save(db, ctx, o, _defaults(db))
        brief.confirm(db, ctx, o, method="customer", by="customer")
        assert o.stage == "making" and o.started_at is not None
        ev = db.scalar(select(Event).where(Event.type == "intake.brief_confirmed"))
        assert ev.content["method"] == "customer" and ev.content["by"] == "customer" and "场合：" in ev.content["card"]
        moves = [e.content["to_step"] for e in db.scalars(select(Event).where(Event.type == "intake.stage").order_by(Event.id))]
        assert moves[-3:] == ["brief", "gate", "making"]  # 收资料 → 需求卡确认了没有 → 开工判断 → 制作中


def test_proxy_confirm_needs_reason_and_is_marked(database, ctx, tmp_path):
    """客人在聊天里口头说「可以」：负责人代确认，必须写依据；事件、确认卡、开单说明里都写明是代确认。"""
    with database.session() as db:
        _, o = ready(db, ctx, name="代确认", brief=False)
        with pytest.raises(ValueError, match="依据"):
            brief.confirm(db, ctx, o, method="proxy", by="edison", note=" ")
        brief.confirm(db, ctx, o, method="proxy", by="edison", note="客人在聊天里说「可以，就这样」")  # 没选的按推荐
        assert o.stage == "making"
        b = brief.get(db, o)
        assert b.confirm_method == "proxy" and b.confirmed_by == "edison" and "（按推荐）" in b.card_text
        ev = db.scalar(select(Event).where(Event.type == "intake.brief_confirmed"))
        assert (ev.content["method"], ev.content["by"]) == ("proxy", "edison") and "可以，就这样" in ev.content["note"]
        req = (tmp_path / "inbox" / "代确认" / "要求.md").read_text(encoding="utf-8")
        assert "客人的需求和偏好：" in req and "负责人代确认（依据：客人在聊天里说「可以，就这样」）" in req


def test_edit_after_confirm_needs_reconfirm(database, ctx):
    """认领后先确认了需求卡、后来又改了一项（版本变了）→ 算没确认，资料齐了也不开工；再点一次才开工。"""
    with database.session() as db:
        c, o = claimed(db, ctx, name="又改了")
        confirm_brief(db, ctx, o)
        assert brief.confirmed(db, o)
        brief.save(db, ctx, o, {"audience": {"choice": "committee"}})
        assert not brief.confirmed(db, o)
        assert "又改了" in brief.condition(db, o)[1]
        service.receive_text(db, ctx, c, "组会")
        service.receive_file(db, ctx, c, filename="p.pdf", data=PDF_BYTES)[1].purpose = "论文"
        service.update_order(db, ctx, o, {"present_date": utcnow().date() + timedelta(days=9)})
        assert o.stage == "collecting" and o.started_at is None
        with pytest.raises(ValueError, match="刚改过"):  # 客人看的是旧确认卡：版本对不上不收
            brief.confirm(db, ctx, o, method="customer", by="customer", version=1)
        brief.confirm(db, ctx, o, method="customer", by="customer", version=brief.get(db, o).version)
        assert o.stage == "making"
        with pytest.raises(ValueError, match="已经开工"):  # 开工以后不能再改
            brief.save(db, ctx, o, {"audience": {"choice": "lab"}})


def test_card_built_by_code_template_without_model(database, ctx, monkeypatch):
    """确认卡由代码按模板拼：模型一被调就报错，照样拼得出、确认得了；按推荐的写明；时长不能超出档位。"""
    import pydantic_ai

    import app.intake.bot as bot

    def boom(*a, **k):
        raise AssertionError("需求卡这条链路调了模型")

    monkeypatch.setattr(pydantic_ai.Agent, "run", boom)
    monkeypatch.setattr(pydantic_ai.Agent, "run_sync", boom)
    monkeypatch.setattr(bot.BotRunner, "run_for_customer", boom)
    with database.session() as db:
        _, o = claimed(db, ctx, name="模板", sku="regular-p1")
        with pytest.raises(ValueError, match="最多 25 分钟"):
            brief.save(db, ctx, o, {"minutes": {"choice": "30"}})
        brief.save(db, ctx, o, {**_defaults(db), "occasion": {"choice": "midterm"}, "minutes": {"choice": "20"},
                                "focus": {"choice": ["method", "story"], "note": "导师上次问为什么用这个范式"},
                                "avoid": {"choice": ["wordy", "animation"]}, "style": {"choice": "n10"}})
        lines = {x.key: x.value for x in brief.card_lines(db, o)}
        assert lines["occasion"] == "中期" and lines["minutes"] == "20 分钟" and lines["audience"] == "导师和同门（按推荐）"
        assert lines["focus"] == "方法讲明白、一条线讲下来；补充：导师上次问为什么用这个范式"
        assert lines["avoid"] == "字太多、动画" and lines["style"] == "最像「表格对照，字少留白多」" and lines["refs"] == "没传"
        brief.save(db, ctx, o, {"minutes": {"choice": brief.DEFAULT_CHOICE}})
        assert dict((x.key, x.value) for x in brief.card_lines(db, o))["minutes"] == "25 分钟（按推荐：常规档上限）"
        brief.confirm(db, ctx, o, method="customer", by="customer")
        assert brief.confirmed(db, o)


def test_facts_written_back_explicit_wins_default_fills_blank(database, ctx):
    """确认后写回订单：客人明确选的直接写（盖掉助手猜的）；按推荐的只填空着的；时长算客人点过头。"""
    with database.session() as db:
        _, o = claimed(db, ctx, name="写回")
        service.update_order(db, ctx, o, {"occasion": "组会文献", "language": "英文"})
        brief.save(db, ctx, o, {**_defaults(db), "occasion": {"choice": "proposal"}})
        brief.confirm(db, ctx, o, method="customer", by="customer")
        assert o.occasion == "开题"  # 明确选的
        assert o.language == "英文"  # 按推荐（中文）不盖助手记过的
        assert (o.duration_min, o.duration_default, o.duration_confirmed) == (25, True, True)


def test_options_and_defaults_come_from_settings(database, ctx):
    """选项和默认值从设置读：后台改了选项的字、推荐值，确认卡跟着变；推荐值不是选项之一的存不进去。"""
    with database.session() as db:
        s = brief.load_settings(db)
        aud = s.question("audience")
        aud.options[1].label = "答辩委员会"
        aud.default = "committee"
        brief.save_settings(db, s)
        _, o = claimed(db, ctx, name="设置")
        brief.save(db, ctx, o, _defaults(db))
        assert dict((x.key, x.value) for x in brief.card_lines(db, o))["audience"] == "答辩委员会（按推荐）"
        v = brief.view(db, ctx, o)
        assert [x["label"] for x in v["settings"]["questions"][1]["options"]][1] == "答辩委员会"
        bad = s.model_dump()
        bad["questions"][1]["default"] = "nobody"
        with pytest.raises(ValueError):
            brief.BriefSettings.model_validate(bad)


def test_reference_files_are_not_required_materials(database, ctx):
    """需求卡里传的旧材料收进这单资料、标「参考」，不顶必交的论文；模板标「模板」。"""
    with database.session() as db:
        c, o = claimed(db, ctx, name="参考")
        confirm_brief(db, ctx, o)
        service.update_order(db, ctx, o, {"occasion": "组会文献", "duration_min": 15,
                                          "present_date": utcnow().date() + timedelta(days=9)})
        brief.add_file(db, ctx, o, filename="上次组会.pptx", data=b"PK..", kind="ref")
        brief.add_file(db, ctx, o, filename="组里模板.potx", data=b"PK..", kind="template")
        assert [f.purpose for f in brief.brief_files(db, o)] == ["参考", "模板"]
        assert o.stage == "collecting"  # 论文还没来
        assert "论文" in service.collect_for(db, o, ctx).ask_text
        lines = dict((x.key, x.value) for x in brief.card_lines(db, o))
        assert lines["refs"].startswith("1 份（上次组会.pptx")


def test_reminds_once_after_two_hours_never_auto_starts(database, ctx):
    """认领后 2 小时没确认：列进提醒一次；提醒过就不再列；负责人发回重确认后重新起算；从不自动开工。"""
    with database.session() as db:
        _, o = ready(db, ctx, name="提醒", brief=False)
        assert brief.due_reminders(db) == []  # 刚认领
        o.claimed_at = utcnow() - timedelta(hours=3)
        assert [x.id for x in brief.due_reminders(db)] == [o.id]
        brief.mark_reminded(db, o)
        assert brief.due_reminders(db) == []
        assert o.stage == "collecting"  # 不自动开工
        brief.send_back(db, ctx, o, {"audience": {"choice": "cross"}}, note="按你说的改成跨领域")
        assert brief.due_reminders(db) == []
        assert [x.id for x in brief.due_reminders(db, utcnow() + timedelta(hours=2, minutes=1))] == [o.id]
        assert db.get(Order, o.id).stage == "collecting"
