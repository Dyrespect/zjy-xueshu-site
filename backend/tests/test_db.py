import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, text

from app.core.db import Base, create_db_engine
from app.core.migrate import upgrade_to_heads
from app.registry import import_all_models
from tests.conftest import PG_MODE


def test_migration_creates_events(settings):
    engine = create_db_engine(settings.DATABASE_URL)
    try:
        insp = inspect(engine)
        assert "events" in insp.get_table_names()
        cols = {c["name"] for c in insp.get_columns("events")}
        assert {"id", "created_at", "type", "subject", "content"} <= cols
    finally:
        engine.dispose()


def test_migrations_are_idempotent(settings):
    upgrade_to_heads(settings.DATABASE_URL)  # 再跑一次不报错


def test_models_match_migrations(settings):
    """表定义和迁移一致：加了表 / 改了字段却没写迁移，这里会失败。

    修法：在 backend/ 下 `../.venv/bin/alembic revision --autogenerate -m "..." --rev-id <模块>_<序号>`。
    """
    import_all_models()
    engine = create_db_engine(settings.DATABASE_URL)
    try:
        with engine.connect() as conn:
            diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    finally:
        engine.dispose()
    assert diff == [], f"表定义和迁移对不上，需要新迁移：{diff}"


@pytest.mark.skipif(PG_MODE, reason="只 SQLite 有 PRAGMA")
def test_sqlite_pragmas(settings):
    engine = create_db_engine(settings.DATABASE_URL)
    try:
        with engine.connect() as conn:
            assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"
            assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
            assert conn.execute(text("PRAGMA busy_timeout")).scalar() == 15000
    finally:
        engine.dispose()
