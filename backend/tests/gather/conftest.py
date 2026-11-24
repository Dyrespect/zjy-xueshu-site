"""聚人测试的公共件：带假站点地址的 app、截图、后台登录、贴一个假的网盘链接（example.invalid，不是真网盘）。"""

from __future__ import annotations

import io
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.figures.settings import FigureSettings
from app.gather.settings import GatherSettings
from app.main import create_app
from tests.conftest import TEST_PASSWORD

FAKE_PACK_URL = "https://pan.example.invalid/s/full-test"
FAKE_LITE_URL = "https://pan.example.invalid/s/lite-test"
BASES = dict(SITE_MAIN_URL="https://www.example.org", SITE_APP_URL="https://app.example.org",
             SITE_FIGURES_URL="https://tuku.example.org")


# 限频计数在每个测试自己的库里（core.ratelimit，11-18 底座可扩展），不用再手动清


def make_gclient(settings: Settings, notifier, **gs) -> TestClient:
    app = create_app(settings, notifier=notifier)
    app.state.gather_settings = GatherSettings(_env_file=None, **{**BASES, **gs})
    app.state.figure_settings = FigureSettings(_env_file=None, FIGURE_SERVICE_QR=None, SERVICE_URL="")
    return TestClient(app, base_url="http://testserver")


@pytest.fixture
def gclient(settings, notifier) -> Iterator[TestClient]:
    with make_gclient(settings, notifier) as c:
        yield c


def png(seed: int = 1) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (60, 40), ((seed * 37) % 256, (seed * 91) % 256, (seed * 53) % 256)).save(buf, "PNG")
    return buf.getvalue()


def login(c: TestClient) -> None:
    assert c.post("/api/auth/login", json={"password": TEST_PASSWORD}).status_code == 200


def visitor(n: int) -> str:
    return f"visitor-test-{n:04d}"


def release(c: TestClient, tier: str = "full", version: str = "2026.11", url: str = FAKE_PACK_URL) -> dict:
    login(c)
    r = c.post("/api/admin/gather/packs", json={"version": version, "tier": tier, "url": url, "extract_code": "ab12",
                                                "count": 7349 if tier == "full" else 310})
    assert r.status_code == 200, r.text
    return r.json()


def set_config(c: TestClient, **values) -> dict:
    login(c)
    r = c.put("/api/admin/gather/config", json=values)
    assert r.status_code == 200, r.text
    return r.json()["values"]


def start(c: TestClient, v: str, src: str = "") -> dict:
    r = c.post("/api/gather/unlock", json={"visitor": v, "src": src})
    assert r.status_code == 200, r.text
    return r.json()


def upload(c: TestClient, code: str, v: str, seed: int = 1):
    return c.post(f"/api/gather/unlock/{code}/evidence", data={"visitor": v}, files={"image": ("shot.png", png(seed), "image/png")})
