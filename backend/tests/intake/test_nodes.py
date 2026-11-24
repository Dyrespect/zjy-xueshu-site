"""节点注册表：说明卡缺一项不能注册；run_node 按说明卡校验输入、出口、输出；接单这一块的节点都登记了；节点目录接口。"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from app.core.nodes import NodeCall, NodeCard, NodeError, NodeExit, NodeResult, all_cards, card_json, register, run_node
from app.intake import flow


class In(BaseModel):
    n: int


class Out(BaseModel):
    doubled: int


def _card(**over):
    base = dict(id="test.double", name="翻倍", description="测试用：把数翻倍，看注册表的校验。", category="运营",
                tech=["Python"], input_model=In, output_model=Out,
                exits=[NodeExit(key="ok", label="好了", kind="ok")], config=["无"], emits=["无"], listens=["无"],
                replaceable=["暂无"], failure="纯函数，随便重试。", owner="A", status="要新做")
    base.update(over)
    return NodeCard(**base)


@pytest.mark.parametrize("field,value", [
    ("description", ""), ("tech", []), ("exits", []), ("config", []), ("replaceable", []), ("failure", ""),
    ("category", "随便"), ("id", "NoDot"), ("input_model", dict),
])
def test_card_missing_anything_cannot_register(field, value):
    with pytest.raises(ValidationError):
        _card(**{field: value})


def test_run_node_checks_input_exit_output():
    register(_card(), lambda call, data: NodeResult(exit="ok", output=Out(doubled=data.n * 2)))
    assert run_node("test.double", NodeCall(None, None, "t"), {"n": 4}).output.doubled == 8
    with pytest.raises(NodeError, match="输入不对"):
        run_node("test.double", NodeCall(None, None, "t"), {"n": "x"})
    register(_card(id="test.bad_exit"), lambda call, data: NodeResult(exit="nope"))
    with pytest.raises(NodeError, match="出口"):
        run_node("test.bad_exit", NodeCall(None, None, "t"), {"n": 1})
    register(_card(id="test.card_only"))
    with pytest.raises(NodeError, match="还没实现"):
        run_node("test.card_only", NodeCall(None, None, "t"), {"n": 1})
    with pytest.raises(NodeError, match="没有登记"):
        run_node("test.nobody", NodeCall(None, None, "t"), {})


def test_order_hub_nodes_registered():
    flow.ensure_nodes()
    ids = {c.id for c in all_cards()}
    must = {"sku.quote", "sku.catalog", "order.create", "code.issue", "code.lookup", "order.claim", "order.void",
            "gate.ready", "intake.collect", "assistant.sales", "factory.handoff", "deliver.receive", "deliver.watermark",
            "deliver.preview", "revision.collect", "confirm.receipt", "gate.final", "deliver.sla", "notify.feishu"}
    assert must <= ids
    for c in all_cards():
        j = card_json(c)
        assert j["input"]["fields"] is not None and j["exits"] and j["tech"] and j["owner"]


def test_admin_nodes_page(client):
    from tests.conftest import TEST_PASSWORD

    client.post("/api/auth/login", json={"password": TEST_PASSWORD})
    d = client.get("/api/admin/nodes").json()
    by_id = {n["id"]: n for n in d["nodes"]}
    assert by_id["order.claim"]["category"] == "订单" and "paid_custom" in by_id["order.claim"]["flows"]
    assert by_id["gate.ready"]["runnable"] and by_id["deliver.sla"]["runnable"] and by_id["deliver.sla"]["owner"] == "E"
    paid = next(f for f in d["flows"] if f["key"] == "paid_custom")
    assert [s["id"] for s in paid["steps"]][:3] == ["paid", "claimed", "collecting"]
    assert "订单" in d["categories"]
