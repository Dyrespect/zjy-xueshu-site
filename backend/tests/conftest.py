"""测试公共件：每个测试一个临时目录、一个临时库（已跑完迁移）、一个假通知。

不读仓库根的 .env，不发任何网络请求。

两种库（docs/任务单/07_底座可扩展_设计.md 第九节）：
- 默认 SQLite：每个测试 tmp_path 下一个库文件。
- 设了环境变量 TEST_DATABASE_URL=postgresql+psycopg://用户@主机:端口/库 就全量跑在 PostgreSQL 上
  （scripts/verify-pg.sh）：整轮先建一个模板库跑完迁移（这一步就是「空库升到最新」），每个测试从模板克隆一个库，
  测完删掉（WITH FORCE）。没装 psycopg 时 PG 专属的测试自动跳过。
"""

from __future__ import annotations

import itertools
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.db import Database
from app.core.migrate import upgrade_to_heads
from app.core.notify import FakeNotifier
from app.main import create_app

TEST_PASSWORD = "test-password-不要用在线上"
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "").strip()
PG_MODE = TEST_DATABASE_URL.startswith("postgresql")


def psycopg_installed() -> bool:
    try:
        import psycopg  # noqa: F401
    except ImportError:
        return False
    return True


class _PgDatabases:
    """PG 模式：模板库 + 每个测试克隆一个。名字带进程号，几轮同时跑互不干扰。"""

    def __init__(self, admin_url: str) -> None:
        from sqlalchemy import create_engine
        from sqlalchemy.engine import make_url

        self.base = make_url(admin_url)
        self.admin = create_engine(admin_url, isolation_level="AUTOCOMMIT", pool_size=1, max_overflow=2)
        self.prefix = f"xt_{os.getpid()}"
        self.template = f"{self.prefix}_tpl"
        self.counter = itertools.count(1)
        self.created: list[str] = []
        self.ready = False

    def url(self, name: str) -> str:
        return self.base.set(database=name).render_as_string(hide_password=False)

    def _exec(self, sql: str) -> None:
        from sqlalchemy import text

        with self.admin.connect() as c:
            c.execute(text(sql))

    def ensure_template(self) -> None:
        if self.ready:
            return
        self._exec(f'DROP DATABASE IF EXISTS "{self.template}" WITH (FORCE)')
        self._exec(f'CREATE DATABASE "{self.template}"')
        upgrade_to_heads(self.url(self.template))  # 空库升到最新：PG 上的迁移在这里真跑一遍
        self.ready = True

    def new(self) -> str:
        self.ensure_template()
        name = f"{self.prefix}_{next(self.counter)}"
        self._exec(f'CREATE DATABASE "{name}" TEMPLATE "{self.template}"')
        self.created.append(name)
        return self.url(name)

    def drop_created(self) -> None:
        while self.created:
            self._exec(f'DROP DATABASE IF EXISTS "{self.created.pop()}" WITH (FORCE)')

    def close(self) -> None:
        self.drop_created()
        if self.ready:
            self._exec(f'DROP DATABASE IF EXISTS "{self.template}" WITH (FORCE)')
        self.admin.dispose()


_PG: _PgDatabases | None = None


def _pg() -> _PgDatabases:
    global _PG
    if _PG is None:
        if not psycopg_installed():
            pytest.exit("设了 TEST_DATABASE_URL 但没装 psycopg：先 uv pip sync backend/requirements-scale.lock", returncode=2)
        _PG = _PgDatabases(TEST_DATABASE_URL)
    return _PG


def fresh_database_url(tmp_path: Path, name: str = "test.db") -> str:
    """一个空的、已经升到最新的库：SQLite 是 tmp_path 下的新文件（还没迁移，调用方 upgrade_to_heads），PG 是模板克隆。"""
    if PG_MODE:
        return _pg().new()
    return f"sqlite:///{tmp_path / 'data' / name}"


@pytest.fixture(autouse=True)
def _no_release_hold(monkeypatch):
    """不加急的单第一版压到加急承诺时长之后再发（delivery/release.py）：老测试按「交了就发」写的，这里关掉；
    tests/delivery/test_release_hold.py 自己打开测。"""
    monkeypatch.setenv("DELIVERY_HOLD_STANDARD", "false")


@pytest.fixture(autouse=True)
def _drop_pg_databases() -> Iterator[None]:
    yield
    if _PG is not None:
        _PG.drop_created()


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ARG001
    if _PG is not None:
        _PG.close()


def make_settings(tmp_path: Path, **overrides) -> Settings:
    values = dict(
        APP_ENV="dev",
        DATA_DIR=tmp_path / "data",
        DATABASE_URL=overrides.pop("DATABASE_URL", None) or fresh_database_url(tmp_path),
        FRONTEND_DIST=tmp_path / "no-dist",
        ADMIN_PASSWORD=TEST_PASSWORD,
        SESSION_SECRET="test-session-secret-0123456789abcdef",
        FEISHU_WEBHOOK="",
        LLM_API_KEY="",
        EMBED_URL="",
        BACKGROUND_IN_WEB=True,  # 测试照旧：后台圈在 TestClient 的进程里跑（各模块的测试自己关掉要关的）
    )
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture(autouse=True, scope="session")
def _all_nodes_registered() -> None:
    """流程里用到的节点分在各模块（交付那几个在 app/delivery/nodes）：不起 app 的单测也要先全部登记上。"""
    from app.registry import import_all_nodes

    import_all_nodes()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    s = make_settings(tmp_path)
    upgrade_to_heads(s.DATABASE_URL)
    return s


@pytest.fixture
def notifier() -> FakeNotifier:
    return FakeNotifier()


@pytest.fixture
def client(settings: Settings, notifier: FakeNotifier) -> Iterator[TestClient]:
    app = create_app(settings, notifier=notifier)
    with TestClient(app, base_url="http://testserver") as c:
        yield c


@pytest.fixture
def database(settings: Settings) -> Iterator[Database]:
    db = Database(settings.DATABASE_URL)
    yield db
    db.dispose()
