"""图库测试的公共件。

找图引擎、索引、原图都在本机「学术汇报」里（只读）。没有这些文件的机器（服务器、CI）跳过要真索引的测试。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.figures.engine import FigureEngine
from app.figures.library import get_engine
from app.figures.settings import FigureSettings
from app.main import create_app

ENGINE_PATH = Settings(_env_file=None).FIGURE_ENGINE_PATH
HAS_ENGINE = (ENGINE_PATH / "查参考.py").is_file()
needs_engine = pytest.mark.skipif(not HAS_ENGINE, reason="本机没有找图引擎和索引（学术汇报/PPT工厂/skills/科研绘图）")


@pytest.fixture(scope="session")
def engine() -> FigureEngine:
    if not HAS_ENGINE:
        pytest.skip("本机没有找图引擎")
    return get_engine(ENGINE_PATH)  # 只用关键词（不连向量小服务）


def make_client(settings: Settings, notifier, **figure_overrides) -> TestClient:
    app = create_app(settings, notifier=notifier)
    values = dict(FIGURE_SERVICE_QR=None, SERVICE_URL="https://example.org/service", FIGURE_RATE_LIMIT_PER_HOUR=10)
    values.update(figure_overrides)
    app.state.figure_settings = FigureSettings(_env_file=None, **values)
    return TestClient(app, base_url="http://testserver")


@pytest.fixture
def fclient(settings, notifier) -> Iterator[TestClient]:
    if not HAS_ENGINE:
        pytest.skip("本机没有找图引擎")
    with make_client(settings, notifier) as c:
        yield c


def tiny_png(color=(30, 80, 160), size=(40, 30)) -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def first_id_of(engine: FigureEngine, code: str) -> int:
    return next(d["号"] for d in engine.docs if d["h"]["主图型"] == code)


def data_dir(settings: Settings) -> Path:
    return settings.DATA_DIR / "图库"
