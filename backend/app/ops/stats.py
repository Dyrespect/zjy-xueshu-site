"""查询：请求量、错误率、耗时分位数（由分桶算）、页面访问、漏斗、外部服务成功率、支付、仪表最新读数。

- 时间窗用 UTC 存、按北京时间切「今天」「昨天」（OPS_TIMEZONE）。已经按小时合过的读小时表 ops_hourly，最近还没合的读原始表 ops_samples。
- 分位数：每个请求的耗时落进一个桶（BUCKETS_MS），分位数在桶里线性插值，误差不超过一个桶宽；够看「慢没慢」。
- 业务数（下单、付款、认领……）只从 events 表数，口径写在设置的 funnel / externals 里（数据，不写死）。
- 健康检查的路由（/health、/api/health）和静态文件不算进请求量和耗时（外部拨测会刷高）。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.events import Event

BUCKETS_MS: tuple[float, ...] = (10, 25, 50, 100, 200, 400, 800, 1600, 3200, 6400)  # 最后一个桶是 >6400
EXCLUDED_ROUTES = ("/health", "/api/health", "/assets/{file}")
STAFF_PREFIXES = ("/api/admin", "/api/auth", "/api/ops")  # 只有 Edison 用的：「慢接口」里不列


def new_hist() -> list[int]:
    return [0] * (len(BUCKETS_MS) + 1)


def bucket_index(ms: float) -> int:
    for i, edge in enumerate(BUCKETS_MS):
        if ms <= edge:
            return i
    return len(BUCKETS_MS)


def merge_hist(a: list[int] | None, b: list[int] | None) -> list[int]:
    a, b = list(a or new_hist()), list(b or new_hist())
    n = max(len(a), len(b))
    a += [0] * (n - len(a))
    b += [0] * (n - len(b))
    return [x + y for x, y in zip(a, b)]


def percentile(hist: list[int], q: float) -> float | None:
    """分桶直方图的分位数（毫秒），q 取 0–1。没有数据返回 None。"""
    total = sum(hist)
    if total == 0:
        return None
    target = q * total
    seen = 0
    for i, c in enumerate(hist):
        if c and seen + c >= target:
            lo = 0.0 if i == 0 else BUCKETS_MS[i - 1]
            hi = BUCKETS_MS[i] if i < len(BUCKETS_MS) else BUCKETS_MS[-1] * 2
            frac = (target - seen) / c
            return round(lo + (hi - lo) * frac, 1)
        seen += c
    return float(BUCKETS_MS[-1] * 2)


# ---------------------------------------------------------------- 时间窗

def tz(name: str) -> ZoneInfo:
    return ZoneInfo(name)


def local_day_bounds(day: date, tzname: str) -> tuple[datetime, datetime]:
    z = ZoneInfo(tzname)
    start = datetime.combine(day, time(0), z).astimezone(timezone.utc)
    return start, start + timedelta(days=1)


def today_start(now: datetime, tzname: str) -> datetime:
    return local_day_bounds(now.astimezone(ZoneInfo(tzname)).date(), tzname)[0]


def windows(now: datetime, tzname: str) -> dict[str, tuple[datetime, datetime]]:
    """今天（北京时间 0 点到现在）和近 7 天（往前 7×24 小时）。"""
    return {"today": (today_start(now, tzname), now), "week": (now - timedelta(days=7), now)}


# ---------------------------------------------------------------- 请求

def _rows(db: Session, kind: str, start: datetime, end: datetime) -> list[Any]:
    """[(key, dim, n, total, max, hist, 时间)]：已经按小时合过的部分读小时表（行少，7 天、30 天也快），后面没合的读原始表。
    小时表的粒度是整小时：窗口起点不在整点时，起点所在那一小时整个算进来（近 7 天前后差不到 1 小时）。"""
    from app.ops.models import OpsHourly, OpsSample

    last_h = db.scalar(select(func.max(OpsHourly.hour)).where(OpsHourly.kind == kind))
    raw_from = start if last_h is None else max(start, min(end, last_h + timedelta(hours=1)))
    out: list[Any] = []
    if start < raw_from:
        out += db.execute(select(OpsHourly.key, OpsHourly.dim, OpsHourly.n, OpsHourly.total, OpsHourly.max, OpsHourly.hist, OpsHourly.hour)
                          .where(OpsHourly.kind == kind, OpsHourly.hour >= start.replace(minute=0, second=0, microsecond=0),
                                 OpsHourly.hour < raw_from)).all()
    out += db.execute(select(OpsSample.key, OpsSample.dim, OpsSample.n, OpsSample.total, OpsSample.max, OpsSample.hist, OpsSample.minute)
                      .where(OpsSample.kind == kind, OpsSample.minute >= raw_from, OpsSample.minute < end)).all()
    return out


def http_summary(db: Session, start: datetime, end: datetime) -> dict[str, Any]:
    n = e5 = e4 = 0
    total_ms = 0.0
    hist = new_hist()
    for key, dim, cnt, tot, _mx, h, _at in _rows(db, "http", start, end):
        if key in EXCLUDED_ROUTES:
            continue
        n += cnt
        total_ms += tot
        hist = merge_hist(hist, h)
        if dim.endswith("5xx"):
            e5 += cnt
        elif dim.endswith("4xx"):
            e4 += cnt
    return {"requests": n, "errors_5xx": e5, "errors_4xx": e4, "ratio_5xx": round(e5 / n, 4) if n else None,
            "avg_ms": round(total_ms / n, 1) if n else None, "p50_ms": percentile(hist, 0.5), "p95_ms": percentile(hist, 0.95),
            "p99_ms": percentile(hist, 0.99)}


def route_table(db: Session, start: datetime, end: datetime, *, limit: int = 10, min_n: int = 1,
                exclude_prefixes: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    """按路由分组：次数、5xx、p50/p95、最慢；按 p95 从慢到快。exclude_prefixes：不列的前缀（比如后台 /api/admin）。"""
    agg: dict[tuple[str, str], dict[str, Any]] = {}
    for key, dim, cnt, tot, mx, h, _at in _rows(db, "http", start, end):
        if key in EXCLUDED_ROUTES or (exclude_prefixes and key.startswith(exclude_prefixes)):
            continue
        method = dim.split(" ")[0]
        a = agg.setdefault((method, key), {"route": key, "method": method, "n": 0, "errors_5xx": 0, "max_ms": 0.0, "total": 0.0,
                                           "hist": new_hist()})
        a["n"] += cnt
        a["total"] += tot
        a["max_ms"] = max(a["max_ms"], mx)
        a["hist"] = merge_hist(a["hist"], h)
        if dim.endswith("5xx"):
            a["errors_5xx"] += cnt
    rows = []
    for a in agg.values():
        if a["n"] < min_n:
            continue
        rows.append({"route": a["route"], "method": a["method"], "n": a["n"], "errors_5xx": a["errors_5xx"],
                     "avg_ms": round(a["total"] / a["n"], 1), "p50_ms": percentile(a["hist"], 0.5),
                     "p95_ms": percentile(a["hist"], 0.95), "max_ms": round(a["max_ms"], 1)})
    rows.sort(key=lambda r: (r["p95_ms"] or 0, r["max_ms"]), reverse=True)
    return rows[:limit]


def window_5xx(db: Session, start: datetime, end: datetime) -> tuple[int, int]:
    """（5xx 次数，全部次数），给告警用。"""
    s = http_summary(db, start, end)
    return s["errors_5xx"], s["requests"]


# ---------------------------------------------------------------- 页面访问

def pages(db: Session, start: datetime, end: datetime) -> dict[str, Any]:
    pv: dict[str, int] = defaultdict(int)
    uv = 0
    for key, dim, cnt, _tot, _mx, _h, _at in _rows(db, "page", start, end):
        if key == "_uv":
            uv += cnt
        elif dim == "pv":
            pv[key] += cnt
    return {"pv": sum(pv.values()), "uv": uv, "by_page": dict(sorted(pv.items(), key=lambda x: -x[1]))}


# ---------------------------------------------------------------- 事件（业务数）

def count_events(db: Session, type_: str, start: datetime, end: datetime, *, where: dict[str, Any] | None = None) -> int:
    stmt = select(Event.content) if where else select(func.count()).select_from(Event)
    stmt = stmt.where(Event.type == type_, Event.created_at >= start, Event.created_at < end)
    if not where:
        return int(db.scalar(stmt) or 0)
    n = 0
    for (c,) in db.execute(stmt):
        c = c or {}
        if all((c.get(k) in v) if isinstance(v, (list, tuple, set)) else c.get(k) == v for k, v in where.items()):
            n += 1
    return n


def funnel(db: Session, start: datetime, end: datetime, steps: list[Any]) -> list[dict[str, Any]]:
    out = []
    page = None
    for st in steps:
        if st.source == "page.uv":
            page = page or pages(db, start, end)
            n = page["uv"]
        elif st.source.startswith("event:"):
            n = count_events(db, st.source[6:], start, end)
        else:
            n = None
        out.append({"key": st.key, "label": st.label, "count": n})
    return out


def externals(db: Session, start: datetime, end: datetime, specs: list[Any]) -> list[dict[str, Any]]:
    out = []
    for sp in specs:
        ok, fail = count_events(db, sp.ok, start, end), count_events(db, sp.fail, start, end)
        out.append({"key": sp.key, "label": sp.label, "ok": ok, "fail": fail,
                    "rate": round(ok / (ok + fail), 4) if ok + fail else None})
    return out


def payments(db: Session, start: datetime, end: datetime) -> dict[str, Any]:
    created = count_events(db, "shop.checkout_created", start, end)
    paid = count_events(db, "shop.pay_notified", start, end)
    invalid = count_events(db, "shop.pay_invalid", start, end)
    by_query = count_events(db, "shop.pay_notified", start, end, where={"via": "query"})
    return {"checkouts": created, "paid": paid, "success_rate": round(min(paid, created) / created, 4) if created else None,
            "callback_invalid": invalid, "paid_by_query": by_query}


def capacity_from_events(db: Session, start: datetime, end: datetime) -> dict[str, Any]:
    started = count_events(db, "intake.stage", start, end, where={"to": "making"})
    return {"started": started}


# ---------------------------------------------------------------- 仪表

def latest_gauges(db: Session, *, within: timedelta = timedelta(minutes=30), now: datetime | None = None) -> dict[str, dict[str, Any]]:
    """每个仪表最近一次读数：{key: {value, at}}（key = 仪表名，子项拼在后面）。"""
    from app.ops.models import OpsSample

    now = now or datetime.now(timezone.utc)
    rows = db.execute(select(OpsSample.key, OpsSample.dim, OpsSample.total, OpsSample.n, OpsSample.minute)
                      .where(OpsSample.kind == "gauge", OpsSample.minute >= now - within)
                      .order_by(OpsSample.minute)).all()
    out: dict[str, dict[str, Any]] = {}
    for key, dim, tot, n, at in rows:
        k = f"{key}.{dim}" if dim else key
        out[k] = {"value": round(tot / n, 2) if n else None, "at": at}
    return out


def heartbeat_minutes(db: Session, start: datetime, end: datetime) -> int:
    from app.ops.models import OpsHourly, OpsSample

    raw = db.scalar(select(func.count(func.distinct(OpsSample.minute))).where(
        OpsSample.kind == "gauge", OpsSample.key == "heartbeat", OpsSample.minute >= start, OpsSample.minute < end)) or 0
    if raw:
        return int(raw)
    # 原始已经清掉的时间段：小时表里 n 是那一小时的心跳次数
    return int(db.scalar(select(func.coalesce(func.sum(OpsHourly.n), 0)).where(
        OpsHourly.kind == "gauge", OpsHourly.key == "heartbeat", OpsHourly.hour >= start, OpsHourly.hour < end)) or 0)


def availability(db: Session, start: datetime, end: datetime) -> dict[str, Any]:
    """有心跳的分钟 / 总分钟。网站第一次起来之前的时间不算（新部署第一天不会显示成「只在线 40%」）。"""
    from app.ops.config import kv_get

    first = kv_get(db, "started").get("first_at")
    if first:
        start = max(start, min(end, datetime.fromisoformat(first).replace(second=0, microsecond=0)))
    minutes = max(1, int((end - start).total_seconds() // 60))
    beats = min(minutes, heartbeat_minutes(db, start, end))
    return {"minutes": minutes, "alive_minutes": beats, "ratio": round(beats / minutes, 4)}
