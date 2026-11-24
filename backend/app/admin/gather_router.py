"""后台「聚人」（模块 L）：聚人数、领取列表（看截图、标假、手动发）、网盘链接、聚人设置、公众号关键词回复的字。

挂在 /api/admin/gather 下，整个后台 router 已经要求登录。截图按号取（要登录），不给文件路径。
"""

from __future__ import annotations

import mimetypes
from collections import Counter
from datetime import timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.deps import get_db, get_storage
from app.core.events import Event, record_event
from app.core.nodes import NodeCall, run_node
from app.core.storage import Storage
from app.figures.models import SearchLog
from app.gather import service
from app.gather.config import LABELS, VERIFIERS, ConfigError, load_config, save_config
from app.gather.models import FigurePack, FigureUnlock, FunnelVisit, PackGrant, UnlockEvidence
from app.gather.models_io import ReleaseIn
from app.gather.runtime import build_ctx, gather_settings
from app.intake.flow import StageError
from app.intake.models import Order

router = APIRouter(prefix="/gather", tags=["admin-gather"])


@router.get("/overview")
def overview(days: int = Query(default=7, ge=1, le=90), db: Session = Depends(get_db)) -> dict[str, Any]:
    """07 设计第三节那张表的数：来访按来源、转发带来几个新访客、领取三级数、点去下单、插件调用、图库带来几单。"""
    since = utcnow() - timedelta(days=days)
    by_src = dict(db.execute(select(FunnelVisit.src, func.count()).where(FunnelVisit.created_at >= since)
                             .group_by(FunnelVisit.src)).all())
    share_new = db.scalar(select(func.count()).select_from(FunnelVisit).where(
        FunnelVisit.created_at >= since, FunnelVisit.share_counted.is_(True))) or 0
    unlocks = db.scalars(select(FigureUnlock).where(FigureUnlock.created_at >= since)).all()
    with_evidence = db.scalar(select(func.count(func.distinct(UnlockEvidence.unlock_id))).where(
        UnlockEvidence.created_at >= since)) or 0
    sent = sum(1 for u in unlocks if u.sent_at is not None)
    top = sorted(unlocks, key=lambda u: -u.share_visits)[:10]
    clicks: Counter[str] = Counter()
    for content in db.scalars(select(Event.content).where(Event.type == "funnel.cta_click", Event.created_at >= since)):
        clicks[f"{content.get('placement')}→{content.get('target')}"] += 1
    callers = dict(db.execute(select(SearchLog.caller, func.count()).where(SearchLog.created_at >= since)
                              .group_by(SearchLog.caller)).all())
    tuku_orders = db.scalar(select(func.count()).select_from(Order).where(
        Order.created_at >= since, Order.source.like("tuku_%"))) or 0
    return {
        "days": days,
        "visits": sum(by_src.values()),
        "visits_by_src": [{"src": k or "（直接打开）", "n": v} for k, v in sorted(by_src.items(), key=lambda x: -x[1])],
        "share_new_visitors": share_new,
        "unlock_requested": len(unlocks),
        "unlock_evidence": with_evidence,
        "unlock_sent": sent,
        "top_sharers": [{"share_code": u.share_code, "visits": u.share_visits, "stage": u.stage} for u in top if u.share_visits],
        "cta_clicks": [{"what": k, "n": v} for k, v in clicks.most_common()],
        "search_by_caller": callers,
        "orders_from_tuku": tuku_orders,
        "grants": db.scalar(select(func.count()).select_from(PackGrant).where(PackGrant.sent_at >= since)) or 0,
    }


def _unlock(db: Session, u: FigureUnlock) -> dict[str, Any]:
    evs = db.scalars(select(UnlockEvidence).where(UnlockEvidence.unlock_id == u.id).order_by(UnlockEvidence.id)).all()
    grant = service.latest_grant(db, u.id)
    return {
        "id": u.id, "created_at": u.created_at.isoformat(), "share_code": u.share_code, "visitor": u.visitor[:12],
        "src": u.src, "stage": u.stage, "stage_label": service.stage_label(u), "flow_step": u.flow_step,
        "verifier": u.verifier or (u.verifiers or [""])[0], "reason": u.verdict_reason, "share_visits": u.share_visits,
        "evidence": [{"id": e.id, "url": f"/api/admin/gather/evidence/{e.id}", "mark": e.admin_mark,
                      "created_at": e.created_at.isoformat()} for e in evs],
        "sent_at": u.sent_at.isoformat() if u.sent_at else None,
        "resend_count": grant.resend_count if grant else 0,
        "actions": service.manual_options(u),
    }


@router.get("/unlocks")
def unlocks(stage: str = "", limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db)) -> dict[str, Any]:
    stmt = select(FigureUnlock).order_by(FigureUnlock.id.desc()).limit(limit)
    if stage:
        stmt = stmt.where(FigureUnlock.stage == stage)
    counts = dict(db.execute(select(FigureUnlock.stage, func.count()).group_by(FigureUnlock.stage)).all())
    return {"counts": counts, "items": [_unlock(db, u) for u in db.scalars(stmt)]}


@router.get("/evidence/{eid}")
def evidence_image(eid: int, db: Session = Depends(get_db), storage: Storage = Depends(get_storage)) -> Response:
    ev = db.get(UnlockEvidence, eid)
    if ev is None or not storage.exists(ev.file):
        raise HTTPException(404, detail="没有这张截图")
    media = mimetypes.guess_type(ev.file)[0] or "application/octet-stream"
    return Response(storage.read_bytes(ev.file), media_type=media, headers={"Cache-Control": "private, max-age=3600"})


class MarkIn(BaseModel):
    mark: Literal["ok", "fake", ""]


@router.post("/evidence/{eid}/mark")
def mark(eid: int, body: MarkIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    """抽查截图：标「假的」之后这个访客再交都不给（screenshot_trust / manual 都认）。"""
    ev = db.get(UnlockEvidence, eid)
    if ev is None:
        raise HTTPException(404, detail="没有这张截图")
    ev.admin_mark = body.mark
    record_event(db, "admin.gather_evidence_mark", f"figure_unlock:{ev.unlock_id}", {"evidence_id": eid, "mark": body.mark})
    db.commit()
    return _unlock(db, db.get(FigureUnlock, ev.unlock_id))


class PushIn(BaseModel):
    on: str = Field(min_length=1, max_length=32)
    why: str = Field(default="", max_length=200)


@router.post("/unlocks/{uid}/push")
def push(uid: int, body: PushIn, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    u = db.get(FigureUnlock, uid)
    if u is None:
        raise HTTPException(404, detail="没有这次领取")
    try:
        service.push(db, build_ctx(request, load_config(db)), u, body.on, by="admin", why=body.why or "后台手动推")
    except StageError as e:
        raise HTTPException(409, detail=str(e)) from None
    db.commit()
    return _unlock(db, u)


def _pack(p: FigurePack, db: Session) -> dict[str, Any]:
    n = db.scalar(select(func.count()).select_from(PackGrant).where(PackGrant.pack_id == p.id)) or 0
    return {"id": p.id, "version": p.version, "tier": p.tier, "provider": p.provider, "url": p.url,
            "extract_code": p.extract_code, "count": p.count, "size_mb": p.size_mb, "active": p.active,
            "note": p.note, "updated_at": p.updated_at.isoformat(), "grants": n}


@router.get("/packs")
def packs(db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = db.scalars(select(FigurePack).order_by(FigurePack.id.desc())).all()
    waiting = db.scalar(select(func.count()).select_from(FigureUnlock).where(FigureUnlock.flow_step == "wait_pack")) or 0
    return {"items": [_pack(p, db) for p in rows], "waiting": waiting}


@router.post("/packs")
def release(body: ReleaseIn, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    """贴网盘链接 = 这一版上线（figure.release）；同版本同一档再贴就是改链接。卡在「等链接」的自动补发。"""
    res = run_node("figure.release", NodeCall(db, build_ctx(request, load_config(db)), "admin"), body)
    if res.exit == "bad":
        raise HTTPException(400, detail=res.detail)
    db.commit()
    return {**_pack(db.get(FigurePack, res.output.pack_id), db), "resent": res.output.resent}


@router.post("/packs/{pid}/deactivate")
def deactivate(pid: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    p = db.get(FigurePack, pid)
    if p is None:
        raise HTTPException(404, detail="没有这个包")
    p.active = False
    record_event(db, "admin.gather_pack_off", f"figure_pack:{pid}", {"version": p.version, "tier": p.tier})
    db.commit()
    return _pack(p, db)


@router.get("/config")
def get_config(db: Session = Depends(get_db)) -> dict[str, Any]:
    return {"values": load_config(db), "labels": LABELS, "verifiers": VERIFIERS}


@router.put("/config")
def put_config(body: dict[str, Any], db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        values = save_config(db, body)
    except ConfigError as e:
        raise HTTPException(400, detail=str(e)) from None
    record_event(db, "admin.gather_config", "gather_settings", {"keys": sorted(body)})
    db.commit()
    return {"values": values, "labels": LABELS, "verifiers": VERIFIERS}


@router.get("/gzh-reply")
def gzh_reply(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    """公众号后台关键词回复要贴的字（小包链接、提取码、网站地址）；没贴小包链接就说清楚。"""
    cfg = load_config(db)
    gs = gather_settings(request)
    lite = service.active_pack(db, "lite")
    if lite is None:
        return {"keyword": cfg["gzh_keyword"], "text": "", "missing": "后台还没贴小包（lite）的网盘链接：先在「网盘链接」贴上。"}
    figures_url = gs.SITE_FIGURES_URL or build_ctx(request).figures_url
    return {"keyword": cfg["gzh_keyword"], "text": service.pack_text(lite, cfg, gs, figures_url=figures_url), "missing": ""}
