"""后台：节点目录（/api/admin/nodes，要登录）。由注册表自动生成，列出所有节点说明卡和流程定义（顶层设计第十八节）。

像前端的「区块陈列页」：Edison 能直接看每个节点做什么、用什么技术、输入输出、出口、配置、可替换点、归谁。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.core.nodes import CATEGORIES, all_cards, card_json
from app.intake import flow

router = APIRouter(prefix="/nodes", tags=["admin"])


@router.get("")
def nodes() -> dict[str, Any]:
    flow.ensure_nodes()
    cards = [card_json(c) for c in all_cards()]
    used: dict[str, list[str]] = {}
    flows = []
    for f in flow.all_flows():
        steps = []
        for s in f.steps:
            for nid in filter(None, (s.node, s.enter)):
                used.setdefault(nid, [])
                if f.key not in used[nid]:
                    used[nid].append(f.key)
            steps.append({
                "id": s.id, "stage": s.stage, "stage_label": f.stage_label(s.stage), "node": s.node, "enter": s.enter,
                "label": s.label, "terminal": s.terminal,
                "edges": [{"on": e.on, "to": e.to, "manual": e.manual, "loop": e.loop, "label": e.label,
                           "when": [c.model_dump() for c in e.when]} for e in s.edges],
            })
        flows.append({"key": f.key, "subject": f.subject, "name": f.name, "description": f.description, "start": f.start,
                      "stages": [s.model_dump() for s in f.stages], "steps": steps})
    for c in cards:
        c["flows"] = used.get(c["id"], [])
    return {"categories": [c for c in CATEGORIES if any(x["category"] == c for x in cards)], "nodes": cards, "flows": flows}
