"""告警（ops.alert_eval 背后的实现）：按 alerts.json 的规则算一遍 → 开、续、关告警 → 去重和静默后交给推送节点。

- 每条规则一个同名函数，返回若干 Finding（这一项现在是不是在报警、大白话说明、影响什么）。规则的阈值从设置读（cfg.rule(id)）。
- 去重：同一个 key 只有一条开着的告警；开着期间再触发只加次数，不重复推。
- 静默：推过之后 push.silence_minutes[级别] 分钟内不再推同一条；过了还没好，再推一次「还没好」。级别升高（今天看 → 立刻）马上推。
- 防刷屏：每小时最多推 push.max_per_hour 条，多的只记录，下一条推送末尾说「还有 N 条没推，去后台看」。
- 恢复：条件不成立了就关掉；「要立刻处理」的、推过的，恢复时说一声（push.notify_resolved）。
- info 级别只记录，不推。规则在设置里关掉的不算；push=false 的照样记录、后台能看，只是不推。
成熟替代（Prometheus Alertmanager）要装 Prometheus 才能用，现在的规模先用这几十行；见设计文档第三节。
"""

from __future__ import annotations

from collections import Counter as _Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.events import record_event
from app.core.nodes import NodeCall, run_node
from app.ops import sources, stats
from app.ops.config import LEVEL_LABELS, OpsConfig, kv_get, kv_set
from app.ops.health import backup_state
from app.ops.models import OpsAlert
from app.ops.models_io import AlertEvalOut, AlertMessage, HealthOut, MessageLine, MessageSection
from app.ops.runtime import OpsCtx

LEVEL_RANK = {"info": 0, "today": 1, "urgent": 2}
# 路由前缀 → 客人看到的是哪一页（告警里说「影响什么」）
ROUTE_PAGES: tuple[tuple[str, str], ...] = (
    ("/api/shop", "下单页、付款页"), ("/api/delivery", "交付页"), ("/api/channels/web", "网页聊天"), ("/api/channels/wecom", "微信客服"),
    ("/api/figures", "图库"), ("/api/invoices", "发票"), ("/api/platforms", "平台固定链接页"), ("/api/intake/production", "制作方接口"),
    ("/api/handoffs", "工厂领单"), ("/api/admin", "后台"), ("/api/auth", "后台登录"), ("/{full_path:path}", "网页本身（打不开页面）"),
)


def page_of(route: str) -> str:
    return next((label for prefix, label in ROUTE_PAGES if route.startswith(prefix)), "其他接口")


@dataclass
class Finding:
    key: str
    firing: bool
    detail: str = ""
    impact: str = ""
    level: str = ""  # 空 = 用规则的级别
    data: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------- 规则（函数名 = alerts.json 里的 id）

def http_5xx(db: Session, ctx: OpsCtx, rule: dict[str, Any], health: HealthOut | None, now: datetime) -> list[Finding]:
    p = rule["params"]
    start = now - timedelta(minutes=p["window_minutes"])
    e5, n = stats.window_5xx(db, start, now)
    firing = n > 0 and e5 >= p["min_errors"] and e5 / n >= p["ratio"]
    top = sorted((r for r in stats.route_table(db, start, now, limit=200) if r["errors_5xx"]), key=lambda r: -r["errors_5xx"])[:3]
    where = "；".join(f"{r['method']} {r['route']}（{page_of(r['route'])}）{r['errors_5xx']} 次" for r in top)
    pct = f"{e5 / n:.1%}" if n else "0%"
    return [Finding("http_5xx", firing, detail=f"近 {p['window_minutes']:.0f} 分钟 {n} 次请求里 {e5} 次出错（{pct}）",
                    impact=(rule["impact"] + (f"。出错最多的：{where}" if where else "")), data={"errors": e5, "requests": n})]


def db_unwritable(db: Session, ctx: OpsCtx, rule: dict[str, Any], health: HealthOut | None, now: datetime) -> list[Finding]:
    item = next((i for i in (health.items if health else []) if i.key == "db_write"), None)
    return [Finding("db_unwritable", bool(item and item.status == "problem"), detail=item.detail if item else "")]


def pay_notify_invalid(db: Session, ctx: OpsCtx, rule: dict[str, Any], health: HealthOut | None, now: datetime) -> list[Finding]:
    p = rule["params"]
    n = stats.count_events(db, "shop.pay_invalid", now - timedelta(minutes=p["window_minutes"]), now)
    return [Finding("pay_notify_invalid", n >= p["min_count"],
                    detail=f"近 {p['window_minutes']:.0f} 分钟收到 {n} 条验签不过或对不上的支付通知", data={"count": n})]


def pay_notify_silent(db: Session, ctx: OpsCtx, rule: dict[str, Any], health: HealthOut | None, now: datetime) -> list[Finding]:
    p = rule["params"]
    gauges, _ = sources.collect("gauge", db, ctx.app)
    g = next((x for x in gauges if x.key == "pay.notify_missing"), None)
    n = int(g.value or 0) if g else 0
    return [Finding("pay_notify_silent", n >= p["min_missing"],
                    detail=f"近 {p['window_hours']:.0f} 小时有 {n} 笔付款超过 {p['after_minutes']:.0f} 分钟还没收到网关的付款通知"
                           + (f"（{g.detail}）" if g and g.detail else ""), data={"missing": n})]


def watermark_backlog(db: Session, ctx: OpsCtx, rule: dict[str, Any], health: HealthOut | None, now: datetime) -> list[Finding]:
    p = rule["params"]
    gauges, _ = sources.collect("gauge", db, ctx.app)
    by = {g.key: g.value or 0 for g in gauges}
    if "watermark.rendering" not in by:
        return []
    q, wait, failed = by.get("watermark.rendering", 0), by.get("watermark.oldest_wait_min", 0), by.get("watermark.failed_24h", 0)
    firing = q >= p["max_queue"] or (q > 0 and wait >= p["max_wait_minutes"]) or failed > 0
    parts = [f"在排 {int(q)} 版"]
    if wait:
        parts.append(f"最老的等了 {wait:.0f} 分钟")
    if failed:
        parts.append(f"{p['failed_hours']:.0f} 小时内出图失败 {int(failed)} 版（重试用完了，要去后台点「重出图」）")
    return [Finding("watermark_backlog", firing, detail="，".join(parts), level="urgent" if failed or wait >= p["max_wait_minutes"] else "")]


def disk_usage(db: Session, ctx: OpsCtx, rule: dict[str, Any], health: HealthOut | None, now: datetime) -> list[Finding]:
    item = next((i for i in (health.items if health else []) if i.key == "disk"), None)
    if item is None or item.value is None:
        return []
    p = rule["params"]
    return [Finding("disk_usage", item.value >= p["warn_pct"], detail=item.detail,
                    level="urgent" if item.value >= p["urgent_pct"] else "")]


def backup_failed(db: Session, ctx: OpsCtx, rule: dict[str, Any], health: HealthOut | None, now: datetime) -> list[Finding]:
    cfg_backup_on = next((i for i in (health.items if health else []) if i.key == "backup"), None)
    if cfg_backup_on is not None and cfg_backup_on.status == "off":
        return [Finding("backup_failed", False)]
    p = rule["params"]
    st = backup_state(db)
    started = kv_get(db, "started").get("first_at")
    if st["done_at"] is None:
        old_enough = started and (now - datetime.fromisoformat(started)).total_seconds() > p["max_age_hours"] * 3600
        return [Finding("backup_failed", bool(st["failed_at"]) or bool(old_enough),
                        detail="还没成功备份过" + (f"；最近一次失败：{str(st['failed'].get('error', ''))[:120]}" if st["failed_at"] else ""))]
    hours = (now - st["done_at"]).total_seconds() / 3600
    failed_later = st["failed_at"] is not None and st["failed_at"] > st["done_at"]
    detail = f"最近一次成功是 {hours:.0f} 小时前"
    if failed_later:
        detail += f"；之后那次失败了：{str(st['failed'].get('error', ''))[:120]}"
    return [Finding("backup_failed", failed_later or hours > p["max_age_hours"], detail=detail)]


def cert_expiring(db: Session, ctx: OpsCtx, rule: dict[str, Any], health: HealthOut | None, now: datetime) -> list[Finding]:
    p = rule["params"]
    out = []
    for i in (health.items if health else []):
        if i.key.startswith("cert:") and i.value is not None:
            out.append(Finding(f"cert_expiring:{i.key[5:]}", i.value < p["warn_days"], detail=f"{i.label}：{i.detail}",
                               level="urgent" if i.value < p["urgent_days"] else ""))
    return out


def external_down(db: Session, ctx: OpsCtx, rule: dict[str, Any], health: HealthOut | None, now: datetime) -> list[Finding]:
    p = rule["params"]
    items = [i for i in (health.items if health else []) if i.key.startswith("ext:")]
    if not items:
        return []  # 这一轮没查外部（每 every_minutes 分钟查一次）：不动开着的告警
    fails = kv_get(db, "ext_fail")
    out = []
    for i in items:
        k = i.key[4:]
        fails[k] = fails.get(k, 0) + 1 if i.status == "problem" else 0
        if i.status in ("ok", "problem"):
            out.append(Finding(f"external_down:{k}", fails[k] >= p["fail_times"], detail=f"{i.label}：{i.detail}（连续 {fails[k]} 次）",
                               impact=f"用到{i.label}的功能会失败"))
    kv_set(db, "ext_fail", fails)
    return out


RULES = {f.__name__: f for f in (http_5xx, db_unwritable, pay_notify_invalid, pay_notify_silent, watermark_backlog, disk_usage,
                                 backup_failed, cert_expiring, external_down)}
HEALTH_RULES = ("db_unwritable", "disk_usage", "backup_failed", "cert_expiring", "external_down")


# ---------------------------------------------------------------- 消息

def fmt_local(dt: datetime, tzname: str) -> str:
    return dt.astimezone(ZoneInfo(tzname)).strftime("%m-%d %H:%M")


def build_message(ctx: OpsCtx, a: OpsAlert, *, kind: str = "alert", extra_note: str = "") -> AlertMessage:
    tzname = ctx.osettings.OPS_TIMEZONE
    lasted = int((a.last_at - a.first_at).total_seconds() // 60)
    when = f"{fmt_local(a.first_at, tzname)} 开始（北京时间）" + (f"，已经 {lasted} 分钟" if lasted >= 1 else "")
    if kind == "resolved":
        title = f"【已恢复】{a.title}"
        lines = [MessageLine(text=f"什么时候：{when}，{fmt_local(a.resolved_at or a.last_at, tzname)} 恢复"),
                 MessageLine(text=f"当时：{a.detail}")]
    else:
        title = f"【{LEVEL_LABELS.get(a.level, a.level)}】{a.title}" + ("（还没好）" if (a.notify_count or 0) >= 1 else "")
        lines = [MessageLine(text=f"发生了什么：{a.detail}"), MessageLine(text=f"什么时候：{when}"),
                 MessageLine(text=f"影响什么：{a.impact}")]
    url = ctx.admin_url(a.link)
    lines.append(MessageLine(text="去后台看：", link=url))
    if extra_note:
        lines.append(MessageLine(text=extra_note))
    return AlertMessage(kind="resolved" if kind == "resolved" else "alert", title=title, level=a.level,  # type: ignore[arg-type]
                        sections=[MessageSection(title="", lines=lines)], dedupe_key=a.key, link=url, happened_at=a.first_at)


def _pushed_last_hour(db: Session, now: datetime) -> int:
    """这一小时推了几条告警（日报、试发不算）。"""
    return stats.count_events(db, "ops.sent", now - timedelta(hours=1), now, where={"kind": ["alert", "resolved"]})


# ---------------------------------------------------------------- 一轮

def evaluate(call: NodeCall, cfg: OpsConfig, *, now: datetime, health: HealthOut | None) -> AlertEvalOut:
    db, ctx = call.db, call.ctx
    out = AlertEvalOut()
    findings: list[tuple[dict[str, Any], Finding]] = []
    for rule in cfg.all_rules():
        fn = RULES.get(rule["id"])
        if fn is None or not rule["enabled"]:
            continue
        if rule["id"] in HEALTH_RULES and health is None:
            continue
        try:
            for f in fn(db, ctx, rule, health, now):
                findings.append((rule, f))
        except Exception as e:  # noqa: BLE001  一条规则坏了不影响别的
            out.errors.append(f"{rule['id']}：{type(e).__name__}")
    open_rows = {a.key: a for a in db.scalars(select(OpsAlert).where(OpsAlert.status == "open"))}
    to_push: list[tuple[OpsAlert, str]] = []
    for rule, f in findings:
        a = open_rows.get(f.key)
        level = f.level or rule["level"]
        if f.firing:
            if a is None:
                a = OpsAlert(key=f.key, rule=rule["id"], level=level, title=rule["title"], detail=f.detail[:2000],
                             impact=(f.impact or rule["impact"])[:200], link=rule["link"], first_at=now, last_at=now, data=f.data)
                db.add(a)
                db.flush()
                open_rows[f.key] = a
                out.opened.append(f.key)
                record_event(db, "ops.alert_opened", f"ops_alert:{a.id}", {"key": f.key, "level": level, "detail": f.detail[:300]})
                if rule["push"]:
                    to_push.append((a, "alert"))
            else:
                escalated = LEVEL_RANK.get(level, 0) > LEVEL_RANK.get(a.level, 0)
                a.last_at, a.count, a.detail, a.data = now, a.count + 1, f.detail[:2000], f.data
                a.level = level if escalated else a.level
                a.impact = (f.impact or rule["impact"])[:200]
                out.still_open.append(f.key)
                silence = cfg.push.silence_minutes.get(a.level, 60)
                due = a.notified_at is None or (now - a.notified_at) >= timedelta(minutes=silence)
                if rule["push"] and (escalated or due):
                    to_push.append((a, "alert"))
        elif a is not None:
            a.status, a.resolved_at, a.resolved_by, a.last_at = "resolved", now, "auto", now
            out.resolved.append(f.key)
            record_event(db, "ops.alert_resolved", f"ops_alert:{a.id}", {"key": f.key, "by": "auto"})
            if rule["push"] and cfg.push.notify_resolved and a.level == "urgent" and (a.notify_count or 0) > 0:
                to_push.append((a, "resolved"))
    # 推送：总开关、级别、每小时上限
    budget = cfg.push.max_per_hour - _pushed_last_hour(db, now)
    held = kv_get(db, "push_held").get("n", 0)
    for a, kind in sorted(to_push, key=lambda x: -LEVEL_RANK.get(x[0].level, 0)):
        if not cfg.push.enabled or (kind == "alert" and a.level not in cfg.push.levels) or a.level == "info":
            continue
        if budget <= 0:
            held += 1
            out.suppressed += 1
            continue
        note = f"另外还有 {held} 条告警这一小时没推（防刷屏），去后台「运维」看。" if held else ""
        msg = build_message(ctx, a, kind=kind, extra_note=note)
        res = run_node("ops.send", call, msg)
        if res.output is not None and res.output.delivered:
            held = 0
        if kind == "alert":
            a.notified_at, a.notify_count = now, (a.notify_count or 0) + 1
        budget -= 1
        out.pushed += 1
    kv_set(db, "push_held", {"n": held})
    db.flush()
    return out


def level_counts(db: Session) -> dict[str, int]:
    return dict(_Counter(a.level for a in db.scalars(select(OpsAlert).where(OpsAlert.status == "open"))))
