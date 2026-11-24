"""数据库层（设计第六节）：SQLite 写会话一开始就占写锁、读不受影响、SAVEPOINT 可靠；PG 上 lock_row / txn_lock 真的会挡住
第二个事务。按方言的测试各自跳过。"""

from __future__ import annotations

import threading
import time

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError

from app.core.db import Database, PoolSettings, lock_row, txn_lock, utcnow
from app.core.events import Event, record_event
from tests.conftest import PG_MODE
from tests.scale.helpers import no_errors, run_at_once


@pytest.fixture
def db_(settings):
    d = Database(settings.DATABASE_URL)
    yield d
    d.dispose()


def test_savepoint_rolls_back_only_inner(db_):
    """关掉 pysqlite 自带的事务处理以后 SAVEPOINT 可靠了（两种库一样）。"""
    with db_.session() as db:
        record_event(db, "t.outer", "x:1", {})
        try:
            with db.begin_nested():
                record_event(db, "t.inner", "x:2", {})
                db.flush()
                raise RuntimeError("回滚里面这一段")
        except RuntimeError:
            pass
    with db_.session(write=False) as db:
        assert db.scalars(select(Event.type).where(Event.type.like("t.%"))).all() == ["t.outer"]


@pytest.mark.skipif(PG_MODE, reason="只 SQLite：整库一个写锁")
def test_sqlite_write_session_locks_up_front_reads_still_work(settings):
    holder = Database(settings.DATABASE_URL)
    impatient = Database(settings.DATABASE_URL, PoolSettings(busy_timeout_ms=200))
    try:
        with holder.session() as a:
            a.execute(select(1))  # 写会话：第一句（哪怕是读）就 BEGIN IMMEDIATE，写锁到手
            with impatient.session(write=False) as r:  # WAL：读照常
                assert r.execute(select(1)).scalar() == 1
            t0 = time.monotonic()
            with pytest.raises(OperationalError, match="locked"):
                with impatient.session() as b:
                    b.execute(select(1))
            assert time.monotonic() - t0 >= 0.15  # 等了 busy_timeout 才放弃，不是一上来就失败
        with impatient.session() as b:  # 前一个提交了，马上拿得到
            record_event(b, "t.after", "x:1", {})
    finally:
        holder.dispose()
        impatient.dispose()


@pytest.mark.skipif(not PG_MODE, reason="只 PostgreSQL：行锁")
def test_pg_lock_row_makes_second_transaction_wait(db_):
    with db_.session() as db:
        ev = record_event(db, "t.row", "x:1", {"n": 0})
        db.flush()
        eid = ev.id
    started = threading.Event()

    def first():
        with db_.session() as db:
            e = db.get(Event, eid)
            lock_row(db, e)
            started.set()
            time.sleep(0.5)
            e.content = {"n": 1}
        return utcnow()

    def second():
        started.wait(5)
        with db_.session() as db:
            e = db.get(Event, eid)
            lock_row(db, e)  # 等第一个提交
            return utcnow(), dict(e.content)

    t_first, (t_second, seen) = no_errors(run_at_once([first, second]))
    assert t_second >= t_first and seen == {"n": 1}  # 拿到锁时看到的是第一个改完的


@pytest.mark.skipif(not PG_MODE, reason="只 PostgreSQL：事务锁")
def test_pg_txn_lock_serializes(db_):
    spans: list[tuple[float, float]] = []
    lock = threading.Lock()

    def work():
        with db_.session() as db:
            txn_lock(db, "test.quota")
            t0 = time.monotonic()
            db.execute(text("SELECT pg_sleep(0.2)"))
            with lock:
                spans.append((t0, time.monotonic()))

    no_errors(run_at_once([work] * 3))
    spans.sort()
    assert all(spans[i][1] <= spans[i + 1][0] + 0.01 for i in range(len(spans) - 1)), spans


def test_read_session_can_write_after_others_committed(db_):
    """读会话（GET）里先读、别人提交了一笔、再写：不报 database is locked（SQLite 读会话不留旧快照，写之前才占锁）。"""
    with db_.session() as db:
        record_event(db, "t.seed", "x:1", {})
    r = db_.read_sessionmaker()
    try:
        assert r.scalar(select(Event.id).limit(1)) is not None  # 先读
        with db_.session() as w:  # 别人提交了一笔
            record_event(w, "t.other", "x:2", {})
        record_event(r, "t.mine", "x:3", {})  # 再写
        r.commit()
    finally:
        r.close()
    with db_.session(write=False) as db:
        assert set(db.scalars(select(Event.type).where(Event.type.like("t.%")))) == {"t.seed", "t.other", "t.mine"}
