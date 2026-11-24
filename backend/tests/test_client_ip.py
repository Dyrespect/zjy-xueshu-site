from fastapi import Request
from fastapi.testclient import TestClient

from app.core.deps import client_ip
from app.main import create_app
from tests.conftest import make_settings


def _app(tmp_path, notifier, trust: bool):
    app = create_app(make_settings(tmp_path, TRUST_PROXY_HEADERS=trust), notifier=notifier)

    @app.get("/api/_test/ip")
    def ip(request: Request):
        return {"ip": client_ip(request)}

    return app


def test_proxy_headers_ignored_by_default(tmp_path, notifier):
    with TestClient(_app(tmp_path, notifier, False)) as c:
        r = c.get("/api/_test/ip", headers={"CF-Connecting-IP": "1.2.3.4", "X-Forwarded-For": "5.6.7.8"})
        assert r.json()["ip"] == "testclient"


def test_proxy_headers_trusted_when_configured(tmp_path, notifier):
    with TestClient(_app(tmp_path, notifier, True)) as c:
        assert c.get("/api/_test/ip", headers={"CF-Connecting-IP": "1.2.3.4"}).json()["ip"] == "1.2.3.4"
        r = c.get("/api/_test/ip", headers={"X-Forwarded-For": "5.6.7.8, 10.0.0.1"})
        assert r.json()["ip"] == "5.6.7.8"
