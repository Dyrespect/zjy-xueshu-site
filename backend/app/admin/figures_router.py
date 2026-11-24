"""后台的图库几页（PRD P0-7）：反馈、需求、投图、意见四个列表，能标「处理了」、写一句备注；搜索统计。

挂在 /api/admin/figures 下，整个后台 router 已经要求登录（app/admin/router.py 自动挂 *_router.py）。
上传的图按号从这里取（要登录），不给文件路径。
"""

from __future__ import annotations

import mimetypes
from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.deps import get_db, get_storage
from app.core.events import record_event
from app.core.nodes import NodeCall, run_node
from app.core.storage import Storage
from app.figures.inbox import FEEDBACK_REASONS
from app.figures.library import thumb_url
from app.figures.models import (
    DECISION_NEW,
    STATUS_DONE,
    STATUS_NEW,
    FigureFeedback,
    FigureRequest,
    FigureSubmission,
    FigureTakedown,
    SearchClick,
    SearchLog,
    SiteFeedback,
)
from app.figures.node_models import CurateIn
from app.figures.overlay import FiguresCtx

router = APIRouter(prefix="/figures", tags=["admin-figures"])
TZ = ZoneInfo("Asia/Shanghai")  # 「今天」按北京时间算

Kind = Literal["feedback", "requests", "submissions", "site"]
MODELS: dict[str, Any] = {
    "feedback": FigureFeedback,
    "requests": FigureRequest,
    "submissions": FigureSubmission,
    "site": SiteFeedback,
}


def _lib(request: Request):
    return getattr(request.app.state, "figure_library", None)


def _figure(lib, fid: int) -> dict[str, Any]:
    d = lib.engine.doc(fid) if lib is not None else None
    if d is None:
        return {"id": fid, "thumb_url": "", "title": f"图 {fid}"}
    return {"id": fid, "thumb_url": thumb_url(fid, lib.asset_base), "title": d["h"].get("讲的是什么") or d["题目"]}


def _item(kind: str, row: Any, lib) -> dict[str, Any]:
    base = {
        "id": row.id,
        "created_at": row.created_at.isoformat(),
        "status": row.status,
        "admin_note": row.admin_note,
        "handled_at": row.handled_at.isoformat() if row.handled_at else None,
    }
    if kind == "feedback":
        base.update(
            figure=_figure(lib, row.figure_id),
            reason=FEEDBACK_REASONS.get(row.reason, row.reason),
            note=row.note,
            query=row.query,
            proposed=row.proposed or {},
            credit=row.credit,
            decision=row.decision,
        )
    elif kind == "requests":
        base.update(
            want=row.want,
            method=row.method,
            contact=row.contact,
            query=row.query,
            image_url=f"/api/admin/figures/uploads/requests/{row.id}" if row.sketch else "",
        )
    elif kind == "submissions":
        base.update(
            source=row.source,
            reason=row.reason,
            credit=row.credit,
            decision=row.decision,
            image_url=f"/api/admin/figures/uploads/submissions/{row.id}",
        )
    else:
        base.update(content=row.content, contact=row.contact, page=row.page)
    return base


@router.get("/inbox/{kind}")
def list_inbox(
    kind: Kind,
    request: Request,
    status: Literal["new", "done", "all"] = "all",
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    model = MODELS[kind]
    stmt = select(model).order_by(model.id.desc()).limit(limit)
    if status != "all":
        stmt = stmt.where(model.status == status)
    counts = dict(db.execute(select(model.status, func.count()).group_by(model.status)).all())
    lib = _lib(request)
    return {
        "kind": kind,
        "counts": {"new": counts.get(STATUS_NEW, 0), "done": counts.get(STATUS_DONE, 0)},
        "items": [_item(kind, r, lib) for r in db.scalars(stmt)],
    }


class InboxUpdate(BaseModel):
    status: Literal["new", "done"] | None = None
    admin_note: str | None = Field(default=None, max_length=500)


@router.patch("/inbox/{kind}/{item_id}")
def update_inbox(
    kind: Kind, item_id: int, body: InboxUpdate, request: Request, db: Session = Depends(get_db)
) -> dict[str, Any]:
    row = db.get(MODELS[kind], item_id)
    if row is None:
        raise HTTPException(404, detail="没有这一条")
    if body.status is not None and body.status != row.status:
        row.status = body.status
        row.handled_at = utcnow() if body.status == STATUS_DONE else None
    if body.admin_note is not None:
        row.admin_note = body.admin_note.strip()
    record_event(db, "admin.figures_inbox", f"{kind}:{item_id}", {"status": row.status, "admin_note": row.admin_note})
    db.commit()
    return _item(kind, row, _lib(request))


@router.get("/uploads/{kind}/{item_id}")
def upload_file(
    kind: Literal["requests", "submissions"],
    item_id: int,
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> Response:
    row = db.get(MODELS[kind], item_id)
    rel = (row.sketch if kind == "requests" else row.image) if row is not None else ""
    if not rel or not storage.exists(rel):
        raise HTTPException(404, detail="没有上传的图")
    media = mimetypes.guess_type(rel)[0] or "application/octet-stream"
    return Response(storage.read_bytes(rel), media_type=media, headers={"Cache-Control": "private, max-age=3600"})


@router.get("/stats")
def stats(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    now = utcnow()
    today_start = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    def count_since(t: datetime) -> int:
        return db.scalar(select(func.count()).select_from(SearchLog).where(SearchLog.created_at >= t)) or 0

    zero: Counter[str] = Counter()
    for words in db.scalars(select(SearchLog.zero_words).where(SearchLog.created_at >= month_ago)):
        zero.update(set(words or []))
    clicks = db.execute(
        select(SearchClick.figure_id, func.count().label("n"))
        .where(SearchClick.created_at >= month_ago)
        .group_by(SearchClick.figure_id)
        .order_by(func.count().desc())
        .limit(12)
    ).all()
    lib = _lib(request)
    recent = db.scalars(select(SearchLog).order_by(SearchLog.id.desc()).limit(20))
    names = lib.engine.names if lib is not None else {}
    return {
        "today": count_since(today_start),
        "week": count_since(week_ago),
        "zero_words": [{"word": w, "n": n} for w, n in zero.most_common(20)],
        "top_clicked": [{**_figure(lib, fid), "n": n} for fid, n in clicks],
        "recent": [
            {
                "id": s.id,
                "created_at": s.created_at.isoformat(),
                "query": s.query,
                "code_name": names.get(s.code, "不限图型"),
                "total": s.total,
                "zero_words": s.zero_words,
            }
            for s in recent
        ],
    }


# ---- 版权下架、审核（模块 L：figure.curate；07 设计第六节第 3、7 条）----

def _takedown(row: FigureTakedown, lib, now: datetime) -> dict[str, Any]:
    deadline = row.deadline_at
    return {
        "id": row.id,
        "created_at": row.created_at.isoformat(),
        "deadline_at": deadline.isoformat() if deadline else None,
        "overdue": bool(deadline and row.decision == DECISION_NEW and deadline < now),
        "hours_left": round((deadline - now).total_seconds() / 3600, 1) if deadline and row.decision == DECISION_NEW else None,
        "figure_ids": row.figure_ids or [],
        "figures": [_figure(lib, int(f)) for f in (row.figure_ids or [])],
        "figures_text": row.figures_text,
        "holder": row.holder,
        "contact": row.contact,
        "reason": row.reason,
        "decision": row.decision,
        "admin_note": row.admin_note,
    }


@router.get("/takedowns")
def list_takedowns(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    """版权方要求删除：没处理的按截止时间排最前，过了 48 小时的标出来。"""
    now = utcnow()
    rows = db.scalars(select(FigureTakedown).order_by(FigureTakedown.id.desc()).limit(200)).all()
    rows.sort(key=lambda r: (r.decision != DECISION_NEW, r.deadline_at or now))
    lib = _lib(request)
    items = [_takedown(r, lib, now) for r in rows]
    return {"items": items, "open": sum(1 for i in items if i["decision"] == DECISION_NEW),
            "overdue": sum(1 for i in items if i["overdue"])}


class CurateBody(BaseModel):
    decision: Literal["approve", "reject", "hide"]
    edited: dict[str, Any] = Field(default_factory=dict)
    note: str = Field(default="", max_length=300)


@router.post("/curate/{kind}/{item_id}")
def curate(kind: Literal["tag_fix", "submit", "takedown"], item_id: int, body: CurateBody, request: Request,
           db: Session = Depends(get_db)) -> dict[str, Any]:
    """审核：改标签通过 → 网站马上用新标签；版权下架 → 网站马上不显示；投图收 → 进下一版图库待收录。"""
    st = request.app.state
    ctx = FiguresCtx(getattr(st, "figure_library", None), getattr(st, "figure_cache", None), st.notifier)
    res = run_node("figure.curate", NodeCall(db, ctx, "admin"),
                   CurateIn(kind=kind, item_id=item_id, decision=body.decision, edited=body.edited, note=body.note))
    if res.exit in ("already", "bad"):
        db.rollback()
        raise HTTPException(409 if res.exit == "already" else 400, detail=res.detail)
    db.commit()
    return res.output.model_dump()
