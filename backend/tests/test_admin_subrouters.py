"""后台子 router 自动挂载：app/admin/xxx_router.py 自动挂上，并自动要求登录。"""

import sys

from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

from app.admin.router import include_sub_routers
from app.core.auth import require_admin
from app.main import create_app
from tests.conftest import TEST_PASSWORD


def test_sub_router_discovered_and_protected(tmp_path, settings, notifier, monkeypatch):
    pkg = tmp_path / "fakeadmin"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "demo_router.py").write_text(
        "from fastapi import APIRouter\n"
        "router = APIRouter(prefix='/demo')\n"
        "@router.get('/ping')\n"
        "def ping():\n"
        "    return {'pong': True}\n"
    )
    (pkg / "helpers.py").write_text("X = 1\n")  # 不以 _router 结尾，不挂
    monkeypatch.syspath_prepend(str(tmp_path))

    parent = APIRouter(dependencies=[Depends(require_admin)])
    assert include_sub_routers(parent, pkg, "fakeadmin") == ["demo_router"]

    app = create_app(settings, notifier=notifier)
    app.include_router(parent, prefix="/api/admin")
    with TestClient(app) as c:
        assert c.get("/api/admin/demo/ping").status_code == 401
        c.post("/api/auth/login", json={"password": TEST_PASSWORD})
        assert c.get("/api/admin/demo/ping").json() == {"pong": True}
    sys.modules.pop("fakeadmin.demo_router", None)
    sys.modules.pop("fakeadmin", None)
