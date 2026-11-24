"""深健康检查（ops.health_check 背后的实现）：一项一行，状态 ok / warn / problem / skipped（没配）/ off（关了）。

- 数据库可写：往 ops_kv 写一行心跳并提交，记耗时；顺便报库文件和 WAL 多大。
- 水印队列、做单产能：业务读数从接口位（sources 的 gauge）来。
- 磁盘：DATA_DIR 所在盘的使用率（阈值取告警规则 disk_usage 的设置）。
- 证书：连 OPS_CERT_HOSTS（空 = PUBLIC_BASE_URL 的域名，https 才查）的 443 读证书到期日；连不上写「查不到」，不算有问题。
- 备份：最近一次 ops.backup_done / ops.backup_failed 事件。
- 外部依赖：接口位 external 给的目标 + 飞书；没配的跳过；超时 OPS_EXTERNAL_TIMEOUT 秒；OPS_EXTERNAL_CHECKS=false 时全部「已关」。
  只看「连不连得上」（HEAD 那个地址，收到任何 HTTP 回应都算通），不带密钥。
"""

from __future__ import annotations

import shutil
import socket
import ssl
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.events import Event
from app.ops import sources
from app.ops.config import OpsConfig, kv_set
from app.ops.models_io import HealthItem, HealthOut
from app.ops.runtime import OpsCtx
from app.ops.sender import build_sender, read_webhook


def cert_days_left(host: str, timeout: float) -> int:
    ctx = ssl.create_default_context()
    with socket.create_connection((host, 443), timeout=timeout) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as s:
            cert = s.getpeercert()
    not_after = ssl.cert_time_to_seconds(cert["notAfter"])  # type: ignore[index]
    return int((not_after - time.time()) // 86400)


def cert_hosts(ctx: OpsCtx) -> list[str]:
    if ctx.osettings.OPS_CERT_HOSTS.strip():
        return [h.strip() for h in ctx.osettings.OPS_CERT_HOSTS.split(",") if h.strip()]
    u = urlparse(ctx.settings.PUBLIC_BASE_URL)
    return [u.hostname] if u.scheme == "https" and u.hostname else []


def _db_item(db: Session, ctx: OpsCtx) -> list[HealthItem]:
    items = []
    t0 = time.perf_counter()
    try:
        kv_set(db, "heartbeat_write", {"at": ctx.now().isoformat()})
        db.commit()
        ms = (time.perf_counter() - t0) * 1000
        items.append(HealthItem(key="db_write", label="数据库可写", status="ok" if ms < 1000 else "warn",
                                detail=f"写一行用了 {ms:.0f} 毫秒", value=round(ms, 1)))
    except Exception as e:  # noqa: BLE001
        db.rollback()
        items.append(HealthItem(key="db_write", label="数据库可写", status="problem", detail=f"写不进去：{type(e).__name__}"))
    url = ctx.settings.DATABASE_URL
    if url.startswith("sqlite:///"):
        p = Path(url.removeprefix("sqlite:///"))
        size = p.stat().st_size if p.exists() else 0
        wal = Path(str(p) + "-wal")
        wsize = wal.stat().st_size if wal.exists() else 0
        items.append(HealthItem(key="db_size", label="数据库大小", status="ok",
                                detail=f"库 {size / 1e6:.1f} MB，WAL {wsize / 1e6:.1f} MB", value=round(size / 1e6, 1)))
    return items


def _gauge_items(db: Session, ctx: OpsCtx, cfg: OpsConfig) -> list[HealthItem]:
    p = cfg.rule("watermark_backlog")["params"]
    gauges, errors = sources.collect("gauge", db, ctx.app)
    items = []
    by = {g.key: g for g in gauges}
    q, wait, failed = by.get("watermark.rendering"), by.get("watermark.oldest_wait_min"), by.get("watermark.failed_24h")
    if q is not None:
        status = "ok"
        if (q.value or 0) >= p["max_queue"] or ((q.value or 0) > 0 and wait is not None and (wait.value or 0) >= p["max_wait_minutes"]):
            status = "problem"
        elif failed is not None and (failed.value or 0) > 0:
            status = "warn"
        detail = f"在排 {int(q.value or 0)} 版"
        if wait is not None and wait.value:
            detail += f"，最老的等了 {wait.value:.0f} 分钟"
        if failed is not None and failed.value:
            detail += f"；24 小时内出图失败 {int(failed.value)} 版"
        items.append(HealthItem(key="watermark", label="水印出图队列", status=status, detail=detail, value=q.value))
    making, waiting = by.get("capacity.making"), by.get("capacity.waiting")
    if making is not None:
        items.append(HealthItem(key="capacity", label="做单", status="ok",
                                detail=f"在做 {int(making.value or 0)} 单，等开工 {int((waiting.value if waiting else 0) or 0)} 单",
                                value=making.value))
    for e in errors:
        items.append(HealthItem(key="sources", label="业务读数", status="warn", detail=e))
    return items


def _disk_item(ctx: OpsCtx, cfg: OpsConfig) -> HealthItem:
    p = cfg.rule("disk_usage")["params"]
    try:
        u = (ctx.disk_probe or shutil.disk_usage)(ctx.settings.DATA_DIR)
    except OSError as e:
        return HealthItem(key="disk", label="磁盘", status="warn", detail=f"读不到：{type(e).__name__}")
    pct = round(u.used / u.total * 100, 1)
    status = "problem" if pct >= p["urgent_pct"] else "warn" if pct >= p["warn_pct"] else "ok"
    return HealthItem(key="disk", label="磁盘", status=status, value=pct,
                      detail=f"用了 {pct}%，还剩 {u.free / 1e9:.1f} GB（共 {u.total / 1e9:.0f} GB）")


def _cert_items(ctx: OpsCtx, cfg: OpsConfig) -> list[HealthItem]:
    hosts = cert_hosts(ctx)
    if not hosts:
        return [HealthItem(key="cert", label="网站证书", status="skipped", detail="网址不是 https（本机开发），不查")]
    p = cfg.rule("cert_expiring")["params"]
    probe = ctx.cert_probe or cert_days_left
    out = []
    for h in hosts:
        try:
            days = probe(h, ctx.osettings.OPS_EXTERNAL_TIMEOUT)
        except Exception as e:  # noqa: BLE001  容器里连不出去也不误报
            out.append(HealthItem(key=f"cert:{h}", label=f"证书 {h}", status="warn", detail=f"查不到：{type(e).__name__}"))
            continue
        status = "problem" if days < p["urgent_days"] else "warn" if days < p["warn_days"] else "ok"
        out.append(HealthItem(key=f"cert:{h}", label=f"证书 {h}", status=status, value=days, detail=f"还有 {days} 天到期"))
    return out


def backup_state(db: Session) -> dict[str, Any]:
    done = db.scalar(select(Event).where(Event.type == "ops.backup_done").order_by(Event.id.desc()).limit(1))
    failed = db.scalar(select(Event).where(Event.type == "ops.backup_failed").order_by(Event.id.desc()).limit(1))
    return {"done_at": done.created_at if done else None, "done": (done.content or {}) if done else {},
            "failed_at": failed.created_at if failed else None, "failed": (failed.content or {}) if failed else {}}


def _backup_item(db: Session, ctx: OpsCtx, cfg: OpsConfig) -> HealthItem:
    st = backup_state(db)
    max_age = cfg.rule("backup_failed")["params"]["max_age_hours"]
    now = ctx.now()
    if not cfg.backup.enabled:
        return HealthItem(key="backup", label="备份", status="off", detail="本机备份关着（设置里开）")
    if st["done_at"] is None:
        return HealthItem(key="backup", label="备份", status="warn" if st["failed_at"] is None else "problem",
                          detail="还没备份过" + ("，最近一次失败了" if st["failed_at"] else ""))
    hours = (now - st["done_at"]).total_seconds() / 3600
    failed_later = st["failed_at"] is not None and st["failed_at"] > st["done_at"]
    status = "problem" if failed_later or hours > max_age else "ok"
    detail = f"最近一次成功是 {hours:.0f} 小时前（{st['done'].get('name', '')}）"
    if failed_later:
        detail += f"；之后失败了：{str(st['failed'].get('error', ''))[:80]}"
    return HealthItem(key="backup", label="备份", status=status, detail=detail, value=round(hours, 1))


def _litestream_item(ctx: OpsCtx) -> HealthItem | None:
    """装了 Litestream（数据库连续备份）才查：它的指标地址通不通、有没有它的数。"""
    url = ctx.osettings.OPS_LITESTREAM_METRICS_URL
    if not url:
        return None
    try:
        with httpx.Client(timeout=ctx.osettings.OPS_EXTERNAL_TIMEOUT, transport=ctx.transport) as c:
            r = c.get(url)
        ok = r.status_code == 200 and "litestream_" in r.text
        return HealthItem(key="litestream", label="数据库连续备份（Litestream）", status="ok" if ok else "problem",
                          detail="在跑" if ok else f"指标地址回 HTTP {r.status_code}，没有 litestream 的数")
    except Exception as e:  # noqa: BLE001
        return HealthItem(key="litestream", label="数据库连续备份（Litestream）", status="problem", detail=f"连不上：{type(e).__name__}")


def _probe(url: str, timeout: float, transport: httpx.BaseTransport | None) -> tuple[bool, str]:
    try:
        with httpx.Client(timeout=timeout, transport=transport, follow_redirects=False) as c:
            r = c.head(url)
        return True, f"通（HTTP {r.status_code}）"
    except Exception as e:  # noqa: BLE001
        return False, f"连不上：{type(e).__name__}"


def external_targets(ctx: OpsCtx) -> list[sources.ExternalTarget]:
    targets, _errors = sources.collect("external", ctx.app)
    url, _secret, _src = read_webhook(ctx.osettings)
    sender = build_sender(ctx.osettings, ctx.notifier)
    targets.append(sources.ExternalTarget(key="feishu", label="飞书机器人", url="https://open.feishu.cn",
                                          configured=bool(url) or sender.name in ("core_notifier", "feishu_app")))
    return targets


def _external_items(ctx: OpsCtx) -> list[HealthItem]:
    targets = external_targets(ctx)
    if not ctx.osettings.OPS_EXTERNAL_CHECKS:
        return [HealthItem(key=f"ext:{t.key}", label=t.label, status="off", detail="外部检查关着（OPS_EXTERNAL_CHECKS=false）")
                for t in targets]
    todo = [t for t in targets if t.configured]
    out = [HealthItem(key=f"ext:{t.key}", label=t.label, status="skipped", detail=t.note or "没配，跳过") for t in targets
           if not t.configured]
    if todo:
        with ThreadPoolExecutor(max_workers=min(6, len(todo))) as ex:
            res = list(ex.map(lambda t: _probe(t.url, ctx.osettings.OPS_EXTERNAL_TIMEOUT, ctx.transport), todo))
        for t, (ok, detail) in zip(todo, res):
            out.append(HealthItem(key=f"ext:{t.key}", label=t.label, status="ok" if ok else "problem", detail=detail))
    return out


def run(db: Session, ctx: OpsCtx, cfg: OpsConfig, *, external: bool, use_cache: bool = True) -> HealthOut:
    cache_key = f"health:{int(external)}"
    hit = ctx.cache.get(cache_key)
    now = ctx.now()
    if use_cache and hit and (now - hit.checked_at).total_seconds() < ctx.osettings.OPS_HEALTH_CACHE_SECONDS:
        return hit
    items: list[HealthItem] = []
    items += _db_item(db, ctx)
    items += _gauge_items(db, ctx, cfg)
    items.append(_disk_item(ctx, cfg))
    items += _cert_items(ctx, cfg)
    items.append(_backup_item(db, ctx, cfg))
    ls = _litestream_item(ctx)
    if ls is not None:
        items.append(ls)
    if external:
        items += _external_items(ctx)
    out = HealthOut(ok=not any(i.status == "problem" for i in items), checked_at=now, items=items)
    ctx.cache[cache_key] = out
    return out


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
