"""后台工人：领到点的任务跑机器人；每分钟看一次有没有排到今天的单要交接给工厂。

任务表在库里，进程重启不丢。接单 v2 没人批了：模型挂了（超时、中转出错）这一趟没回客户，过 RETRY_AFTER 秒再试一次（最多 MAX_ATTEMPTS 次）。

多进程（11-18 底座可扩展，docs/任务单/07_底座可扩展_设计.md）：这两件事登记到底座的调度器（core.tasks），
网站进程（BACKGROUND_IN_WEB）或 `python -m app.worker` 跑，开几个都不重复：
- 领任务是带条件的 UPDATE（pending → running，只有一个进程改得动）；PG 上再加 SKIP LOCKED。
- 同一个客户同一时刻只跑一趟（租约锁 intake.customer:<id>），不然两个进程会对同一段对话各回一遍。
- 进程死了：running 超过 JOB_LEASE 没动静就当没做完，别的进程重新领（不再「启动时把所有 running 放回去」，那样会抢别人正在做的）。
- 交接工厂是全集群一个在跑（singleton）。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.tasks import Scheduler, new_holder, register_gauge, release_lease, try_lease
from app.intake.models import Job
from app.intake.runtime import IntakeRuntime
from app.intake.service import handoff_due_orders

log = logging.getLogger("app.intake.worker")

MAX_ATTEMPTS = 2
RETRY_AFTER = 20.0
JOB_LEASE = timedelta(minutes=10)  # 跑一趟机器人最多多久；过了还是 running 就当进程死了


def _claim(rt: IntakeRuntime, now: datetime, limit: int) -> list[tuple[int, int, int]]:
    """领到期的任务（含卡住超时的）。返回 [(任务 id, 客户 id, 第几次)]。多个进程同时领，每条只有一个领到。"""
    picked: list[tuple[int, int, int]] = []
    due = or_(and_(Job.status == "pending", Job.run_after <= now),
              and_(Job.status == "running", Job.updated_at < now - JOB_LEASE))
    with rt.database.session(write=False) as db:  # 先用读会话看有没有活：没活不碰写锁（SQLite 整库一个写锁）
        if db.scalar(select(Job.id).where(due).limit(1)) is None:
            return picked
    with rt.database.session() as db:
        jobs = db.scalars(select(Job).where(due).order_by(Job.run_after).limit(limit).with_for_update(skip_locked=True)).all()
        for j in jobs:
            if j.status == "running" and j.attempts >= MAX_ATTEMPTS:
                db.execute(update(Job).where(Job.id == j.id, Job.status == "running").values(
                    status="failed", error=(j.error or "进程中途退出，次数用完")[:2000], updated_at=now))
                continue
            res = db.execute(update(Job).where(Job.id == j.id, Job.status == j.status, Job.attempts == j.attempts)
                             .values(status="running", attempts=j.attempts + 1, updated_at=now)
                             .execution_options(synchronize_session=False))
            if res.rowcount == 1:
                picked.append((j.id, j.customer_id, j.attempts + 1))
    return picked


def _finish(rt: IntakeRuntime, job_id: int, attempt: int, status: str, error: str) -> None:
    with rt.database.session() as db:
        job = db.get(Job, job_id)
        job.status = status
        job.error = error[:2000]
        job.updated_at = utcnow()
        if status == "failed" and attempt < MAX_ATTEMPTS:
            job.status = "pending"
            job.run_after = utcnow() + timedelta(seconds=RETRY_AFTER)


def _put_back(rt: IntakeRuntime, job_id: int) -> None:
    """这个客户正有别的进程在跑：放回去过两秒再领，这次不算次数。"""
    with rt.database.session() as db:
        db.execute(update(Job).where(Job.id == job_id, Job.status == "running").values(
            status="pending", attempts=Job.attempts - 1, run_after=utcnow() + timedelta(seconds=2), updated_at=utcnow()))


async def run_due_jobs(rt: IntakeRuntime, *, now: datetime | None = None, limit: int = 5) -> int:
    picked = await asyncio.to_thread(_claim, rt, now or utcnow(), limit)
    holder = new_holder("intake")
    done = 0
    for job_id, customer_id, attempt in picked:
        lease = f"intake.customer:{customer_id}"
        got = await asyncio.to_thread(try_lease, rt.database, lease, holder, JOB_LEASE.total_seconds())
        if not got:
            await asyncio.to_thread(_put_back, rt, job_id)
            continue
        status, error = "done", ""
        try:
            run = await rt.runner.run_for_customer(rt.database, rt.ctx, customer_id)
            if run is not None and run.error:
                status, error = "failed", run.error
        except Exception as e:  # 一单出错不能把工人卡死
            log.exception("任务 %s 出错", job_id)
            status, error = "failed", f"{type(e).__name__}: {e}"
        finally:
            await asyncio.to_thread(release_lease, rt.database, lease, holder, forget=True)
        await asyncio.to_thread(_finish, rt, job_id, attempt, status, error)
        done += 1
    return done


def handoff_tick(rt: IntakeRuntime) -> list[int]:
    with rt.database.session() as db:
        return handoff_due_orders(db, rt.ctx)


def _jobs_gauge(db: Session) -> dict[str, Any]:
    rows = dict(db.execute(select(Job.status, func.count()).group_by(Job.status)).all())
    oldest = db.scalar(select(func.min(Job.run_after)).where(Job.status == "pending"))
    age = 0
    if oldest is not None:
        age = max(0, int((utcnow() - (oldest if oldest.tzinfo else oldest.replace(tzinfo=utcnow().tzinfo))).total_seconds()))
    return {"pending": rows.get("pending", 0), "running": rows.get("running", 0), "failed": rows.get("failed", 0),
            "oldest_pending_sec": age}


def register(sched: Scheduler, rt: IntakeRuntime, *, interval: float = 1.0) -> None:
    """接单的两件后台事登记到调度器（intake/router.py 的 lifespan 调）。"""
    sched.every("intake.bot_jobs", interval, lambda: run_due_jobs(rt), singleton=False)
    sched.every("intake.handoff", 60, lambda: handoff_tick(rt))
    register_gauge("intake.jobs", _jobs_gauge)
