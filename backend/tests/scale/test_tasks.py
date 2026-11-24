"""后台任务（设计第六节）：多个 worker 同时跑不重复、重试退避、死信、租约过期接手、定时任务同一时刻只一个、
接单机器人任务每条只跑一次且同一客户不并行、网站进程可以不跑后台任务（交给 worker）。两种库都跑。"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core import tasks
from app.core.db import Database, utcnow
from app.core.tasks import Lease, Scheduler, Task, claim_tasks, enqueue, finish_task, try_lease
from app.intake import service
from app.intake.models import Job
from app.intake.runtime import IntakeRuntime
from app.intake.worker import run_due_jobs
from app.main import create_app
from app.worker import run_worker
from tests.conftest import make_settings
from tests.intake.helpers import make_ctx
from tests.scale.helpers import no_errors, run_at_once


@pytest.fixture
def db_(settings):
    d = Database(settings.DATABASE_URL)
    yield d
    d.dispose()


def _drain(database: Database, holder: str, seen: list[int], lock: threading.Lock) -> int:
    n = 0
    while True:
        batch = claim_tasks(database, holder, limit=3, lease_sec=60, kinds=["test.count"])
        if not batch:
            return n
        for t in batch:
            with lock:
                seen.append(t.payload["i"])
            time.sleep(0.002)
            finish_task(database, t.id, holder, ok=True, attempt=t.attempt, max_attempts=t.max_attempts)
            n += 1


def test_many_workers_each_task_once(db_):
    """60 个任务，4 个 worker 同时领：每个任务只被处理一次，全部做完。"""
    with db_.session() as db:
        for i in range(60):
            enqueue(db, "test.count", {"i": i})
    seen: list[int] = []
    lock = threading.Lock()
    counts = no_errors(run_at_once([lambda h=h: _drain(db_, f"w{h}", seen, lock) for h in range(4)]))
    assert sorted(seen) == list(range(60)), "有任务被处理了两次或漏了"
    assert sum(counts) == 60
    with db_.session() as db:
        assert db.scalar(select(func.count()).select_from(Task).where(Task.status == "done")) == 60


def test_enqueue_dedupe_even_when_concurrent(db_):
    """同一个 dedupe_key 并发排 8 次：只有一条。"""
    def add():
        with db_.session() as db:
            return enqueue(db, "test.count", {"i": 1}, dedupe_key="report:2026-11-18")

    ids = no_errors(run_at_once([add] * 8))
    assert len(set(ids)) == 1
    with db_.session() as db:
        assert db.scalar(select(func.count()).select_from(Task)) == 1


def test_retry_backoff_then_dead_letter(db_):
    """失败按 30 秒 × 2^(次数-1) 退避；做满次数进死信；死信能重排。"""
    with db_.session() as db:
        enqueue(db, "test.fail", {}, max_attempts=2)
    (t,) = claim_tasks(db_, "w1", kinds=["test.fail"])
    assert finish_task(db_, t.id, "w1", ok=False, error="boom", attempt=t.attempt, max_attempts=t.max_attempts) == "pending"
    with db_.session() as db:
        row = db.get(Task, t.id)
        wait = (row.run_after - utcnow()).total_seconds()
        assert 25 < wait <= 30 and row.last_error == "boom"
    assert claim_tasks(db_, "w1", kinds=["test.fail"]) == []  # 还没到点
    (t2,) = claim_tasks(db_, "w1", kinds=["test.fail"], now=utcnow() + timedelta(seconds=31))
    assert t2.attempt == 2
    assert finish_task(db_, t2.id, "w1", ok=False, error="boom2", attempt=2, max_attempts=2) == "dead"
    m = tasks.metrics(db_)
    assert m["queue"]["test.fail"]["dead"] == 1 and m["dead"] >= 1 and {"pending", "oldest_wait_sec"} <= set(m)
    assert tasks.retry_dead(db_, t.id)
    with db_.session() as db:
        assert db.get(Task, t.id).status == "pending"


def test_expired_lease_is_taken_over(db_):
    """worker 领了任务没做完就死了：租约到期后别的 worker 接手；原来那个回来交结果也不会覆盖。"""
    with db_.session() as db:
        enqueue(db, "test.count", {"i": 1}, max_attempts=3)
    (t,) = claim_tasks(db_, "dead-worker", lease_sec=5, kinds=["test.count"])
    assert claim_tasks(db_, "w2", kinds=["test.count"]) == []
    (t2,) = claim_tasks(db_, "w2", kinds=["test.count"], now=utcnow() + timedelta(seconds=6))
    assert t2.id == t.id and t2.attempt == 2
    finish_task(db_, t.id, "dead-worker", ok=True)  # 不是它的了，不算数
    with db_.session() as db:
        assert db.get(Task, t.id).status == "running"
    finish_task(db_, t.id, "w2", ok=True)
    with db_.session() as db:
        assert db.get(Task, t.id).status == "done"


def test_lease_only_one_holder(db_):
    got = no_errors(run_at_once([lambda h=h: try_lease(db_, "sched:x", f"h{h}", 30) for h in range(8)]))
    assert got.count(True) == 1
    with db_.session() as db:
        assert db.scalar(select(func.count()).select_from(Lease)) == 1


def test_singleton_job_never_overlaps_across_schedulers(db_):
    """两个进程（两个调度器）都登记同一个定时任务：任何时刻只有一个在跑。"""
    state = {"active": 0, "max": 0, "runs": 0}
    lock = threading.Lock()

    def job() -> None:
        with lock:
            state["active"] += 1
            state["max"] = max(state["max"], state["active"])
            state["runs"] += 1
        time.sleep(0.05)
        with lock:
            state["active"] -= 1

    def loop(name: str) -> None:
        s = Scheduler(database=db_, holder=name, poll_sec=0.01)
        s.every("test.singleton", 0.01, job)
        end = time.monotonic() + 1.5
        while time.monotonic() < end:
            asyncio.run(s.run_once())
            time.sleep(0.005)

    no_errors(run_at_once([lambda: loop("p1"), lambda: loop("p2")]))
    assert state["max"] == 1 and state["runs"] >= 3, state


@dataclass
class _Runner:
    calls: list[int]
    lock: threading.Lock
    active: dict[int, int]
    overlap: list[int]

    async def run_for_customer(self, database, ctx, customer_id):
        with self.lock:
            self.calls.append(customer_id)
            self.active[customer_id] = self.active.get(customer_id, 0) + 1
            if self.active[customer_id] > 1:
                self.overlap.append(customer_id)
        await asyncio.sleep(0.02)
        with self.lock:
            self.active[customer_id] -= 1
        return None


def test_intake_bot_jobs_run_once_across_workers(db_, tmp_path, notifier):
    """12 个客户各有一条待跑的机器人任务，4 个进程同时领：每条只跑一次，同一客户不会两个进程同时跑。"""
    ctx = make_ctx(tmp_path, notifier)
    with db_.session() as db:
        cids = [service.get_or_create_customer(db, "web", f"key-job-{i:02d}-0123456789").id for i in range(12)]
        for cid in cids:
            db.add(Job(customer_id=cid, run_after=utcnow() - timedelta(seconds=1), created_at=utcnow(), updated_at=utcnow()))
    runner = _Runner([], threading.Lock(), {}, [])
    rt = IntakeRuntime(ctx, runner, db_)  # type: ignore[arg-type]

    def worker() -> int:
        n = 0
        while (k := asyncio.run(run_due_jobs(rt, limit=2))) > 0:
            n += k
        return n

    done = no_errors(run_at_once([worker] * 4))
    assert sorted(runner.calls) == sorted(cids) and sum(done) == 12 and runner.overlap == []
    with db_.session() as db:
        assert db.scalar(select(func.count()).select_from(Job).where(Job.status == "done")) == 12


def test_intake_job_waits_while_same_customer_running(db_, tmp_path, notifier):
    """同一客户正有别的进程在跑（拿着租约）：这条放回去、不算次数，租约放了再跑。"""
    ctx = make_ctx(tmp_path, notifier)
    with db_.session() as db:
        cid = service.get_or_create_customer(db, "web", "key-busy-0123456789").id
        db.add(Job(customer_id=cid, run_after=utcnow() - timedelta(seconds=1), created_at=utcnow(), updated_at=utcnow()))
    assert try_lease(db_, f"intake.customer:{cid}", "other-process", 600)
    runner = _Runner([], threading.Lock(), {}, [])
    rt = IntakeRuntime(ctx, runner, db_)  # type: ignore[arg-type]
    assert asyncio.run(run_due_jobs(rt)) == 0 and runner.calls == []
    with db_.session() as db:
        job = db.scalar(select(Job))
        assert job.status == "pending" and job.attempts == 0
    tasks.release_lease(db_, f"intake.customer:{cid}", "other-process", forget=True)
    asyncio.run(run_due_jobs(rt, now=utcnow() + timedelta(seconds=3)))
    assert runner.calls == [cid]


def test_stuck_running_job_is_reclaimed_after_lease(db_, tmp_path, notifier):
    """进程死在半路：running 超过租约没动静的任务，别的进程重新领（不再「一启动就把所有 running 放回去」）。"""
    ctx = make_ctx(tmp_path, notifier)
    with db_.session() as db:
        cid = service.get_or_create_customer(db, "web", "key-stuck-0123456789").id
        db.add(Job(customer_id=cid, status="running", attempts=1, run_after=utcnow() - timedelta(minutes=30),
                   created_at=utcnow(), updated_at=utcnow() - timedelta(minutes=11)))
        fresh = service.get_or_create_customer(db, "web", "key-fresh-0123456789").id
        db.add(Job(customer_id=fresh, status="running", attempts=1, run_after=utcnow(), created_at=utcnow(), updated_at=utcnow()))
    runner = _Runner([], threading.Lock(), {}, [])
    assert asyncio.run(run_due_jobs(IntakeRuntime(ctx, runner, db_))) == 1  # type: ignore[arg-type]
    assert runner.calls == [cid]  # 刚开始跑的那条（别的进程正在做）不动


def test_web_process_can_leave_background_to_worker(tmp_path, notifier):
    """BACKGROUND_IN_WEB=false：网站进程不跑后台任务；worker（python -m app.worker）跑同一批登记好的任务。"""
    from app.core.migrate import upgrade_to_heads

    s = make_settings(tmp_path, BACKGROUND_IN_WEB=False)
    upgrade_to_heads(s.DATABASE_URL)
    ran: list[str] = []

    @tasks.task_handler("test.web_vs_worker")
    def _h(app, payload):
        ran.append(payload["who"])

    try:
        web = create_app(s, notifier=notifier)
        with TestClient(web):
            assert web.state.scheduler.running is False
            with web.state.db.session() as db:
                enqueue(db, "test.web_vs_worker", {"who": "queued-from-web"})
            time.sleep(0.3)
            assert ran == []
        worker = create_app(s, notifier=notifier, role="worker")
        asyncio.run(run_worker(worker, once=True))
        assert ran == ["queued-from-web"]
        assert "intake.bot_jobs" in worker.state.scheduler.jobs and "delivery.tick" in worker.state.scheduler.jobs
    finally:
        tasks._HANDLERS.pop("test.web_vs_worker", None)


def test_stop_waits_for_running_job_then_releases_lease(db_):
    """收到退出信号（stop）：手上这件做完再停，租约放掉，别的进程马上能接着跑。"""
    done = threading.Event()

    def slow() -> None:
        time.sleep(0.4)
        done.set()

    async def go() -> None:
        s = Scheduler(database=db_, holder="graceful", poll_sec=0.01)
        s.every("test.graceful", 60, slow)
        task = asyncio.create_task(s.run_forever())
        await asyncio.sleep(0.1)
        s.stop()
        await asyncio.wait_for(task, 5)

    asyncio.run(go())
    assert done.is_set()
    with db_.session() as db:
        lease = db.get(Lease, "sched:test.graceful")
        assert lease.lease_until is None and lease.runs == 1 and lease.next_run_at is not None
