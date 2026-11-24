"""运维的调度：按 ops/jobs.json（数据）跑节点。

- 每隔 OPS_TICK_SECONDS 看一圈：every_sec 到了的、at（每天几点，北京时间）到了且今天还没跑的、every_days 隔够了的，跑它的节点；
  节点出口和 after 里的 on 一样就接着跑 after 的节点。每个任务上次跑的时间、出口、出错记在 ops_kv 的 jobs 里（重启不重跑、不漏跑）。
- 每天几点的任务：过了点 catchup_hours（默认 6）小时内补跑；再晚就等明天（新部署下午起来，不会马上发早上的日报）。
- per_process 的任务（计数落库）每个网站进程自己跑（计数在各自内存里），不走单例调度。
- 底座以后有了统一调度器（app.state.scheduler，有 every()；docs/任务单/07_底座可扩展_设计.md）就登记进去（单例：多进程只一个在跑）；
  没有就自己起一个 asyncio 圈（跟别的模块现在一样）。
成熟替代 APScheduler 也要我们自己记「今天跑过没」才能重启不漏跑，所以先用这几十行；见设计文档第三节。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.core.nodes import NodeCall, run_node
from app.ops.config import OpsConfig, jobs, kv_get, kv_set, load_config
from app.ops.runtime import OpsCtx, get_ops

log = logging.getLogger("app.ops.scheduler")


def resolve(cfg: OpsConfig, ref: Any) -> Any:
    """`config:report.time` → 设置里的值；别的原样返回。"""
    if isinstance(ref, str) and ref.startswith("config:"):
        cur: Any = cfg
        for part in ref[7:].split("."):
            cur = getattr(cur, part)
        return cur
    return ref


def is_due(job: dict[str, Any], cfg: OpsConfig, state: dict[str, Any], now: datetime, tzname: str) -> bool:
    if job.get("per_process"):
        return False
    enabled = resolve(cfg, job.get("enabled", True))
    if not enabled:
        return False
    last = state.get("last_at")
    last_at = datetime.fromisoformat(last) if last else None
    if "every_sec" in job:
        return last_at is None or (now - last_at).total_seconds() >= float(resolve(cfg, job["every_sec"])) - 1
    at = resolve(cfg, job.get("at"))
    if not at:
        return False
    z = ZoneInfo(tzname)
    local = now.astimezone(z)
    hh, mm = (int(x) for x in str(at).split(":"))
    slot = datetime.combine(local.date(), time(hh, mm), z)
    if local < slot or local > slot + timedelta(hours=float(job.get("catchup_hours", 6))):
        return False
    if last_at is not None and last_at.astimezone(z) >= slot:
        return False  # 今天这个点已经跑过
    every_days = resolve(cfg, job.get("every_days"))
    if every_days and last_at is not None and now - last_at < timedelta(days=float(every_days)) - timedelta(hours=1):
        return False
    return True


def run_job(ctx: OpsCtx, job: dict[str, Any], *, now: datetime | None = None, by: str = "system:ops") -> dict[str, Any]:
    """跑一个任务（含 after 链）。返回 {exit, error, seconds}。调用方不用管事务：每个节点一个会话、跑完提交。"""
    import time as _t

    t0 = _t.perf_counter()
    exit_, error = "", ""
    chain = [job["node"]]
    i = 0
    while i < len(chain):
        node = chain[i]
        try:
            with ctx.database.session() as db:
                r = run_node(node, NodeCall(db, ctx, by), {"now": now} if now else {})
            exit_ = r.exit if i == 0 else exit_
            if i == 0:
                chain += [a["node"] for a in job.get("after", []) if a.get("on") == r.exit]
            if r.detail and r.exit in ("fail",):
                error = r.detail[:300]
        except Exception as e:  # noqa: BLE001  一个任务坏了不影响别的
            log.exception("运维任务 %s 的节点 %s 出错", job["id"], node)
            error = f"{node}：{type(e).__name__}: {e}"[:300]
            if i == 0:
                exit_ = "fail"
        i += 1
    return {"exit": exit_, "error": error, "seconds": round(_t.perf_counter() - t0, 2)}


def tick(app: Any, now: datetime | None = None) -> list[str]:
    """看一圈，跑到点的任务。返回跑了哪些。"""
    ctx = get_ops(app)
    explicit = now  # 测试、走查才传：假装现在是几点（节点也按这个时间算）
    now = now or ctx.now()
    with ctx.database.session() as db:
        cfg = load_config(db)
        states = kv_get(db, "jobs")
    ran = []
    for job in jobs():
        st = states.get(job["id"], {})
        if not is_due(job, cfg, st, now, ctx.osettings.OPS_TIMEZONE):
            continue
        res = run_job(ctx, job, now=explicit)
        states[job["id"]] = {"last_at": now.isoformat(), "last_exit": res["exit"], "last_error": res["error"], "seconds": res["seconds"]}
        with ctx.database.session() as db:
            kv_set(db, "jobs", states)
        ran.append(job["id"])
    return ran


def flush_now(app: Any, now: datetime | None = None) -> None:
    """这个进程的计数落库（per_process 的任务）。"""
    ctx = get_ops(app)
    for job in jobs():
        if job.get("per_process"):
            run_job(ctx, job, now=now)


async def _loop(app: Any, seconds: float, fn: Any) -> None:
    while True:
        await asyncio.sleep(seconds)
        try:
            await asyncio.to_thread(fn, app)
        except Exception:  # noqa: BLE001  一圈出错不停
            log.exception("运维定时圈出错")


class Running:
    def __init__(self) -> None:
        self.tasks: list[asyncio.Task[Any]] = []

    async def stop(self) -> None:
        for t in self.tasks:
            t.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t


def start(app: Any) -> Running:
    ctx = get_ops(app)
    run = Running()
    if not ctx.osettings.OPS_TIMER_ENABLED:
        return run
    flush_every = next((float(j["every_sec"]) for j in jobs() if j.get("per_process")), 60.0)
    run.tasks.append(asyncio.create_task(_loop(app, flush_every, flush_now)))  # 计数在各进程内存里：每个网站进程自己落库
    sched = getattr(app.state, "scheduler", None)
    if sched is not None and hasattr(sched, "every"):
        sched.every("ops.tick", ctx.osettings.OPS_TICK_SECONDS, lambda: tick(app), singleton=True, initial_delay=20)
    else:
        run.tasks.append(asyncio.create_task(_loop(app, float(ctx.osettings.OPS_TICK_SECONDS), tick)))
    return run
