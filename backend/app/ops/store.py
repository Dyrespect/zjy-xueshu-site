"""计数落库、小时聚合（ops.metrics_flush / ops.metrics_rollup 背后的实现）。清理在 retention.py。

只用 SQLAlchemy 的写法（不写只有 SQLite 认的 upsert），以后换 PostgreSQL 不用改：先查有没有这一格，有就加，没有就插。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ops import sources
from app.ops.collector import Collector, Slot
from app.ops.models import OpsError, OpsHourly, OpsSample, OpsVisitor
from app.ops.stats import merge_hist

GAUGE_EVERY_MINUTES = 5  # 仪表（水印队列、做单产能、磁盘）每 5 分钟读一次


def _upsert(db: Session, model: Any, slot_col: str, at: datetime, kind: str, key: str, dim: str, s: Slot | dict[str, Any]) -> None:
    n, total, mx, hist = (s.n, s.total, s.max, s.hist) if isinstance(s, Slot) else (s["n"], s["total"], s["max"], s["hist"])
    row = db.scalar(select(model).where(getattr(model, slot_col) == at, model.kind == kind, model.key == key, model.dim == dim))
    if row is None:
        db.add(model(**{slot_col: at}, kind=kind, key=key, dim=dim, n=n, total=total, max=mx, hist=list(hist)))
    else:
        row.n += n
        row.total += total
        row.max = max(row.max, mx)
        row.hist = merge_hist(row.hist, hist)


def flush(db: Session, collector: Collector, *, now: datetime, gauge_args: tuple[Any, ...] | None = None) -> dict[str, int]:
    """把计数器里这一分钟多出来的数写进 ops_samples，错误进 ops_errors，访客去重后把「新访客数」记成 page/_uv。调用方提交。"""
    slots, errors, visitors = collector.drain(now=now)
    try:
        for (minute, kind, key, dim), s in slots.items():
            _upsert(db, OpsSample, "minute", minute, kind, key, dim, s)
        for e in errors:
            db.add(OpsError(**e))
        new_by_minute = 0
        seen: set[tuple[str, str]] = set()
        for day, vh, page in visitors:
            if (day, vh) in seen:
                continue
            seen.add((day, vh))
            if db.scalar(select(OpsVisitor.id).where(OpsVisitor.day == day, OpsVisitor.vh == vh)) is None:
                db.add(OpsVisitor(day=day, vh=vh, page=page[:24]))
                new_by_minute += 1
        minute = now.replace(second=0, microsecond=0)
        if new_by_minute:
            _upsert(db, OpsSample, "minute", minute, "page", "_uv", "new", {"n": new_by_minute, "total": float(new_by_minute),
                                                                          "max": float(new_by_minute), "hist": []})
        # 心跳：这一分钟进程活着（可用性 = 有心跳的分钟 / 总分钟）
        _upsert(db, OpsSample, "minute", minute, "gauge", "heartbeat", "", {"n": 1, "total": 1.0, "max": 1.0, "hist": []})
        gauges = 0
        if gauge_args is not None and minute.minute % GAUGE_EVERY_MINUTES == 0:
            for g in sources.collect("gauge", *gauge_args)[0]:
                if g.value is None:
                    continue
                collector.set_gauge(g.key, float(g.value))
                key, _, dim = g.key.partition(".")
                _upsert(db, OpsSample, "minute", minute, "gauge", key, dim, {"n": 1, "total": float(g.value),
                                                                              "max": float(g.value), "hist": []})
                gauges += 1
        db.flush()
    except IntegrityError:
        db.rollback()
        collector.put_back(slots)
        raise
    return {"samples": len(slots), "errors": len(errors), "visitors_new": new_by_minute, "gauges": gauges}


def rollup(db: Session, *, now: datetime) -> dict[str, int]:
    """把整点以前、还没聚合的原始行按小时合进 ops_hourly。已经聚合过的小时会重算覆盖（幂等）。调用方提交。"""
    upto = now.replace(minute=0, second=0, microsecond=0)
    last = db.scalar(select(OpsHourly.hour).order_by(OpsHourly.hour.desc()).limit(1))
    start = (last if last is not None else (db.scalar(select(OpsSample.minute).order_by(OpsSample.minute).limit(1)) or upto))
    start = start.replace(minute=0, second=0, microsecond=0)
    hours = rows = 0
    h = start
    while h < upto:
        nxt = h + timedelta(hours=1)
        agg: dict[tuple[str, str, str], dict[str, Any]] = {}
        for s in db.scalars(select(OpsSample).where(OpsSample.minute >= h, OpsSample.minute < nxt)):
            a = agg.setdefault((s.kind, s.key, s.dim), {"n": 0, "total": 0.0, "max": 0.0, "hist": []})
            a["n"] += s.n
            a["total"] += s.total
            a["max"] = max(a["max"], s.max)
            a["hist"] = merge_hist(a["hist"], s.hist) if (a["hist"] or s.hist) else []
        if agg:
            for old in db.scalars(select(OpsHourly).where(OpsHourly.hour == h)):
                db.delete(old)
            db.flush()
            for (kind, key, dim), a in agg.items():
                db.add(OpsHourly(hour=h, kind=kind, key=key, dim=dim, n=a["n"], total=a["total"], max=a["max"], hist=a["hist"]))
                rows += 1
            hours += 1
        h = nxt
    db.flush()
    return {"hours": hours, "rows": rows}


def utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
