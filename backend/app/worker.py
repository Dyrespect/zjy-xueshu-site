"""独立任务进程：在 backend/ 下 `python -m app.worker`（设计 docs/任务单/07_底座可扩展_设计.md 第六节）。

跑什么：各模块在 lifespan 里向调度器登记的定时任务（接单机器人、交接工厂、出水印图、时限看门、3 天自动确认、
关过期付款单、发票推进……）和 core_tasks 队列里的任务。跟网站进程是同一份代码、同一个库。

- 网站进程设 BACKGROUND_IN_WEB=false 就不再跑这些，全交给 worker；多开几个 worker 也不重复（租约锁 + 抢占领任务）。
- SIGTERM / Ctrl-C：不再领新的，等手上那件做完（最多 WORKER_GRACE_SEC 秒），放掉租约再退。再按一次立刻退。
- 每 5 分钟（全集群一个）往日志打一行任务指标（JSON），运维采。
- `--once`：只跑一圈就退（运维排查、测试用）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.tasks import metrics
from app.main import create_app

log = logging.getLogger("app.worker")


async def run_worker(app: FastAPI, *, once: bool = False) -> None:
    sched = app.state.scheduler
    settings = app.state.settings
    database = app.state.db
    sched.every("core.metrics_log", 300, lambda: log.info("任务指标 %s", json.dumps(metrics(database), ensure_ascii=False)),
                initial_delay=60)
    async with app.router.lifespan_context(app):  # 各模块的 lifespan：建运行时、登记定时任务
        if once:
            await sched.run_once()
            return
        loop = asyncio.get_running_loop()
        task = asyncio.create_task(sched.run_forever())
        hits = {"n": 0}

        def _on_signal() -> None:
            hits["n"] += 1
            if hits["n"] == 1:
                log.info("收到退出信号：不再领新任务，等手上的做完（最多 %s 秒）", settings.WORKER_GRACE_SEC)
                sched.stop()
                loop.call_later(settings.WORKER_GRACE_SEC, task.cancel)
            else:
                task.cancel()

        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, _on_signal)
            except (NotImplementedError, RuntimeError):  # pragma: no cover - 不是主线程（测试里）
                pass
        try:
            await task
        except asyncio.CancelledError:
            log.warning("worker 被强制停下（手上的任务租约到期后会被别的 worker 接手）")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="学术汇报平台后台任务进程")
    ap.add_argument("--once", action="store_true", help="只跑一圈就退")
    args = ap.parse_args(argv)
    settings = get_settings()
    app = create_app(settings, role="worker")
    log.info("worker 启动：%s（库 %s）", app.state.scheduler.holder, app.state.db.dialect)
    asyncio.run(run_worker(app, once=args.once))


if __name__ == "__main__":
    main()
