"""后台：运维（/api/admin/ops，要登录；只有 Edison 用）。设计 docs/任务单/07_运维与数据_设计.md 第五节。

- GET  health?external=0|1        深健康检查（库可写、水印队列、磁盘、证书、备份、外部依赖）
- GET  overview                   今天和近 7 天：请求、出错率、耗时分位数、访问、漏斗、支付、外部服务、产能、仪表、告警、备份、推送状态、定时任务
- GET  errors · GET slow          最近错误（5xx）· 慢接口（按路由）
- GET  alerts?status=open|all · POST alerts/{id}/resolve
- GET  settings · PUT settings    阈值、静默、保留期、日报时间、哪些告警推送、保存期限（存库里）
- POST test-send                  试发一条（没配飞书机器人 409）
- GET  report/preview?day= · POST report/send
- GET  backups · POST backups/run · POST backups/drill
- GET  lifecycle · POST flush（现在把计数写进库，走查用）
本文件导入时把各业务模块的读数登记进运维的接口位（ops_sources.register_all）。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin import ops_sources
from app.core.deps import get_db, get_write_db
from app.core.nodes import NodeCall, run_node
from app.ops import backup, scheduler, stats
from app.ops.config import LEVEL_LABELS, alert_rules, jobs, kv_get, load_config, save_config
from app.ops.health import backup_state
from app.ops.models import OpsAlert, OpsError
from app.ops.models_io import MessageLine, MessageSection, OpsMessage
from app.ops.runtime import get_ops
from app.ops.sender import build_sender, sender_status

ops_sources.register_all()
router = APIRouter(prefix="/ops", tags=["admin"])


def _call(request: Request, db: Session) -> NodeCall:
    return NodeCall(db, get_ops(request.app), "edison")


def _msg(m: OpsMessage) -> dict[str, Any]:
    return {"title": m.title, "level": m.level, "text": m.text(),
            "sections": [{"title": s.title, "lines": [ln.model_dump() for ln in s.lines]} for s in m.sections]}


@router.get("/health")
def health(request: Request, external: int = 1, db: Session = Depends(get_db)) -> dict[str, Any]:
    r = run_node("ops.health_check", _call(request, db), {"external": bool(external)})
    return r.output.model_dump(mode="json")


@router.get("/overview")
def overview(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    ctx = get_ops(request.app)
    cfg = load_config(db)
    now = ctx.now()
    tz = ctx.osettings.OPS_TIMEZONE
    win = stats.windows(now, tz)
    out: dict[str, Any] = {"now": now.isoformat(), "timezone": tz, "windows": {}}
    for key, (s, e) in win.items():
        out["windows"][key] = {
            "http": stats.http_summary(db, s, e), "pages": stats.pages(db, s, e), "funnel": stats.funnel(db, s, e, cfg.funnel),
            "payments": stats.payments(db, s, e), "externals": stats.externals(db, s, e, cfg.externals),
            "capacity": stats.capacity_from_events(db, s, e), "availability": stats.availability(db, s, e),
            "refunds": stats.count_events(db, "intake.order_voided", s, e, where={"code_action": "void"}),
        }
    gauges, gauge_errors = ops_sources_gauges(db, request)
    out["gauges"] = gauges
    out["gauge_errors"] = gauge_errors
    out["alerts_open"] = [_alert(a) for a in db.scalars(select(OpsAlert).where(OpsAlert.status == "open").order_by(OpsAlert.first_at.desc()))]
    st = backup_state(db)
    out["backup"] = {"done_at": st["done_at"], "done": st["done"], "failed_at": st["failed_at"], "failed": st["failed"],
                     "engine": backup.engine(ctx)}
    out["sender"] = sender_status(ctx.osettings, ctx.notifier)
    states = kv_get(db, "jobs")
    out["jobs"] = [{"id": j["id"], "label": j["label"], **states.get(j["id"], {})} for j in jobs()]
    out["last_report"] = kv_get(db, "last_report")
    return out


def ops_sources_gauges(db: Session, request: Request) -> tuple[list[dict[str, Any]], list[str]]:
    from app.ops import sources

    items, errors = sources.collect("gauge", db, request.app)
    return [g.model_dump() for g in items], errors


@router.get("/errors")
def errors(limit: int = 50, db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = db.scalars(select(OpsError).order_by(OpsError.id.desc()).limit(min(max(limit, 1), 200)))
    return {"rows": [{"id": r.id, "at": r.at, "rid": r.rid, "method": r.method, "route": r.route, "status": r.status, "kind": r.kind,
                      "message": r.message, "ms": r.ms} for r in rows]}


@router.get("/slow")
def slow(request: Request, days: int = 7, db: Session = Depends(get_db)) -> dict[str, Any]:
    now = get_ops(request.app).now()
    from datetime import timedelta

    return {"days": days, "rows": stats.route_table(db, now - timedelta(days=max(1, min(days, 365))), now, limit=15, min_n=5,
                                                    exclude_prefixes=stats.STAFF_PREFIXES)}


def _alert(a: OpsAlert) -> dict[str, Any]:
    return {"id": a.id, "key": a.key, "rule": a.rule, "level": a.level, "level_label": LEVEL_LABELS.get(a.level, a.level), "title": a.title,
            "detail": a.detail, "impact": a.impact, "link": a.link, "status": a.status, "first_at": a.first_at, "last_at": a.last_at,
            "count": a.count, "notified_at": a.notified_at, "notify_count": a.notify_count, "resolved_at": a.resolved_at,
            "resolved_by": a.resolved_by}


@router.get("/alerts")
def alerts(status: str = "open", db: Session = Depends(get_db)) -> dict[str, Any]:
    q = select(OpsAlert).order_by(OpsAlert.last_at.desc()).limit(100)
    if status == "open":
        q = q.where(OpsAlert.status == "open")
    return {"rows": [_alert(a) for a in db.scalars(q)]}


@router.post("/alerts/{alert_id}/resolve")
def resolve(alert_id: int, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    from app.core.events import record_event

    a = db.get(OpsAlert, alert_id)
    if a is None:
        raise HTTPException(404, detail="没有这条告警")
    if a.status == "open":
        now = get_ops(request.app).now()
        a.status, a.resolved_at, a.resolved_by, a.last_at = "resolved", now, "edison", now
        record_event(db, "ops.alert_resolved", f"ops_alert:{a.id}", {"key": a.key, "by": "edison"})
        db.commit()
    return _alert(a)


# ---------------------------------------------------------------- 设置

def _settings_out(request: Request, db: Session) -> dict[str, Any]:
    ctx = get_ops(request.app)
    cfg = load_config(db)
    return {"config": cfg.model_dump(), "rules": cfg.all_rules(), "levels": LEVEL_LABELS, "sender": sender_status(ctx.osettings, ctx.notifier),
            "rule_defaults": {r["id"]: r.get("params", {}) for r in alert_rules()},
            "backup_env": {"engine": backup.engine(ctx), "restic_installed": bool(backup.restic_bin(ctx)),
                           "cos_enabled": ctx.osettings.OPS_BACKUP_COS_ENABLED}}


@router.get("/settings")
def get_settings(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    return _settings_out(request, db)


class SettingsIn(BaseModel):
    config: dict[str, Any] = Field(default_factory=dict)


@router.put("/settings")
def put_settings(body: SettingsIn, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        save_config(db, body.config, by="edison")
    except ValidationError as e:
        first = e.errors()[0]
        raise HTTPException(422, detail=f"{'.'.join(str(x) for x in first['loc'])}：{first['msg']}") from e
    db.commit()
    return _settings_out(request, db)


# ---------------------------------------------------------------- 飞书

@router.post("/test-send")
def test_send(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    ctx = get_ops(request.app)
    if not build_sender(ctx.osettings, ctx.notifier).configured:
        raise HTTPException(409, detail="还没配飞书机器人：应用机器人把凭证存进文件、.env 写 FEISHU_APP_FILE=<那个文件>；"
                                        "或群机器人把 webhook 地址存进文件、.env 写 OPS_FEISHU_WEBHOOK_FILE=<那个文件>。重启后再试")
    msg = OpsMessage(kind="test", title="【试发】运维机器人能收到消息", level="info", sections=[MessageSection(title="", lines=[
        MessageLine(text=f"这是从后台点的试发（北京时间 {datetime.now(ZoneInfo(ctx.osettings.OPS_TIMEZONE)).strftime('%m-%d %H:%M')}）。收到就说明告警和日报都能发到这里。"),
        MessageLine(text="后台运维页：", link=ctx.admin_url("/admin/ops"))])])
    r = run_node("ops.send", _call(request, db), msg)
    db.commit()
    if r.exit != "sent":
        raise HTTPException(502, detail=f"没发出去：{r.detail}")
    return {"ok": True, "sender": r.output.sender if r.output else ""}


class ReportBody(BaseModel):
    day: str = ""


def _day(day: str) -> str:
    if day:
        try:
            date.fromisoformat(day)
        except ValueError as e:
            raise HTTPException(422, detail="日期写成 2026-11-17") from e
    return day


@router.get("/report/preview")
def report_preview(request: Request, day: str = "", db: Session = Depends(get_write_db)) -> dict[str, Any]:
    r = run_node("ops.daily_report", _call(request, db), {"day": _day(day), "send": False})
    db.commit()
    return {"day": r.output.day, "problems": r.output.problems, "message": _msg(r.output.message)}


@router.post("/report/send")
def report_send(body: ReportBody, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    r = run_node("ops.daily_report", _call(request, db), {"day": _day(body.day), "send": True})
    db.commit()
    if r.exit == "skipped":
        raise HTTPException(409, detail="还没配飞书机器人，发不出去（预览照样能看）")
    if r.exit != "sent":
        raise HTTPException(502, detail=f"没发出去：{r.detail}")
    return {"ok": True, "day": r.output.day}


# ---------------------------------------------------------------- 备份

@router.get("/backups")
def backups(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    from app.core.events import Event

    ctx = get_ops(request.app)
    out = backup.list_backups(ctx)
    drill = db.scalar(select(Event).where(Event.type == "ops.restore_drilled").order_by(Event.id.desc()).limit(1))
    out["last_drill"] = {"at": drill.created_at, **(drill.content or {})} if drill else None
    st = backup_state(db)
    out["last_done"] = {"at": st["done_at"], **st["done"]} if st["done_at"] else None
    out["last_failed"] = {"at": st["failed_at"], **st["failed"]} if st["failed_at"] else None
    out["config"] = load_config(db).backup.model_dump()
    return out


@router.post("/backups/run")
def backup_run(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    call = _call(request, db)
    r = run_node("ops.backup_run", call, {})
    db.commit()
    if r.exit == "ok":
        run_node("ops.backup_prune", call, {})
        db.commit()
    return {"exit": r.exit, "detail": r.detail, "result": r.output.model_dump() if r.output else None}


@router.post("/backups/drill")
def backup_drill(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    r = run_node("ops.restore_drill", _call(request, db), {})
    db.commit()
    return {"exit": r.exit, "detail": r.detail, "result": r.output.model_dump() if r.output else None}


# ---------------------------------------------------------------- 保存期限、走查

@router.get("/lifecycle")
def lifecycle(request: Request, db: Session = Depends(get_write_db)) -> dict[str, Any]:
    r = run_node("ops.lifecycle_scan", _call(request, db), {})
    db.commit()
    cfg = load_config(db)
    return {**r.output.model_dump(), "confirmed": cfg.lifecycle_confirmed}


@router.post("/flush")
def flush(request: Request) -> dict[str, Any]:
    scheduler.flush_now(request.app)
    return {"ok": True}
