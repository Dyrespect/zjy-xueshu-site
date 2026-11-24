"""生产加固（上线准备）：APP_ENV=prod 时 cookie 带 Secure、接口清单关掉；交付页 / 后台 / 网页聊天页面头带 noindex；
后台、登录、交付、网页聊天、领交接包的接口不缓存；前端带哈希的静态文件长缓存；在 Cloudflare 后面限流按真实 IP 算。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.auth import COOKIE_NAME
from app.core.headers import headers_for
from app.core.migrate import upgrade_to_heads
from app.figures.settings import FigureSettings
from app.main import create_app
from tests.conftest import TEST_PASSWORD, make_settings


def _dist(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><div id=root>SPA</div>", encoding="utf-8")
    (dist / "assets" / "index-abc123.js").write_text("console.log(1)", encoding="utf-8")
    return dist


def _app(tmp_path, notifier, **over):
    s = make_settings(tmp_path, FRONTEND_DIST=_dist(tmp_path), **over)
    upgrade_to_heads(s.DATABASE_URL)
    return create_app(s, notifier=notifier)


def _set_cookie(r) -> str:
    return next(v for k, v in r.headers.multi_items() if k.lower() == "set-cookie" and v.startswith(COOKIE_NAME))


def test_prod_cookie_secure_and_no_api_docs(tmp_path, notifier):
    # 回源可能是 http（Cloudflare → nginx），PUBLIC_BASE_URL 也没写 https：只要 APP_ENV=prod 就带 Secure
    app = _app(tmp_path, notifier, APP_ENV="prod", PUBLIC_BASE_URL="http://hb.example.cn")
    with TestClient(app, base_url="https://testserver") as c:
        r = c.post("/api/auth/login", json={"password": TEST_PASSWORD})
        assert r.status_code == 200
        cookie = _set_cookie(r)
        assert "Secure" in cookie and "HttpOnly" in cookie and "samesite=lax" in cookie.lower()
        assert c.get("/api/openapi.json").status_code == 404 and c.get("/api/docs").status_code == 404


def test_dev_cookie_not_secure_on_http(tmp_path, notifier):
    with TestClient(_app(tmp_path, notifier)) as c:
        assert "Secure" not in _set_cookie(c.post("/api/auth/login", json={"password": TEST_PASSWORD}))


def test_pages_and_private_apis_headers(tmp_path, notifier):
    with TestClient(_app(tmp_path, notifier, APP_ENV="prod")) as c:
        for path in ("/d/q8Hc2vYtW1nM0aXbLr4sK7pE9dJf", "/admin", "/admin/orders", "/chat/abc", "/chat", "/c/PSY-K7QM4XWDN", "/me"):
            r = c.get(path)
            assert "SPA" in r.text and r.headers["x-robots-tag"] == "noindex, nofollow", path
        assert c.get("/d/q8Hc2vYtW1nM0aXbLr4sK7pE9dJf").headers["referrer-policy"] == "no-referrer"
        assert c.get("/c/PSY-K7QM4XWDN").headers["referrer-policy"] == "no-referrer"  # 兑换页地址里带激活码
        assert "x-robots-tag" not in c.get("/contact").headers  # 整段匹配：/c 不连带 /contact
        for path in ("/", "/search", "/figure/123"):
            assert "x-robots-tag" not in c.get(path).headers, path  # 图库页面要被收录
        for path in ("/api/auth/me", "/api/admin/intake/orders", "/api/delivery/q8Hc2vYtW1nM0aXbLr4sK7pE9dJf",
                     "/api/handoffs"):
            assert c.get(path).headers["cache-control"] == "no-store", path
        key = c.post("/api/channels/web/sessions").json()["key"]
        assert c.get(f"/api/channels/web/{key}").headers["cache-control"] == "no-store"
        a = c.get("/assets/index-abc123.js")
        assert a.headers["cache-control"] == "public, max-age=31536000, immutable"
        assert a.headers["x-content-type-options"] == "nosniff"
        assert c.get("/api/health").headers.get("cache-control") is None


@pytest.mark.parametrize("path,no_store,noindex", [
    ("/administer", False, False),  # 按整段匹配，不是前缀字符串
    ("/admin", False, True),
    ("/api/admin/figures/stats", True, True),
    ("/api/delivery/x/files/1", True, True),
    ("/api/figures/search", False, False),
    ("/data/x", False, False),
])
def test_header_rules(path, no_store, noindex):
    h = dict(headers_for(path))
    assert (h.get(b"cache-control") == b"no-store") is no_store
    assert (b"x-robots-tag" in h) is noindex


def test_rate_limit_uses_cloudflare_real_ip(tmp_path, notifier):
    """部署在 Cloudflare + nginx 后面（TRUST_PROXY_HEADERS=true）：限流按 CF-Connecting-IP，不是按代理的 IP 一起算。"""
    app = _app(tmp_path, notifier, TRUST_PROXY_HEADERS=True)
    app.state.figure_settings = FigureSettings(_env_file=None, FIGURE_RATE_LIMIT_PER_HOUR=2)
    with TestClient(app) as c:
        def send(ip: str) -> int:
            return c.post("/api/figures/site-feedback", json={"content": "搜不到眼动的图"},
                          headers={"CF-Connecting-IP": ip, "X-Forwarded-For": f"{ip}, 172.18.0.1"}).status_code

        assert [send("1.1.1.1"), send("1.1.1.1"), send("1.1.1.1")] == [200, 200, 429]
        assert send("2.2.2.2") == 200  # 另一个人不受影响
