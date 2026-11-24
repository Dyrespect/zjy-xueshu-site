from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import make_settings


def _fake_dist(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><div id=root>SPA</div>", encoding="utf-8")
    (dist / "assets" / "app-abc.js").write_text("console.log(1)", encoding="utf-8")
    (dist / "robots.txt").write_text("User-agent: *", encoding="utf-8")
    (dist / "maintenance.html").write_text("<p>维护中</p>", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("不该被读到", encoding="utf-8")
    return dist


def test_spa_fallback_and_api_untouched(tmp_path, notifier):
    settings = make_settings(tmp_path, FRONTEND_DIST=_fake_dist(tmp_path))
    with TestClient(create_app(settings, notifier=notifier)) as c:
        assert "SPA" in c.get("/").text
        assert "SPA" in c.get("/search/抑郁").text  # 前端路由回落到 index.html
        assert c.get("/assets/app-abc.js").text == "console.log(1)"
        assert c.get("/maintenance.html").text == "<p>维护中</p>"  # dist 里的静态文件原样给
        assert "Disallow: /" in c.get("/robots.txt").text  # robots.txt 由官网模块按开关出（app/website/router.py），不读 dist 里的
        r = c.get("/api/不存在")
        assert r.status_code == 404 and r.headers["content-type"].startswith("application/json")
        assert c.get("/api/health").json()["status"] == "ok"
        assert "不该被读到" not in c.get("/..%2fsecret.txt").text
        assert "不该被读到" not in c.get("/%2e%2e/secret.txt").text


def test_no_dist_no_mount(client):
    assert client.get("/").status_code == 404
