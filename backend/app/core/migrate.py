"""跑迁移到最新：`python -m app.core.migrate`（在 backend/ 目录下）。

并行开发时迁移可能分叉成多个 head（每个模块各自加表），所以一律升到 `heads`（复数）。
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

from app.core.config import get_settings

BACKEND_DIR = Path(__file__).resolve().parents[2]


def alembic_config(database_url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return cfg


def upgrade_to_heads(database_url: str) -> None:
    if database_url.startswith("sqlite:///"):
        Path(database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(alembic_config(database_url), "heads")


if __name__ == "__main__":
    s = get_settings()
    upgrade_to_heads(s.DATABASE_URL)
    print(f"迁移完成：{s.DATABASE_URL}")
