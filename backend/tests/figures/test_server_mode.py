"""服务器上的图库：引擎跟部署包走（scripts/build_engine_bundle.py）、没有原图、图走 FIGURE_ASSET_BASE、EMBED_URL 空只用关键词。

- 有 FIGURE_ASSET_BASE 时：卡片、详情、后台给的都是拼好的 CDN 地址；/thumb、/preview 老链接 302 过去；不读原图、不在本地生成图。
- 从部署包加载、EMBED_URL 空：首页、搜索、详情、更多类似的都正常（只用关键词，「更多类似的」用本地向量）。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.migrate import upgrade_to_heads
from app.figures import images
from app.figures.library import Library
from app.figures.settings import FigureSettings
from app.main import create_app
from tests.conftest import TEST_PASSWORD, make_settings
from tests.figures.conftest import ENGINE_PATH, make_client, needs_engine

CDN = "https://cdn.example.com/xueshu-tuku"
REPO = Path(__file__).resolve().parents[3]


def _forbid_originals(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("图走对象存储时不该读原图、不该在本地生成图")

    monkeypatch.setattr(Library, "original_file", boom)
    monkeypatch.setattr(images, "ensure", boom)


def _check_site(c: TestClient, query: str) -> int:
    home = c.get("/api/figures/home")
    assert home.status_code == 200 and home.json()["total"] > 7000
    r = c.get("/api/figures/search", params={"q": query})
    assert r.status_code == 200
    cards = [card for g in r.json()["groups"] for card in g["cards"]]
    assert cards and all(card["thumb_url"] == f"{CDN}/thumb/{card['id']}.webp" for card in cards)
    fid = cards[0]["id"]
    d = c.get(f"/api/figures/{fid}").json()
    assert d["thumb_url"] == f"{CDN}/thumb/{fid}.webp" and d["preview_url"] == f"{CDN}/preview/{fid}.webp"
    sim = c.get(f"/api/figures/{fid}/similar").json()["cards"]
    assert sim and all(x["thumb_url"].startswith(f"{CDN}/thumb/") for x in sim)
    for kind in ("thumb", "preview"):
        red = c.get(f"/api/figures/{fid}/{kind}", follow_redirects=False)
        assert red.status_code == 302 and red.headers["location"] == f"{CDN}/{kind}/{fid}.webp"
    return fid


@needs_engine
def test_asset_base_gives_cdn_urls_and_never_touches_originals(settings, notifier, monkeypatch):
    _forbid_originals(monkeypatch)
    with make_client(settings, notifier, FIGURE_ASSET_BASE=CDN + "/") as c:  # 末尾斜杠也认
        fid = _check_site(c, "被试内实验的试次流程")
        c.post(f"/api/figures/{fid}/feedback", json={"reason": "wrong_tags", "note": "不是试次流程"})
        c.post("/api/auth/login", json={"password": TEST_PASSWORD})
        items = c.get("/api/admin/figures/inbox/feedback").json()["items"]
        assert items[0]["figure"]["thumb_url"] == f"{CDN}/thumb/{fid}.webp"


def _load_bundler():
    spec = importlib.util.spec_from_file_location("build_engine_bundle", REPO / "scripts" / "build_engine_bundle.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["build_engine_bundle"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def bundle(tmp_path_factory) -> Path:
    if not (ENGINE_PATH / "查参考.py").is_file():
        pytest.skip("本机没有找图引擎")
    tmp = tmp_path_factory.mktemp("bundle")
    sources = tmp / "出处.json"
    sources.write_text(json.dumps({"条目": {}}), encoding="utf-8")
    out = tmp / "deploy" / "bundle" / "engine"
    assert _load_bundler().main(["--engine", str(ENGINE_PATH), "--sources", str(sources), "--out", str(out)]) == 0
    return out


@needs_engine
def test_bundle_runs_site_keyword_only_without_originals(bundle, tmp_path, notifier, monkeypatch):
    # 包里的索引「文件」都清空了
    lines = (bundle / "参考" / "图库索引_新.jsonl").read_text(encoding="utf-8").splitlines()
    assert lines and all(json.loads(x)["文件"] == "" for x in lines)
    assert json.loads((bundle / "清单.json").read_text(encoding="utf-8"))["张数"] == len(lines)

    _forbid_originals(monkeypatch)
    s = make_settings(tmp_path, FIGURE_ENGINE_PATH=bundle / "脚本", ACADEMIC_ROOT=tmp_path / "没有学术汇报", EMBED_URL="")
    upgrade_to_heads(s.DATABASE_URL)
    app = create_app(s, notifier=notifier)
    app.state.figure_settings = FigureSettings(_env_file=None, FIGURE_ASSET_BASE=CDN, FIGURE_SOURCES=bundle / "出处.json")
    with TestClient(app) as c:
        lib = app.state.figure_library
        assert lib is not None and lib.engine.semantic is False  # EMBED_URL 空：只用关键词
        assert lib.engine.vectors is not None  # 本地向量还在（「更多类似的」用）
        _check_site(c, "眼动实验的试次流程")
        r = c.get("/api/figures/search", params={"q": "沙盘游戏治疗的流程"}).json()
        assert r["zero_words"]  # 库里没有的词照样说「库里没有」
