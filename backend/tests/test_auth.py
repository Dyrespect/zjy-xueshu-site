from fastapi import Depends
from fastapi.testclient import TestClient

from app.core.auth import COOKIE_NAME, require_admin
from app.core.migrate import upgrade_to_heads
from app.main import create_app
from tests.conftest import TEST_PASSWORD, make_settings


def _app_with_protected_route(settings, notifier):
    app = create_app(settings, notifier=notifier)

    @app.get("/api/_test/secret", dependencies=[Depends(require_admin)])
    def secret():
        return {"ok": True}

    return app


def test_login_logout_flow(settings, notifier):
    with TestClient(_app_with_protected_route(settings, notifier)) as c:
        assert c.get("/api/auth/me").json() == {"admin": False}
        assert c.get("/api/_test/secret").status_code == 401

        r = c.post("/api/auth/login", json={"password": "错的"})
        assert r.status_code == 401
        assert c.get("/api/_test/secret").status_code == 401

        r = c.post("/api/auth/login", json={"password": TEST_PASSWORD})
        assert r.status_code == 200
        assert COOKIE_NAME in r.cookies
        set_cookie = r.headers["set-cookie"].lower()
        assert "httponly" in set_cookie and "samesite=lax" in set_cookie
        assert c.get("/api/auth/me").json() == {"admin": True}
        assert c.get("/api/_test/secret").json() == {"ok": True}

        c.post("/api/auth/logout")
        assert c.get("/api/auth/me").json() == {"admin": False}
        assert c.get("/api/_test/secret").status_code == 401


def test_tampered_cookie_rejected(client):
    client.cookies.set(COOKIE_NAME, "eyJhZG1pbiI6dHJ1ZX0.forged.sig")
    assert client.get("/api/auth/me").json() == {"admin": False}


def test_cookie_signed_with_other_secret_rejected(tmp_path, notifier):
    sa, sb = make_settings(tmp_path / "a", SESSION_SECRET="secret-a-" * 4), make_settings(tmp_path / "b", SESSION_SECRET="secret-b-" * 4)
    for s in (sa, sb):
        upgrade_to_heads(s.DATABASE_URL)  # 登录失败计数在库里（core.ratelimit），要有表
    a, b = create_app(sa, notifier=notifier), create_app(sb, notifier=notifier)
    with TestClient(a) as ca, TestClient(b) as cb:
        token = ca.post("/api/auth/login", json={"password": TEST_PASSWORD}).cookies[COOKIE_NAME]
        cb.cookies.set(COOKIE_NAME, token)
        assert cb.get("/api/auth/me").json() == {"admin": False}


def test_no_password_configured_means_no_login(tmp_path, notifier):
    app = create_app(make_settings(tmp_path, ADMIN_PASSWORD=""), notifier=notifier)
    with TestClient(app) as c:
        assert c.post("/api/auth/login", json={"password": ""}).status_code == 503


def test_lockout_after_repeated_failures(client):
    for _ in range(5):
        assert client.post("/api/auth/login", json={"password": "x"}).status_code == 401
    r = client.post("/api/auth/login", json={"password": TEST_PASSWORD})
    assert r.status_code == 429


def test_admin_router_requires_login_by_default():
    """后台 router 整体挂了 require_admin：以后加的后台接口默认要登录。"""
    from app.admin.router import router

    deps = [d.dependency for d in router.dependencies]
    assert require_admin in deps


def test_prod_requires_secrets(tmp_path):
    import pytest

    with pytest.raises(ValueError, match="ADMIN_PASSWORD"):
        make_settings(tmp_path, APP_ENV="prod", ADMIN_PASSWORD="", SESSION_SECRET="")
