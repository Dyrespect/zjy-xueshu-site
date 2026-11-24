"""流程引擎：流程是数据（Pydantic 校验）、只按连线走、非法手动推进拒绝、进来就跑的节点、条件分岔、循环、不只认订单。

scripts/check.py 规矩 9 要求这里有 test_illegal_manual_push_rejected。
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.core.events import Event
from app.intake import flow
from app.intake.flow import Flow, StageError
from app.intake.models import Order
from tests.intake.helpers import claimed, confirm_brief, make_ctx, package, ready


@pytest.fixture
def ctx(tmp_path, notifier):
    return make_ctx(tmp_path, notifier)


def _flow(**over):
    data = {
        "key": "tiny", "name": "小流程", "description": "测试用", "start": "a",
        "stages": [{"key": "a", "label": "甲"}, {"key": "b", "label": "乙"}, {"key": "z", "label": "终"}],
        "steps": [
            {"id": "a", "stage": "a", "node": "notify.feishu", "edges": [{"on": "go", "to": "b"}]},
            {"id": "b", "stage": "b", "node": "notify.feishu", "edges": [{"on": "back", "to": "a", "loop": True}, {"on": "end", "to": "z"}]},
            {"id": "z", "stage": "z", "node": "notify.feishu", "terminal": True},
        ],
    }
    data.update(over)
    return data


def test_flow_definition_is_validated():
    Flow.model_validate(_flow())
    bad = _flow()
    bad["steps"][1]["edges"][0]["loop"] = False  # 回到前面的状态没标 loop
    with pytest.raises(ValidationError, match="loop"):
        Flow.model_validate(bad)
    bad = _flow()
    bad["steps"][0]["edges"][0]["to"] = "nowhere"
    with pytest.raises(ValidationError, match="不存在的步骤"):
        Flow.model_validate(bad)
    bad = _flow()
    bad["steps"][2]["edges"] = [{"on": "x", "to": "a", "loop": True}]
    with pytest.raises(ValidationError, match="终点"):
        Flow.model_validate(bad)
    bad = _flow()
    bad["steps"][0]["edges"] = [{"on": "exit:ok", "to": "b"}]  # 没有 enter 却接出口
    with pytest.raises(ValidationError, match="enter"):
        Flow.model_validate(bad)


def test_default_flow_loads_and_every_node_is_registered():
    f = flow.load_flow("paid_custom")
    assert f.subject == "order" and f.start == "paid"
    assert flow.check_nodes(f) == []
    labels = [s.label for s in f.stages]
    assert labels == ["已付款", "已认领", "收资料", "制作中", "已交水印版", "修改中", "已完成", "已交付", "作废"]
    # 已完成之后不能作废
    for sid in ("confirm", "completed", "delivered", "revising_after"):
        assert all(e.on != "voided" for e in f.step(sid).edges)


def test_illegal_manual_push_rejected(database, ctx):
    """后台手动推不是 manual 的连线、或当前步骤没有的连线 → StageError，状态不动、不记事件。"""
    with database.session() as db:
        _, o = claimed(db, ctx)
        assert o.stage == "claimed"
        before = db.scalar(select(Event.id).order_by(Event.id.desc()).limit(1))
        for bad in ("changed", "delivered", "completed", "start_now", "final_ready", "voided"):
            with pytest.raises(StageError):
                flow.push(db, ctx, o, bad, by="edison", why="试试")
        assert o.stage == "claimed" and o.flow_step == "claimed"
        assert db.scalar(select(Event.id).order_by(Event.id.desc()).limit(1)) == before


def test_events_without_edge_are_ignored_idempotently(database, ctx):
    with database.session() as db:
        _, o = claimed(db, ctx)
        assert flow.emit(db, ctx, o, "delivered", by="system") is False  # 这一步不认：不动
        assert flow.emit(db, ctx, o, "completed", by="system") is False
        assert o.stage == "claimed"


def test_walk_through_enter_nodes_records_each_hop(database, ctx, tmp_path):
    with database.session() as db:
        c, o = ready(db, ctx, name="走一遍")
        # 资料齐 + 今天有名额：认领 → 收资料（判断）→ 制作中（交接）
        assert o.stage == "making" and o.started_at is not None
        hops = [e.content for e in db.scalars(select(Event).where(Event.type == "intake.stage", Event.subject == f"order:{o.id}")
                                               .order_by(Event.id))]
        assert [h["to"] for h in hops][:2] == ["paid", "claimed"]
        assert hops[-1]["to_step"] == "making" and all(h["by"] for h in hops)
        package(db, ctx, o)
        assert o.stage == "watermarked" and o.delivery_round == 1  # 出水印图 → 发布 → 已交水印版（同一趟）
        # 修改循环：已交水印版 → 修改中 → 交了新的一版 → 回到已交水印版
        from app.intake import service

        service.submit_revision(db, ctx, o, items=[{"page": 1, "text": "标题大一号"}], source="bot")
        assert o.stage == "revising"
        package(db, ctx, o)
        assert o.stage == "watermarked" and o.delivery_round == 2


def test_bounce_through_gate_is_not_logged_as_a_move(database, ctx):
    with database.session() as db:
        c, o = claimed(db, ctx, name="来回")
        from app.intake import service

        service.receive_text(db, ctx, c, "组会汇报")
        service.update_order(db, ctx, o, {"occasion": "组会文献"})  # claimed → gate → collecting（还缺东西）
        assert o.stage == "collecting"
        n = db.scalar(select(Event.id).order_by(Event.id.desc()).limit(1))
        service.update_order(db, ctx, o, {"title": "题目"})  # collecting → gate → collecting：不算换步骤
        moves = list(db.scalars(select(Event).where(Event.id > n, Event.type == "intake.stage")))
        assert moves == []


def test_manual_options_come_from_flow_and_push_works(database, ctx):
    with database.session() as db:
        c, o = claimed(db, ctx, name="现在开工")
        from app.intake import service

        service.update_order(db, ctx, o, {"occasion": "组会文献"})
        opts = flow.manual_options(o)
        assert [x["on"] for x in opts] == ["start_now"] and "需求卡" in opts[0]["label"]
        with pytest.raises(ValueError, match="需求卡还没确认"):  # 09 需求引导：没确认不开工，现在开工也一样
            service.start_now(db, ctx, o)
        assert o.stage == "collecting" and o.started_at is None
        confirm_brief(db, ctx, o, method="proxy", note="客人在聊天里说可以")
        service.start_now(db, ctx, o)  # 条件不齐也照做（事件里记下当时缺什么）
        assert o.stage == "making" and o.started_at is not None


def test_conditions_pick_the_branch(database, ctx, tmp_path, monkeypatch):
    """条件分岔：发布那一步，平台早就确认收货了 → 直接走到已完成、放最终版；否则 → 已交水印版。"""
    with database.session() as db:
        _, a = ready(db, ctx, name="平台早完成", platform="xy")
        from app.intake import orders

        assert orders.mark_completed(db, ctx, a, source="edison", by="edison") == "recorded"
        assert a.platform_completed_at is not None and a.stage == "making"
        package(db, ctx, a)
        assert a.stage == "delivered" and a.finished_at is not None  # 钱已安全：直接放最终版
        _, b = ready(db, ctx, name="普通", platform="fk")
        package(db, ctx, b)
        assert b.stage == "watermarked"


def test_engine_is_not_only_for_orders(database, ctx, tmp_path):
    """别的对象（如图库访客）登记成 subject，就能走自己的流程；订单只是其中一种。"""
    from dataclasses import dataclass, field
    from datetime import datetime

    @dataclass
    class Visitor:
        id: int = 7
        flow_key: str = ""
        flow_step: str = ""
        stage: str = ""
        stage_at: datetime | None = None
        updated_at: datetime | None = None
        tier: str = "a"

    flow.register_subject(flow.SubjectSpec("visitor_test", Visitor))
    d = tmp_path / "flows"
    d.mkdir()
    data = _flow(key="visitor_tiny", subject="visitor_test")
    data["steps"][1]["edges"].insert(0, {"on": "end", "to": "z", "when": [{"field": "tier", "op": "eq", "value": "vip"}]})
    (d / "visitor_tiny.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    flow.register_flow_dir(d)
    with database.session() as db:
        v = Visitor()
        flow.start(db, ctx, v, "visitor_tiny", by="system")
        assert (v.flow_step, v.stage) == ("a", "a")
        assert flow.emit(db, ctx, v, "go", by="system") and v.stage == "b"
        assert flow.emit(db, ctx, v, "back", by="system") and v.stage == "a"  # 循环
        flow.emit(db, ctx, v, "go", by="system")
        assert flow.emit(db, ctx, v, "end", by="system") and v.stage == "z"  # 条件不满足走第二条
        ev = db.scalar(select(Event).where(Event.type == "flow.stage").order_by(Event.id.desc()).limit(1))
        assert ev.subject == "visitor_test:7"
        with pytest.raises(StageError):
            flow.start(db, ctx, Order(), "visitor_tiny", by="system")  # 流程是给访客的，订单不能走


def test_engine_loads_every_module_nodes_without_app():
    """不起 app 的脚本读流程：引擎自己把各模块（交付的 deliver.* 等）的节点登记上，不报「没登记的节点」。
    另起一个干净的进程跑（测试进程里 conftest 已经全部登记过了，看不出来）。"""
    import subprocess
    import sys
    from pathlib import Path

    code = ("from app.intake import flow; f = flow.load_flow('paid_custom'); "
            "from app.core.nodes import has_node; assert has_node('deliver.watermark') and has_node('gate.final'); print('ok')")
    out = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0 and out.stdout.strip().endswith("ok"), out.stderr[-800:]


def test_add_node_loader_replaces_discovery():
    calls = []
    saved = (list(flow._NODE_LOADERS), flow._nodes_loaded)
    try:
        flow._NODE_LOADERS.clear()
        flow.add_node_loader(lambda: calls.append("x"))
        flow.ensure_nodes()
        flow.ensure_nodes()  # 第二次不再加载
        assert calls == ["x"]
    finally:
        flow._NODE_LOADERS[:] = saved[0]
        flow._nodes_loaded = saved[1]
