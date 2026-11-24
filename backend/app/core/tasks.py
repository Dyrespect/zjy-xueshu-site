"""后台任务：库表排队 + 租约锁 + 定时任务调度。网站进程和 worker 进程用同一套，多开几个也不重复处理。

设计：docs/任务单/07_底座可扩展_设计.md 第六节。三样东西：

1. 队列（表 core_tasks）：`enqueue(db, kind, payload)` 跟业务同一个事务提交，提交了才会被领；
   `@task_handler(kind)` 登记处理函数。失败按 30 秒 × 2^(次数-1) 退避（上限 1 小时），做满 max_attempts 次进
   dead（死信）。领任务：PG 用 FOR UPDATE SKIP LOCKED，SQLite 靠写会话独占（BEGIN IMMEDIATE）+ 带条件的
   UPDATE；进程死了，任务的租约到期后别的 worker 会重新领。
2. 租约锁（表 core_leases）：一个名字同一时刻只有一个持有人，到期自动作废。定时任务、「同一客户同时只跑一个」都用它。
3. 调度器（Scheduler，挂在 app.state.scheduler）：各模块在 lifespan 里 `scheduler.every(名字, 秒, 函数)` 登记；
   singleton=True 的定时任务全集群同一时刻只一个在跑（租约锁 + 跑的时候自动续租）、两次之间至少隔 every 秒；
   singleton=False 的每个进程都跑（比如领队列任务，靠领的时候抢占保证不重复）。
   网站进程里跑不跑由 BACKGROUND_IN_WEB 定；`python -m app.worker` 专门跑它。

可观测：`metrics(database)` 给队列长度、最老一条等了多久、死信数、每个定时任务上次耗时和出错（运维采）；
各模块还能 `register_gauge(名字, 函数)` 加自己的队列（接单任务、出水印图）。
"""

from __future__ import annotations

import asyncio
import inspect as pyinspect
import logging
import os
import secrets
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import JSON, Index, Integer, String, Text, and_, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.db import Base, Database, UTCDateTime, utcnow

log = logging.getLogger("app.tasks")

BACKOFF_BASE_SEC = 30.0
BACKOFF_MAX_SEC = 3600.0
DEFAULT_MAX_ATTEMPTS = 5


# ---------------------------------------------------------------- 表

class Task(Base):
    __tablename__ = "core_tasks"
    __table_args__ = (Index("ix_core_tasks_status_run_after", "status", "run_after"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    dedupe_key: Mapped[str | None] = mapped_column(String(160), unique=True, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | running | done | dead
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=DEFAULT_MAX_ATTEMPTS)
    run_after: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    locked_by: Mapped[str] = mapped_column(String(96), default="")
    lease_until: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class Lease(Base):
    __tablename__ = "core_leases"

    name: Mapped[str] = mapped_column(String(128), primary_key=True)
    holder: Mapped[str] = mapped_column(String(96), default="")
    lease_until: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str] = mapped_column(Text, default="")
    runs: Mapped[int] = mapped_column(Integer, default=0)


def new_holder(role: str = "proc") -> str:
    """这个进程的名字（租约、任务上记谁在做）：角色@主机:进程号:随机。"""
    return f"{role}@{socket.gethostname()[:40]}:{os.getpid()}:{secrets.token_hex(3)}"


# ---------------------------------------------------------------- 队列

Handler = Callable[[Any, dict[str, Any]], Any]  # (app, payload) -> 任意；可以是 async
_HANDLERS: dict[str, Handler] = {}  # 登记表：import 时写一次，之后只读（不是跨请求状态）


def task_handler(kind: str) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        _HANDLERS[kind] = fn
        return fn
    return deco


def handler_for(kind: str) -> Handler | None:
    return _HANDLERS.get(kind)


def enqueue(db: Session, kind: str, payload: dict[str, Any] | None = None, *, dedupe_key: str | None = None,
            run_after: datetime | None = None, max_attempts: int = DEFAULT_MAX_ATTEMPTS) -> int:
    """排一个任务，跟调用方的事务一起提交。同一 dedupe_key 只排一次（返回已有那条的 id）。"""
    if dedupe_key:
        old = db.scalar(select(Task.id).where(Task.dedupe_key == dedupe_key))
        if old is not None:
            return old
    now = utcnow()
    t = Task(kind=kind, payload=payload or {}, dedupe_key=dedupe_key or None, run_after=run_after or now,
             max_attempts=max(1, max_attempts), created_at=now, updated_at=now)
    if not dedupe_key:
        db.add(t)
        db.flush()
        return t.id
    try:
        with db.begin_nested():  # 并发时另一个事务刚排了同一个 key：只回滚这一条，不连累调用方
            db.add(t)
            db.flush()
        return t.id
    except IntegrityError:
        return db.scalar(select(Task.id).where(Task.dedupe_key == dedupe_key))


def backoff_seconds(attempt: int) -> float:
    return min(BACKOFF_MAX_SEC, BACKOFF_BASE_SEC * (2 ** max(0, attempt - 1)))


@dataclass
class Claimed:
    id: int
    kind: str
    payload: dict[str, Any]
    attempt: int
    max_attempts: int


def claim_tasks(database: Database, holder: str, *, limit: int = 5, lease_sec: float = 300.0,
                kinds: list[str] | None = None, now: datetime | None = None) -> list[Claimed]:
    """领几条到期的任务（含租约过期没做完的）。多个进程同时领，每条只会被一个领到。

    先用读会话看一眼有没有活：没活就不碰写锁（SQLite 整库一个写锁，空转的 worker 每秒抢一次会挡住网站的写）。"""
    out: list[Claimed] = []
    now = now or utcnow()
    due = or_(and_(Task.status == "pending", Task.run_after <= now),
              and_(Task.status == "running", Task.lease_until < now))
    with database.session(write=False) as db:
        probe = select(Task.id).where(due)
        if kinds:
            probe = probe.where(Task.kind.in_(kinds))
        if db.scalar(probe.limit(1)) is None:
            return out
    with database.session() as db:  # 写会话：SQLite 上一开始就独占写锁
        stmt = select(Task).where(due)
        if kinds:
            stmt = stmt.where(Task.kind.in_(kinds))
        stmt = stmt.order_by(Task.run_after, Task.id).limit(limit).with_for_update(skip_locked=True)
        for t in db.scalars(stmt).all():
            if t.attempts >= t.max_attempts:  # 做到一半进程死了好几次：不再领，进死信
                db.execute(update(Task).where(Task.id == t.id, Task.status == t.status).values(
                    status="dead", lease_until=None, updated_at=now, finished_at=now,
                    last_error=(t.last_error or "租约过期次数用完（进程中途退出）")[:4000],
                ).execution_options(synchronize_session=False))
                continue
            res = db.execute(update(Task).where(Task.id == t.id, Task.status == t.status, Task.attempts == t.attempts).values(
                status="running", locked_by=holder[:96], lease_until=now + timedelta(seconds=lease_sec),
                attempts=t.attempts + 1, updated_at=now,
            ).execution_options(synchronize_session=False))
            if res.rowcount == 1:
                out.append(Claimed(t.id, t.kind, dict(t.payload or {}), t.attempts + 1, t.max_attempts))
    return out


def finish_task(database: Database, task_id: int, holder: str, *, ok: bool, error: str = "", duration_ms: int = 0,
                attempt: int = 1, max_attempts: int = DEFAULT_MAX_ATTEMPTS) -> str:
    """记结果。只认自己领的（别人接手了就不覆盖）。返回新状态。"""
    now = utcnow()
    if ok:
        values: dict[str, Any] = dict(status="done", finished_at=now, last_error="")
    elif attempt >= max_attempts:
        values = dict(status="dead", finished_at=now, last_error=error[:4000])
    else:
        values = dict(status="pending", run_after=now + timedelta(seconds=backoff_seconds(attempt)), last_error=error[:4000])
    values.update(lease_until=None, updated_at=now, duration_ms=duration_ms)
    with database.session() as db:
        db.execute(update(Task).where(Task.id == task_id, Task.locked_by == holder[:96], Task.status == "running")
                   .values(**values).execution_options(synchronize_session=False))
    return values["status"]


def retry_dead(database: Database, task_id: int) -> bool:
    """死信重排（后台按钮用）：次数清零，马上可领。"""
    with database.session() as db:
        res = db.execute(update(Task).where(Task.id == task_id, Task.status == "dead").values(
            status="pending", attempts=0, run_after=utcnow(), finished_at=None, updated_at=utcnow(),
        ).execution_options(synchronize_session=False))
        return res.rowcount == 1


async def _call(fn: Callable[..., Any], *args: Any) -> Any:
    if pyinspect.iscoroutinefunction(fn):
        return await fn(*args)
    res = await asyncio.to_thread(fn, *args)
    if pyinspect.isawaitable(res):
        return await res
    return res


async def run_claimed(app: Any, database: Database, holder: str, task: Claimed) -> str:
    fn = handler_for(task.kind)
    t0 = time.perf_counter()
    if fn is None:
        return finish_task(database, task.id, holder, ok=False, error=f"没有登记处理函数：{task.kind}",
                           attempt=task.max_attempts, max_attempts=task.max_attempts)
    try:
        await _call(fn, app, task.payload)
    except Exception as e:  # noqa: BLE001 - 一条出错不能把 worker 卡死
        log.exception("任务 %s#%s 第 %s 次失败", task.kind, task.id, task.attempt)
        return finish_task(database, task.id, holder, ok=False, error=f"{type(e).__name__}: {e}",
                           duration_ms=int((time.perf_counter() - t0) * 1000), attempt=task.attempt,
                           max_attempts=task.max_attempts)
    return finish_task(database, task.id, holder, ok=True, duration_ms=int((time.perf_counter() - t0) * 1000))


# ---------------------------------------------------------------- 租约锁

def try_lease(database: Database, name: str, holder: str, ttl_sec: float, *, require_due: bool = False,
              now: datetime | None = None) -> bool:
    """拿租约：没人持有、上一个过期了、或者本来就是我的 → 拿到。require_due：还要 next_run_at 到了（定时任务）。
    先用读会话看：明显拿不到（别人拿着没过期、还没到点）就不碰写锁。"""
    now = now or utcnow()
    with database.session(write=False) as db:
        cur = db.get(Lease, name)
        if cur is not None:
            held = cur.lease_until is not None and cur.lease_until >= now and cur.holder != holder[:96]
            early = require_due and cur.next_run_at is not None and cur.next_run_at > now
            if held or early:
                return False
    with database.session() as db:
        until = now + timedelta(seconds=ttl_sec)
        row = db.get(Lease, name)
        if row is None:
            try:
                with db.begin_nested():
                    db.add(Lease(name=name[:128], holder=holder[:96], lease_until=until))
                    db.flush()
                return True
            except IntegrityError:
                return False  # 另一个进程刚建了这一行，它先拿到
        free = or_(Lease.lease_until.is_(None), Lease.lease_until < now, Lease.holder == holder[:96])
        cond = [Lease.name == name, free]
        if require_due:
            cond.append(or_(Lease.next_run_at.is_(None), Lease.next_run_at <= now))
        res = db.execute(update(Lease).where(*cond).values(holder=holder[:96], lease_until=until)
                         .execution_options(synchronize_session=False))
        return res.rowcount == 1


def renew_lease(database: Database, name: str, holder: str, ttl_sec: float) -> bool:
    with database.session() as db:
        res = db.execute(update(Lease).where(Lease.name == name, Lease.holder == holder[:96]).values(
            lease_until=utcnow() + timedelta(seconds=ttl_sec)).execution_options(synchronize_session=False))
        return res.rowcount == 1


def release_lease(database: Database, name: str, holder: str, *, next_run_at: datetime | None = None,
                  duration_ms: int | None = None, error: str | None = None, forget: bool = False) -> None:
    """放掉租约。forget：整行删掉（「同一客户同时只一个」这类一次性的锁，不留行）。"""
    with database.session() as db:
        if forget:
            db.execute(delete(Lease).where(Lease.name == name, Lease.holder == holder[:96]))
            return
        values: dict[str, Any] = {"lease_until": None}
        if next_run_at is not None:
            values.update(next_run_at=next_run_at, last_run_at=utcnow(), runs=Lease.runs + 1)
        if duration_ms is not None:
            values["last_duration_ms"] = duration_ms
        if error is not None:
            values["last_error"] = error[:4000]
        db.execute(update(Lease).where(Lease.name == name, Lease.holder == holder[:96]).values(**values)
                   .execution_options(synchronize_session=False))


# ---------------------------------------------------------------- 调度器

@dataclass
class Periodic:
    name: str
    every: float
    fn: Callable[[], Any]
    singleton: bool = True
    ttl: float = 300.0
    next_local: float = 0.0  # 这个进程下次看它的时间（time.monotonic）


@dataclass
class Scheduler:
    """各模块登记定时任务；run_forever 一圈圈跑。网站进程（BACKGROUND_IN_WEB）和 worker 都用它。"""

    database: Database
    app: Any = None
    holder: str = field(default_factory=lambda: new_holder("sched"))
    poll_sec: float = 1.0
    lease_sec: float = 300.0
    task_batch: int = 5
    jobs: dict[str, Periodic] = field(default_factory=dict)
    running: bool = False
    _stop: asyncio.Event | None = None
    _busy: str = ""  # 正在跑的那个（日志、优雅退出用）

    def every(self, name: str, seconds: float, fn: Callable[[], Any], *, singleton: bool = True,
              ttl: float | None = None, initial_delay: float = 0.0) -> None:
        """登记定时任务。fn 不带参数，可以是普通函数（放到线程里跑）或 async 函数。同名再登记会替换。"""
        self.jobs[name] = Periodic(name, max(0.05, float(seconds)), fn, singleton, ttl or max(self.lease_sec, seconds * 3),
                                   time.monotonic() + max(0.0, initial_delay))

    def stop(self) -> None:
        if self._stop is not None:
            self._stop.set()

    @property
    def stopping(self) -> bool:
        return self._stop is not None and self._stop.is_set()

    async def _heartbeat(self, name: str, ttl: float) -> None:
        while True:
            await asyncio.sleep(max(1.0, ttl / 3))
            ok = await asyncio.to_thread(renew_lease, self.database, name, self.holder, ttl)
            if not ok:
                log.warning("定时任务 %s 的租约续不上了（被别人接手？）", name)

    async def _run_job(self, job: Periodic) -> None:
        if job.singleton:
            got = await asyncio.to_thread(try_lease, self.database, f"sched:{job.name}", self.holder, job.ttl,
                                          require_due=True)
            if not got:
                job.next_local = time.monotonic() + min(job.every, 5.0)
                return
        self._busy = job.name
        hb = asyncio.create_task(self._heartbeat(f"sched:{job.name}", job.ttl)) if job.singleton else None
        t0 = time.perf_counter()
        error = ""
        try:
            await _call(job.fn)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - 一圈出错不停，下一圈再来
            error = f"{type(e).__name__}: {e}"
            log.exception("定时任务 %s 出错", job.name)
        finally:
            if hb is not None:
                hb.cancel()
            self._busy = ""
        ms = int((time.perf_counter() - t0) * 1000)
        job.next_local = time.monotonic() + job.every
        if job.singleton:
            await asyncio.to_thread(release_lease, self.database, f"sched:{job.name}", self.holder,
                                    next_run_at=utcnow() + timedelta(seconds=job.every), duration_ms=ms, error=error)

    async def drain_tasks(self) -> int:
        """领一批队列任务做完。返回做了几条。"""
        if not _HANDLERS:
            return 0
        batch = await asyncio.to_thread(claim_tasks, self.database, self.holder, limit=self.task_batch,
                                        lease_sec=self.lease_sec, kinds=list(_HANDLERS))
        for t in batch:
            self._busy = f"task:{t.kind}#{t.id}"
            try:
                await run_claimed(self.app, self.database, self.holder, t)
            finally:
                self._busy = ""
        return len(batch)

    async def run_once(self) -> None:
        """跑一圈：到点的定时任务 + 一批队列任务。"""
        now = time.monotonic()
        for job in list(self.jobs.values()):
            if self.stopping:
                return
            if job.next_local <= now:
                await self._run_job(job)
        if not self.stopping:
            await self.drain_tasks()

    async def run_forever(self) -> None:
        self._stop = asyncio.Event()
        self.running = True
        log.info("调度器启动：%s，定时任务 %s", self.holder, sorted(self.jobs))
        try:
            while not self._stop.is_set():
                try:
                    await self.run_once()
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001
                    log.exception("调度器这一圈出错")
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self.poll_sec)
                except asyncio.TimeoutError:
                    pass
        finally:
            self.running = False
            log.info("调度器停了：%s", self.holder)


def build_scheduler(database: Database, settings: Any, app: Any = None, role: str = "web") -> Scheduler:
    s = Scheduler(database=database, app=app, holder=new_holder(role), poll_sec=settings.WORKER_POLL_SEC,
                  lease_sec=settings.TASK_LEASE_SEC)
    s.every("core.prune", 600, lambda: prune(database, limiter=getattr(app, "state", None) and getattr(app.state, "ratelimit", None)),
            initial_delay=30)
    return s


# ---------------------------------------------------------------- 清理和指标

Gauge = Callable[[Session], dict[str, Any]]
_GAUGES: dict[str, Gauge] = {}  # 登记表：模块 import / 启动时写一次


def register_gauge(name: str, fn: Gauge) -> None:
    """模块加自己的队列指标（比如接单任务排了几条）。fn(db) -> {"pending": 3, ...}。"""
    _GAUGES[name] = fn


def prune(database: Database, *, limiter: Any = None, keep_done_days: int = 14) -> dict[str, int]:
    """删掉做完两周的任务、过期的一次性租约、两天前的限流记录（限流在哪个库由限流器自己知道）。"""
    from app.core.ratelimit import prune_rate_events  # 同在 core，免得互相 import 打圈

    now = utcnow()
    with database.session() as db:
        done = db.execute(delete(Task).where(Task.status == "done", Task.finished_at < now - timedelta(days=keep_done_days))).rowcount
        stale = db.execute(delete(Lease).where(~Lease.name.like("sched:%"), Lease.lease_until < now - timedelta(hours=1))).rowcount
    rate = limiter.prune() if limiter is not None else prune_rate_events(database)
    return {"tasks": done or 0, "leases": stale or 0, "rate_events": rate}


def metrics(database: Database) -> dict[str, Any]:
    """队列和定时任务的指标（运维采）。"""
    now = utcnow()
    out: dict[str, Any] = {"at": now.isoformat(), "queue": {}, "scheduled": {}, "gauges": {}}
    with database.session(write=False) as db:
        rows = db.execute(select(Task.kind, Task.status, func.count(), func.min(Task.run_after))
                          .where(Task.status != "done").group_by(Task.kind, Task.status)).all()
        for kind, status, n, oldest in rows:
            q = out["queue"].setdefault(kind, {"pending": 0, "running": 0, "dead": 0, "oldest_pending_sec": 0})
            q[status] = n
            if status == "pending" and oldest is not None:
                oldest = oldest if oldest.tzinfo else oldest.replace(tzinfo=now.tzinfo)
                q["oldest_pending_sec"] = max(0, int((now - oldest).total_seconds()))
        avg = db.execute(select(Task.kind, func.avg(Task.duration_ms), func.count()).where(
            Task.status == "done", Task.finished_at >= now - timedelta(hours=1)).group_by(Task.kind)).all()
        for kind, ms, n in avg:
            q = out["queue"].setdefault(kind, {"pending": 0, "running": 0, "dead": 0, "oldest_pending_sec": 0})
            q.update(done_last_hour=n, avg_ms_last_hour=int(ms or 0))
        for lease in db.scalars(select(Lease).where(Lease.name.like("sched:%"))):
            out["scheduled"][lease.name[6:]] = {
                "running_now": bool(lease.lease_until and lease.lease_until > now), "holder": lease.holder,
                "last_run_at": lease.last_run_at.isoformat() if lease.last_run_at else None,
                "last_duration_ms": lease.last_duration_ms, "last_error": lease.last_error[:300], "runs": lease.runs,
            }
        for name, fn in _GAUGES.items():
            try:
                out["gauges"][name] = fn(db)
            except Exception as e:  # noqa: BLE001 - 一个指标坏了不影响别的
                out["gauges"][name] = {"error": f"{type(e).__name__}: {e}"[:200]}
    # 合计（运维页 admin/ops_sources.py 读这几个）：队列 + 各模块自己的队列（接单任务、出图）
    parts = list(out["queue"].values()) + [g for g in out["gauges"].values() if isinstance(g, dict)]
    out["pending"] = sum(int(p.get("pending", 0) or 0) for p in parts)
    out["running"] = sum(int(p.get("running", 0) or 0) + int(p.get("rendering", 0) or 0) for p in parts)
    out["dead"] = sum(int(p.get("dead", 0) or 0) + int(p.get("failed", 0) or 0) for p in parts)
    out["oldest_wait_sec"] = max([int(p.get("oldest_pending_sec", 0) or 0) for p in parts] or [0])
    return out

