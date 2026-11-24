"""第一层（不调模型）：开工条件、按小时的排期、货号装不装得下、加急能不能做，全是纯函数。"""

from datetime import date, datetime, timedelta

import pytest

from app.intake import clock
from app.intake.config_store import DEFAULT_CONFIG, BizConfig
from app.intake.rules import (
    FileFact,
    OrderFacts,
    can_start,
    due_hours,
    duration_ok,
    effective_papers,
    fit_problems,
    missing_materials,
    plan_slot,
    rush_decision,
    start_conditions,
)

CFG = BizConfig.model_validate(DEFAULT_CONFIG)
TODAY = date(2026, 11, 16)  # 周一
NOW = datetime(2026, 11, 16, 14, 0, tzinfo=clock.TZ)


def facts(**kw) -> OrderFacts:
    base = dict(sku="regular-p1", tier_key="regular", band_key="p1")
    base.update(kw)
    return OrderFacts(**base)


@pytest.mark.parametrize(
    "occasion,purposes,addons,missing",
    [
        ("组会文献", [], set(), ["论文"]),
        ("组会文献", ["论文"], set(), []),
        ("组会文献", [], {"find_refs"}, []),  # 买了帮我找文献：论文我们找
        ("开题", ["论文"], set(), ["开题报告"]),
        ("中期", ["开题报告"], set(), ["进展"]),
        ("", ["论文"], set(), None),
    ],
)
def test_missing_materials(occasion, purposes, addons, missing):
    f = facts(occasion=occasion, addons=addons, files=[FileFact(i, f"f{i}.pdf", p) for i, p in enumerate(purposes)])
    assert missing_materials(f, CFG) == missing


def test_duration_default_needs_customer_nod():
    assert not duration_ok(facts())
    assert duration_ok(facts(duration_min=15))
    assert not duration_ok(facts(duration_min=15, duration_default=True))
    assert duration_ok(facts(duration_min=15, duration_default=True, duration_confirmed=True))


def test_plan_slot_hours_quota_and_work_start():
    p = plan_slot(TODAY, {}, CFG, 5, now=NOW)  # 今天开工：从现在算 5 小时
    assert (p.start_date, p.eta_date, p.hours) == (TODAY, TODAY, 5)
    late = datetime(2026, 11, 16, 22, 0, tzinfo=clock.TZ)
    assert plan_slot(TODAY, {}, CFG, 5, now=late).eta_date == TODAY + timedelta(days=1)  # 晚上开工，过了零点
    p = plan_slot(TODAY, {TODAY: 3}, CFG, 12, now=NOW)  # 今天满了 → 明天 9 点起 12 小时
    assert (p.start_date, p.eta_date) == (TODAY + timedelta(days=1), TODAY + timedelta(days=1))
    cfg = CFG.model_copy(deep=True)
    cfg.work_start_hour = 15  # 设置里可改：明天 15 点起 12 小时就到后天了
    assert plan_slot(TODAY, {TODAY: 3}, cfg, 12, now=NOW).eta_date == TODAY + timedelta(days=2)
    full = {TODAY + timedelta(days=i): 3 for i in range(CFG.queue_horizon_days + 1)}
    assert plan_slot(TODAY, full, CFG, 5, now=NOW) is None
    assert plan_slot(TODAY, full, CFG, 3, rush=True, now=NOW).start_date == TODAY  # 加急：今天，不看名额


def test_due_hours_by_tier_rush_find_refs():
    # 对客承诺 = 正常用时 + 余量 2 小时（12 设计第十五节）
    assert due_hours(facts(), CFG, rush=False) == 5 + 2
    assert due_hours(facts(), CFG, rush=True) == 3 + 2
    assert due_hours(facts(sku="xlong-p1", tier_key="xlong"), CFG, rush=False) == 12 + 2
    assert due_hours(facts(addons={"find_refs"}), CFG, rush=False) == 7 + 2


def test_rush_decision():
    ok = facts(occasion="组会文献", addons={"rush"}, files=[FileFact(1, "a.pdf", "论文")])
    assert rush_decision(ok, CFG, 0) == (True, "")
    assert rush_decision(ok, CFG, CFG.rush_daily_quota)[1] == "今天加急名额满了"
    assert "材料" in rush_decision(facts(occasion="组会文献", addons={"rush"}), CFG, 0)[1]
    assert "不开放加急" in rush_decision(facts(sku="long-p1", tier_key="long", occasion="组会文献", addons={"rush"},
                                              files=[FileFact(1, "a.pdf", "论文")]), CFG, 0)[1]
    assert rush_decision(facts(rush_by_edison=True), CFG, 99) == (True, "")  # 后台给的不看名额


def test_fit_and_effective_papers():
    assert fit_problems(facts(duration_min=20), CFG) == []
    probs = fit_problems(facts(sku="light-p1", tier_key="light", duration_min=20, page_count=25), CFG)
    assert any("常规档" in p for p in probs) and any("25 页" in p for p in probs)
    f = facts(files=[FileFact(1, "a.pdf", "论文"), FileFact(2, "b.pdf", "论文")])
    assert effective_papers(f) == (2, True) and fit_problems(f, CFG) == ["买的是1 篇，这单要讲 2 篇"]
    assert effective_papers(facts(paper_count=3)) == (3, False)
    assert effective_papers(facts()) == (None, True)


def _complete(**kw) -> OrderFacts:
    base = dict(occasion="组会文献", duration_min=15, present_date=TODAY + timedelta(days=7),
                files=[FileFact(1, "paper.pdf", "论文")], claimed=True)
    base.update(kw)
    return facts(**base)


def test_conditions_all_ok_and_keys():
    f = _complete()
    conds = start_conditions(f, CFG, plan_slot(TODAY, {}, CFG, 5, now=NOW), TODAY)
    assert [c.key for c in conds] == ["materials", "duration", "fit", "deadline", "quota"]
    assert can_start(conds)


def test_deadline_needs_buffer_day():
    f = _complete(present_date=TODAY + timedelta(days=1))  # 今天交，明天汇报：来得及
    assert can_start(start_conditions(f, CFG, plan_slot(TODAY, {}, CFG, 5, now=NOW), TODAY))
    f = _complete(present_date=TODAY)  # 今天就汇报：来不及
    bad = [c for c in start_conditions(f, CFG, plan_slot(TODAY, {}, CFG, 5, now=NOW), TODAY) if not c.ok]
    assert [c.key for c in bad] == ["deadline"]
    busy = {TODAY: 3, TODAY + timedelta(days=1): 3}
    f = _complete(present_date=TODAY + timedelta(days=2))  # 排到后天开工 → 赶不上；加急今天开工 → 赶得上
    assert not can_start(start_conditions(f, CFG, plan_slot(TODAY, busy, CFG, 5, now=NOW), TODAY))
    f = _complete(present_date=TODAY + timedelta(days=2), rush=True)
    assert can_start(start_conditions(f, CFG, plan_slot(TODAY, busy, CFG, 3, rush=True, now=NOW), TODAY))


def test_collect_result_drives_materials_condition():
    class C:
        complete, ask_text, blocker_detail = False, "还要：哪天汇报", ""

    conds = {c.key: c for c in start_conditions(_complete(), CFG, plan_slot(TODAY, {}, CFG, 5, now=NOW), TODAY, collect=C())}
    assert not conds["materials"].ok and conds["materials"].detail == "还要：哪天汇报"


def test_fit_condition_blocks_start():
    f = _complete(sku="light-p1", tier_key="light", duration_min=20)
    conds = {c.key: c for c in start_conditions(f, CFG, plan_slot(TODAY, {}, CFG, 4, now=NOW), TODAY)}
    assert not conds["fit"].ok and "常规档" in conds["fit"].detail
