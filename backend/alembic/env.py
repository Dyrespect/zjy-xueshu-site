"""Alembic 运行环境。

- 数据库地址：调用方设了 sqlalchemy.url 就用它（测试、app.core.migrate），否则读 app 配置的 DATABASE_URL。
- 表：import_all_models() 自动加载 app/core 的表和每个业务模块的 app/<模块>/models.py。
- render_as_batch=True：SQLite 改列要「建新表-拷数据」，batch 模式自动处理；PostgreSQL 上无副作用。
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import get_settings
from app.core.db import Base, UTCDateTime
from app.registry import import_all_models

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", get_settings().DATABASE_URL.replace("%", "%%"))

import_all_models()
target_metadata = Base.metadata


def render_item(type_, obj, autogen_context):
    """迁移文件里不引用 app 的自定义类型：UTCDateTime 写成普通的 DateTime(timezone=True)。"""
    if type_ == "type" and isinstance(obj, UTCDateTime):
        return "sa.DateTime(timezone=True)"
    return False


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
        render_item=render_item,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            render_item=render_item,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
