def test_health_ok(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "db": "ok"}


def test_business_routers_exist(client):
    """业务模块各有一个 router（handoffs 是上线准备加的：Mac 来领交接包；shop、platforms 是 11-18 加的新模块，
    还在设计、没有 router.py 时先跳过），底座接口在文档里。"""
    from fastapi import APIRouter

    from app.registry import BUSINESS_MODULES, router_modules

    assert BUSINESS_MODULES == ("figures", "intake", "channels", "delivery", "handoffs", "shop", "platforms", "invoices", "gather", "website", "ops", "admin")
    mods = router_modules()
    assert {"figures", "intake", "channels", "delivery", "handoffs", "admin"} <= set(mods)
    assert all(isinstance(m.router, APIRouter) for m in mods.values())
    paths = client.get("/api/openapi.json").json()["paths"]
    assert "/api/health" in paths and "/api/auth/login" in paths


def test_unknown_api_is_json_404(client):
    r = client.get("/api/没有这个接口")
    assert r.status_code == 404
    assert r.json()["detail"] == "Not Found"


def test_module_lifespan_hook_runs(settings, notifier, monkeypatch):
    """业务模块在 router.py 里定义 lifespan，main 会自动调用（不用改 main.py）。"""
    from contextlib import asynccontextmanager

    from fastapi.testclient import TestClient

    import app.figures.router as fr
    from app.main import create_app

    calls = []

    @asynccontextmanager
    async def lifespan(app):
        calls.append("start")
        yield
        calls.append("stop")

    monkeypatch.setattr(fr, "lifespan", lifespan, raising=False)
    with TestClient(create_app(settings, notifier=notifier)):
        assert calls == ["start"]
    assert calls == ["start", "stop"]
