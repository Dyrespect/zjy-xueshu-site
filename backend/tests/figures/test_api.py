"""图库对外接口：首页、搜索（记搜索记录和点击）、浏览、详情、更多类似的、缩略图和预览图。"""

from PIL import Image
from sqlalchemy import select

from app.core.db import Database
from app.figures.models import SearchClick, SearchLog
from tests.figures.conftest import data_dir, first_id_of, needs_engine

pytestmark = needs_engine


def test_site_and_home(fclient, engine):
    s = fclient.get("/api/figures/site").json()
    assert s["service_url"] == "https://example.org/service"
    assert s["qr_url"] == ""  # 没配二维码
    assert len(s["types"]) == 31

    h = fclient.get("/api/figures/home").json()
    assert h["total"] == len(engine.docs)
    assert 100 < h["journals"] < 347  # 去掉预印本、讲义，缩写和全称算一本
    assert [g["title"] for g in h["groups"]] == ["为什么做", "研究设计", "分析", "结果"]
    assert sum(t["count"] for g in h["groups"] for t in g["types"]) == len(engine.docs)
    assert len(h["popular"]) == 10


def test_search_groups_and_log(fclient, settings):
    r = fclient.get("/api/figures/search", params={"q": "被试内实验的试次流程"})
    assert r.status_code == 200
    body = r.json()
    assert body["guess"] == {"code": "D2", "name": "试次流程"}
    assert body["code"] == "D2" and body["overridden"] is False
    assert [w["word"] for w in body["words"]] == ["被试内", "实验", "试次流程"]
    keys = [g["key"] for g in body["groups"]]
    assert keys[0] == "close"
    assert "shape" in keys
    assert all(g["title"] and g["cards"] for g in body["groups"])
    assert body["total"] == sum(len(g["cards"]) for g in body["groups"])
    papers = [c["id"] for g in body["groups"] for c in g["cards"]]
    assert len(papers) == len(set(papers))

    db = Database(settings.DATABASE_URL)
    with db.session() as s:
        log = s.get(SearchLog, body["search_id"])
        assert log.query == "被试内实验的试次流程"
        assert log.guess == "D2" and log.code == "D2"
        assert log.words == ["被试内", "实验", "试次流程"]
        assert log.total == body["total"]
        assert sum(g["n"] for g in log.groups) == body["total"]
    db.dispose()


def test_change_type_in_dropdown(fclient):
    body = fclient.get("/api/figures/search", params={"q": "被试内实验的试次流程", "code": "D1"}).json()
    assert body["code"] == "D1" and body["overridden"] is True
    assert body["code_name"] == "实验设计"


def test_zero_word_notice_data(fclient):
    body = fclient.get("/api/figures/search", params={"q": "催眠诱导的流程"}).json()
    assert body["zero_words"] == ["催眠诱导"]
    assert any(g["key"].startswith("extra:") for g in body["groups"])
    assert body["total"] > 0


def test_click_logged(fclient, settings, engine):
    body = fclient.get("/api/figures/search", params={"q": "技术路线"}).json()
    card = body["groups"][0]["cards"][0]
    r = fclient.post(
        "/api/figures/clicks", json={"search_id": body["search_id"], "figure_id": card["id"], "position": 0, "lane": "close"}
    )
    assert r.status_code == 204
    # 不存在的搜索号：不报错，也不记
    assert fclient.post("/api/figures/clicks", json={"search_id": 999999, "figure_id": 1}).status_code == 204
    db = Database(settings.DATABASE_URL)
    with db.session() as s:
        clicks = list(s.scalars(select(SearchClick)))
        assert [(c.search_id, c.figure_id) for c in clicks] == [(body["search_id"], card["id"])]
    db.dispose()


def test_browse(fclient, engine):
    body = fclient.get("/api/figures/types/w3", params={"limit": 10}).json()
    assert body["code"] == "W3" and body["name"] == "技术路线" and body["group_title"] == "为什么做"
    assert body["total"] == sum(1 for d in engine.docs if d["h"]["主图型"] == "W3")
    assert len(body["cards"]) == 10
    assert fclient.get("/api/figures/types/X9").status_code == 404


def test_detail_and_similar(fclient, engine):
    fid = first_id_of(engine, "W2")
    d = fclient.get(f"/api/figures/{fid}").json()
    assert d["id"] == fid
    assert d["preview_url"] == f"/api/figures/{fid}/preview"
    assert d["types"][0]["code"] == "W2"
    assert d["cite"]
    assert all(t["words"] for t in d["tags"])
    sims = fclient.get(f"/api/figures/{fid}/similar").json()["cards"]
    assert len(sims) == 8 and fid not in [c["id"] for c in sims]
    assert fclient.get("/api/figures/99999999").status_code == 404


def test_thumb_and_preview_generated_and_cached(fclient, engine, settings):
    fid = engine.docs[5]["号"]
    r = fclient.get(f"/api/figures/{fid}/thumb")
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp"
    thumb = data_dir(settings) / "缩略图" / f"{fid}.webp"
    assert thumb.is_file()
    with Image.open(thumb) as im:
        assert max(im.size) <= 480

    r = fclient.get(f"/api/figures/{fid}/preview")
    assert r.status_code == 200
    prev = data_dir(settings) / "预览" / f"{fid}.webp"
    with Image.open(prev) as im:
        assert max(im.size) <= 1400
    mtime = prev.stat().st_mtime_ns
    fclient.get(f"/api/figures/{fid}/preview")
    assert prev.stat().st_mtime_ns == mtime  # 第二次直接用缓存


def test_service_qr_from_config(settings, notifier, tmp_path):
    from tests.figures.conftest import make_client, tiny_png

    qr = tmp_path / "qr.png"
    qr.write_bytes(tiny_png())
    with make_client(settings, notifier, FIGURE_SERVICE_QR=qr) as c:
        assert c.get("/api/figures/site").json()["qr_url"] == "/api/figures/service-qr"
        r = c.get("/api/figures/service-qr")
        assert r.status_code == 200 and r.content == qr.read_bytes()
    with make_client(settings, notifier) as c:
        assert c.get("/api/figures/service-qr").status_code == 404


def test_library_missing_returns_503(settings, notifier, tmp_path):
    from app.main import create_app

    s = settings.model_copy(update={"FIGURE_ENGINE_PATH": tmp_path / "没有这个目录"})
    from fastapi.testclient import TestClient

    with TestClient(create_app(s, notifier=notifier)) as c:
        assert c.get("/api/figures/home").status_code == 503
        assert c.get("/api/health").status_code == 200  # 网站其余部分照常
