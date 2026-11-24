"""交付这一块的后台圈（delivery/router.py 的 lifespan 登记到底座调度器 core.tasks，全集群同一时刻一个在跑）：出水印图的队列、时限看门。

- 出图：版本表里 status=rendering 且到了重试时间的，一版一版出。读底图、写水印图各开一个很短的库会话，
  中间算图放到线程里（34 页十几秒到半分钟），不占 SQLite 唯一的写入口，不卡机器人回消息。出完发 proof_ready → 发布。
- 时限看门：每圈对在做第一版的单跑一次 deliver.sla（每种提醒只发一次）。
- 3 天自动确认的计时器归模块 B（trigger.confirm_timeout），不在这里。
进程重启不丢：队列就是版本表的状态。
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.nodes import NodeCall, run_node
from app.core.tasks import Scheduler, register_gauge
from app.delivery import release, sla, versions
from app.delivery.models import DeliveryVersion
from app.delivery.settings import DeliverySettings
from app.intake import flow
from app.intake.models import Order
from app.intake.runtime import IntakeRuntime

log = logging.getLogger("app.delivery.tick")


async def render_due(rt: IntakeRuntime, s: DeliverySettings, *, limit: int = 3) -> int:
    """出到期的几版。返回出完并发布了几版。"""
    with rt.database.session(write=False) as db:  # 只是看有哪些要出：读会话，不占写锁
        ids = [v.id for v in versions.due_versions(db)][:limit]
    done = 0
    for vid in ids:
        try:
            with rt.database.session() as db:
                v = db.get(DeliveryVersion, vid)
                if v is None or v.status != "rendering":
                    continue
                job = versions.load_job(db, rt.ctx, v, s)
        except Exception as e:  # noqa: BLE001 - 读不出底图也算这一次失败
            with rt.database.session() as db:
                versions.mark_render_failed(db, rt.ctx, vid, f"{type(e).__name__}: {e}", s)
            continue
        try:
            results = await asyncio.to_thread(versions.render_job, job)
        except Exception as e:  # noqa: BLE001
            log.exception("第 %s 版出图失败", vid)
            with rt.database.session() as db:
                versions.mark_render_failed(db, rt.ctx, vid, f"{type(e).__name__}: {e}", s)
            continue
        with rt.database.session() as db:
            v = versions.save_proofs(db, rt.ctx, job, results, by="delivery")
            if v is not None:
                o = db.get(Order, v.order_id)
                flow.emit(db, rt.ctx, o, "proof_ready", by="delivery", why=f"第 {v.round} 版水印图出好了")
                done += 1
    return done


def sla_tick(rt: IntakeRuntime) -> list[str]:
    out = []
    with rt.database.session() as db:
        for oid in sla.watching(db):
            res = run_node("deliver.sla", NodeCall(db, rt.ctx, "delivery", oid), {"order_id": oid})
            out.append(res.exit)
    return out


def release_due(rt: IntakeRuntime) -> int:
    """压着的水印版（不加急的单第一版，release.py）到点了：再推一次「发布」。返回发了几单。"""
    with rt.database.session(write=False) as db:
        due = release.due(db)
    n = 0
    for oid, _vid in due:
        with rt.database.session() as db:
            o = db.get(Order, oid)
            if o is not None and o.flow_step == "publish" and flow.emit(db, rt.ctx, o, "proof_ready", by="delivery",
                                                                       why="不加急的单到了最早可发时间，自动发水印版"):
                n += 1
    return n


async def tick_once(rt: IntakeRuntime, s: DeliverySettings) -> None:
    await render_due(rt, s)
    release_due(rt)
    sla_tick(rt)


def _render_gauge(db: Session) -> dict[str, int]:
    return {"rendering": db.scalar(select(func.count()).select_from(DeliveryVersion).where(DeliveryVersion.status == "rendering")) or 0}


def register(sched: Scheduler, rt: IntakeRuntime, s: DeliverySettings) -> None:
    """出图和时限看门是扫库（版本表、订单表）的活：singleton，全集群同一时刻一个在跑，同一版不会出两遍。
    出图一版十几秒到半分钟，一个 worker 一小时能出一百多版，远多于做单产能（一周 40–90 单），不用并行。"""
    sched.every("delivery.tick", s.DELIVERY_TICK_SECONDS, lambda: tick_once(rt, s), initial_delay=s.DELIVERY_TICK_DELAY)
    register_gauge("delivery.render_queue", _render_gauge)
