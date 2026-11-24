"""插件三个外壳里的开放接口和远程 MCP（官方 SDK），版权下架后各处都不出现。要本机的找图引擎和索引。"""

from __future__ import annotations

import pytest

from tests.figures.conftest import HAS_ENGINE
from tests.gather.conftest import login

pytestmark = pytest.mark.skipif(not HAS_ENGINE, reason="本机没有找图引擎和索引")
MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def _mcp(c, mid, method, params=None):
    r = c.post("/api/gather/mcp", headers=MCP_HEADERS, json={"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}})
    assert r.status_code == 200, r.text
    return r.json()["result"]


def test_open_find_items_have_cite_and_page(gclient):
    out = gclient.get("/api/gather/open/v1/find", params={"q": "有调节的中介模型", "n": 5}).json()
    assert out["items"] and len(out["items"]) <= 5
    for it in out["items"]:
        assert it["cite"] and it["page_url"].startswith("https://tuku.example.org/figure/") and "from=ai" in it["page_url"]
        assert it["preview_url"].startswith("https://tuku.example.org/api/figures/")
    assert out["more_url"].startswith("https://tuku.example.org/search?q=")
    assert "https://app.example.org/order?from=tuku_ai" in out["note"]
    assert gclient.get("/api/gather/open/v1/figure/99999999").status_code == 404
    spec = gclient.get("/api/gather/open/v1/openapi.json").json()
    assert spec["info"]["title"] == "PsyEngine 图库插件" and "/open/v1/find" in spec["paths"]


def test_mcp_shell_with_official_sdk(gclient):
    init = _mcp(gclient, 1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                           "clientInfo": {"name": "pytest", "version": "1"}})
    assert init["serverInfo"]["title"] == "PsyEngine 图库插件"
    names = [t["name"] for t in _mcp(gclient, 2, "tools/list")["tools"]]
    assert names == ["find_figures", "figure_types", "figure_detail"]
    res = _mcp(gclient, 3, "tools/call", {"name": "find_figures", "arguments": {"q": "有调节的中介模型", "n": 3}})
    text = res["content"][0]["text"]
    assert "详情页：https://tuku.example.org/figure/" in text and "出处：" in text


def test_takedown_hides_everywhere(gclient, notifier):
    """版权下架：收到 → 通知负责人 → 后台点下架 → 搜索、浏览、详情、更多类似、插件都不再出现。"""
    out = gclient.get("/api/gather/open/v1/find", params={"q": "有调节的中介模型", "n": 3}).json()
    fid = out["items"][0]["id"]
    code = out["items"][0]["type_code"]
    r = gclient.post("/api/figures/takedown", json={"figures": f"https://tuku.example.org/figure/{fid}",
                                                    "holder": "某出版社", "contact": "rights@example.org", "reason": "版权"})
    assert r.status_code == 200 and "48 小时" in r.json()["message"]
    assert any("版权问题" in m for m in notifier.sent)
    login(gclient)
    items = gclient.get("/api/admin/figures/takedowns").json()["items"]
    assert items[0]["figure_ids"] == [fid] and items[0]["hours_left"] > 47
    assert gclient.post(f"/api/admin/figures/curate/takedown/{items[0]['id']}", json={"decision": "hide"}).status_code == 200
    assert gclient.post(f"/api/admin/figures/curate/takedown/{items[0]['id']}", json={"decision": "hide"}).status_code == 409

    assert gclient.get(f"/api/figures/{fid}").status_code == 404
    assert gclient.get(f"/api/figures/{fid}/thumb").status_code == 404
    s = gclient.get("/api/figures/search", params={"q": "有调节的中介模型"}).json()
    assert fid not in [c["id"] for g in s["groups"] for c in g["cards"]]
    b = gclient.get(f"/api/figures/types/{code}", params={"limit": 100}).json()
    assert fid not in [c["id"] for c in b["cards"]]
    assert gclient.get(f"/api/gather/open/v1/figure/{fid}").status_code == 404
    out2 = gclient.get("/api/gather/open/v1/find", params={"q": "有调节的中介模型", "n": 20}).json()
    assert fid not in [i["id"] for i in out2["items"]]


def test_tag_fix_with_credit_applies_after_approval(gclient):
    out = gclient.get("/api/gather/open/v1/find", params={"q": "中介模型", "n": 1}).json()
    fid = out["items"][0]["id"]
    r = gclient.post(f"/api/figures/{fid}/feedback", json={"reason": "wrong_tags", "note": "",
                                                           "proposed": {"what": "测试改过的标题"}, "credit": "小王"})
    assert "标签由 小王 改过" in r.json()["message"]
    login(gclient)
    item = gclient.get("/api/admin/figures/inbox/feedback").json()["items"][0]
    assert item["proposed"] == {"what": "测试改过的标题"} and item["credit"] == "小王"
    assert gclient.post(f"/api/admin/figures/curate/tag_fix/{item['id']}", json={"decision": "approve"}).status_code == 200
    d = gclient.get(f"/api/figures/{fid}").json()
    assert d["title"] == "测试改过的标题" and "标签由 小王 改过" in d["credits"]
