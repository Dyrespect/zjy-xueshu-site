"""数据库：SQLAlchemy 2.0。SQLite（现在）和 PostgreSQL（百人那档起）用同一套业务代码，切换只改 DATABASE_URL。

- 表定义放 `app/<模块>/models.py`，继承这里的 `Base`；Alembic 会自动发现（见 backend/alembic/env.py）。
- 只用 SQLAlchemy 的写法。**按方言分支的东西只许写在本文件**（scripts/check.py 规矩 S1）：
  SQLite 的 PRAGMA 和 BEGIN 方式、PG 的行锁和事务锁，业务模块调下面的 lock_row / txn_lock，不自己写。
- 库里的时间一律存 UTC。
- 接口里拿会话：`db: Session = Depends(get_db)`（POST/PUT/PATCH/DELETE 是写会话，GET 是读会话；
  GET 里要写库用 `get_write_db`）；脚本和后台任务里：`with database.session() as db:`（默认写会话）。

为什么分读写会话（docs/任务单/07_底座可扩展_设计.md 第六节）：
- SQLite 同一时刻只有一个写的。默认的「先开读事务、写的时候再升级成写锁」在别人刚提交过时会直接失败
  （database is locked，等多久都没用）。写会话一开始就 `BEGIN IMMEDIATE` 占住写锁，排队等，不会失败；
  读会话不开事务（每句读各自一个小事务，WAL 下读不挡写），里面真要写，第一句写之前再 `BEGIN IMMEDIATE`。
- 关掉 pysqlite 自带的事务处理、自己发 BEGIN，是 SQLAlchemy 文档给的做法；顺带 SAVEPOINT 也可靠了。
- PostgreSQL：读写会话一样（READ COMMITTED）；要「先读后改」的地方用 lock_row 锁行、用 txn_lock 锁一类事。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import Request
from sqlalchemy import DateTime, MetaData, create_engine, event, func, inspect, select
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import TypeDecorator

# 约束命名统一，Alembic 生成的迁移在 SQLite / PostgreSQL 上都稳定
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

_WRITE_OPT = "xh_write"  # 写会话的标记（执行选项），SQLite 上据此发 BEGIN IMMEDIATE
lock_log = logging.getLogger("app.db.lockwait")
_DML = re.compile(r"^\s*(INSERT|UPDATE|DELETE|REPLACE)\b", re.I)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator[datetime]):
    """存进去之前转成 UTC，读出来带上 UTC 时区（SQLite 自己不存时区；PG 上是 timestamptz）。"""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("存库的时间必须带时区（用 app.core.db.utcnow()）")
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


def _json_dumps(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False)


@dataclass(frozen=True)
class PoolSettings:
    """连接池参数（三档推荐值见 .env.example 和设计第八节）。SQLite 的 busy_timeout 也放这里。"""

    size: int = 20
    max_overflow: int = 20
    timeout: float = 30.0
    recycle: int = -1
    busy_timeout_ms: int = 15000
    lock_wait_log_ms: int = -1  # ≥0：等锁超过这么多毫秒就记一行日志（压测用；-1 不记）

    @classmethod
    def from_settings(cls, settings: Any) -> "PoolSettings":
        return cls(
            size=settings.DB_POOL_SIZE, max_overflow=settings.DB_MAX_OVERFLOW, timeout=settings.DB_POOL_TIMEOUT,
            recycle=settings.DB_POOL_RECYCLE, busy_timeout_ms=settings.DB_BUSY_TIMEOUT_MS,
            lock_wait_log_ms=settings.DB_LOCK_WAIT_LOG_MS,
        )


def dialect_name(target: Session | Engine | Any) -> str:
    """'sqlite' / 'postgresql'。传会话、engine 或连接都行。"""
    bind = target.get_bind() if isinstance(target, Session) else target
    return bind.dialect.name


def is_sqlite_url(url: str) -> bool:
    return url.startswith("sqlite")


def create_db_engine(database_url: str, pool: PoolSettings | None = None) -> Engine:
    pool = pool or PoolSettings()
    url = make_url(database_url)
    kw: dict[str, Any] = {"json_serializer": _json_dumps}
    if url.get_backend_name() == "sqlite":
        kw["connect_args"] = {"check_same_thread": False, "timeout": pool.busy_timeout_ms / 1000}
        if url.database in (None, "", ":memory:"):
            kw["poolclass"] = StaticPool  # 内存库只能一个连接
        else:
            kw.update(pool_size=pool.size, max_overflow=pool.max_overflow, pool_timeout=pool.timeout)
    else:
        kw.update(pool_size=pool.size, max_overflow=pool.max_overflow, pool_timeout=pool.timeout,
                  pool_recycle=pool.recycle, pool_pre_ping=True)
    engine = create_engine(database_url, **kw)
    if url.get_backend_name() == "sqlite":
        _sqlite_setup(engine, pool.busy_timeout_ms, pool.lock_wait_log_ms)
    elif pool.lock_wait_log_ms >= 0:
        _pg_lock_timing(engine, pool.lock_wait_log_ms)
    return engine


def _pg_lock_timing(engine: Engine, threshold_ms: int) -> None:
    """压测用：带行锁 / 事务锁的语句花了多久（主要是等锁）。"""

    @event.listens_for(engine, "before_cursor_execute")
    def _t0(conn, cursor, statement, params, context, executemany) -> None:  # pragma: no cover - 压测钩子
        if "FOR UPDATE" in statement or "pg_advisory_xact_lock" in statement:
            conn.info["xh_lock_t0"] = time.perf_counter()

    @event.listens_for(engine, "after_cursor_execute")
    def _t1(conn, cursor, statement, params, context, executemany) -> None:  # pragma: no cover - 压测钩子
        t0 = conn.info.pop("xh_lock_t0", None)
        if t0 is not None and (ms := (time.perf_counter() - t0) * 1000) >= threshold_ms:
            lock_log.info("lock_wait_ms=%.1f kind=%s", ms, "advisory" if "advisory" in statement else "row")


def _sqlite_setup(engine: Engine, busy_timeout_ms: int, lock_wait_log_ms: int = -1) -> None:
    @event.listens_for(engine, "connect")
    def _sqlite_connect(dbapi_conn, _record) -> None:  # pragma: no cover - 连接钩子
        dbapi_conn.isolation_level = None  # 不让 pysqlite 自己发 BEGIN / COMMIT，事务由下面的 begin 钩子开
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
        cur.close()

    def _begin_immediate(run) -> None:
        t0 = time.perf_counter()
        run("BEGIN IMMEDIATE")  # 等写锁就等在这一句
        if lock_wait_log_ms >= 0 and (ms := (time.perf_counter() - t0) * 1000) >= lock_wait_log_ms:
            lock_log.info("lock_wait_ms=%.1f kind=sqlite_write", ms)

    @event.listens_for(engine, "begin")
    def _sqlite_begin(conn) -> None:  # pragma: no cover - 连接钩子
        # 写会话：一开始就占写锁。读会话：不开事务，每句读各自成一个小事务（WAL 下不挡写、也不留旧快照）
        if conn.get_execution_options().get(_WRITE_OPT):
            _begin_immediate(conn.exec_driver_sql)

    @event.listens_for(engine, "before_cursor_execute")
    def _sqlite_first_write(conn, cursor, statement, parameters, context, executemany) -> None:  # pragma: no cover
        # 读会话里也有要写的（GET 记一条搜索记录、交付页记一次下载）：第一句写之前再 BEGIN IMMEDIATE 排队，
        # 不会因为「读的时候拿了旧快照、别人刚提交过」而直接 database is locked（11-18 合并图库后撞到过）
        if conn.get_execution_options().get(_WRITE_OPT) or not _DML.match(statement):
            return
        if not conn.connection.dbapi_connection.in_transaction:
            _begin_immediate(cursor.execute)


class Database:
    """一个库 = 一个 engine + 读写两个会话工厂。app 启动时建一个，放在 app.state.db。"""

    def __init__(self, database_url: str, pool: PoolSettings | None = None) -> None:
        self.url = database_url
        self.engine = create_db_engine(database_url, pool)
        self.read_sessionmaker = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.write_sessionmaker = sessionmaker(bind=self.engine.execution_options(**{_WRITE_OPT: True}),
                                               expire_on_commit=False)
        self.sessionmaker = self.write_sessionmaker  # 老写法 database.sessionmaker() = 写会话

    @property
    def dialect(self) -> str:
        return self.engine.dialect.name

    @contextmanager
    def session(self, *, write: bool = True) -> Iterator[Session]:
        """脚本、后台任务用：正常结束自动提交，出错回滚。只读的传 write=False（SQLite 上不占写锁）。"""
        db = (self.write_sessionmaker if write else self.read_sessionmaker)()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def dispose(self) -> None:
        self.engine.dispose()


WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def get_db(request: Request) -> Iterator[Session]:
    """FastAPI 依赖：每个请求一个会话。要落库就在接口里自己 `db.commit()`。
    POST/PUT/PATCH/DELETE 拿写会话；GET 拿读会话（GET 里要写库改用 get_write_db，check.py 规矩 S3 拦）。"""
    database: Database = request.app.state.db
    db = (database.write_sessionmaker if request.method in WRITE_METHODS else database.read_sessionmaker)()
    try:
        yield db
    finally:
        db.close()


def get_write_db(request: Request) -> Iterator[Session]:
    """FastAPI 依赖：不管什么方法都拿写会话（GET 里也要写库的接口用，比如付款页轮询会改状态）。"""
    db: Session = request.app.state.db.write_sessionmaker()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------- 锁（方言分支只在这里）

def lock_row(db: Session, obj: Any) -> Any:
    """「先读后改」之前锁住这一行，再读一遍最新的（PG：SELECT … FOR UPDATE）。

    先 flush（本会话改了还没写下去的不丢），再带行锁重读：PG 上别的事务改这一行要等这笔提交；
    SQLite 不认 FOR UPDATE（SQLAlchemy 不生成），写会话一开始就独占写锁，效果一样。
    """
    state = inspect(obj, raiseerr=False)
    if state is None or not state.persistent:  # 不是表里的对象（测试里的假对象）或还没存进库
        return obj
    db.flush()
    db.refresh(obj, with_for_update=True)
    return obj


def lock_key(key: str) -> int:
    """命名锁的键 → 有符号 64 位整数（pg_advisory_xact_lock 要的）。稳定、跨进程一致。"""
    n = int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big")
    return n - (1 << 64) if n >= (1 << 63) else n


def txn_lock(db: Session, key: str) -> None:
    """本事务内的命名锁：同一个 key 同一时刻只有一个事务拿到，提交或回滚自动放开（比如「算名额再排期」）。

    PG：pg_advisory_xact_lock。SQLite：写会话已经独占，什么都不做。
    """
    if dialect_name(db) == "postgresql":
        db.execute(select(func.pg_advisory_xact_lock(lock_key(key))))


def sqlite_path(database_url: str) -> str | None:
    """sqlite:///绝对路径 → 文件路径；不是 SQLite 文件库返回 None。"""
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or url.database in (None, "", ":memory:"):
        return None
    return os.path.abspath(url.database)


__all__ = [
    "Base", "Database", "PoolSettings", "UTCDateTime", "utcnow", "create_db_engine", "dialect_name", "get_db",
    "get_write_db", "lock_row", "txn_lock", "lock_key", "sqlite_path", "is_sqlite_url",
]
