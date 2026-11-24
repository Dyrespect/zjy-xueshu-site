"""后台：交付版本（模块 E）。自动挂在 /api/admin/delivery 下、要登录。

- `GET  /delivery/orders/{oid}/versions`   这单每一版：状态、出图参数、错误、几页、什么时候发布、时限
- `POST /delivery/versions/{vid}/rerender` 重出图（出图失败、或者水印浓淡改了想重出还没发布的那一版）
人工上传成品、「交这一版」、「平台已确认收货」、「发最终版」在订单卡上（admin/intake_router.py）；
「平台已完成」录入和该看一眼清单是模块 B/C 的后台页，不重复做。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.deps import get_db
from app.core.events import record_event
from app.delivery import sla, versions
from app.delivery.models import DeliveryVersion
from app.intake import flow
from app.intake.models import Order
from app.intake.runtime import get_runtime

router = APIRouter(prefix="/delivery", tags=["admin-delivery"])

STATUS_LABEL = {"received": "收下了", "rendering": "出图中", "ready": "图出好了，等发布", "published": "已发布",
                "failed": "出图失败", "final": "已完成后交的最终版"}


def _out(v: DeliveryVersion) -> dict[str, Any]:
    return {
        "id": v.id, "round": v.round, "status": v.status, "status_label": STATUS_LABEL.get(v.status, v.status), "source": v.source,
        "note": v.note, "slide_count": v.slide_count, "page_count": v.page_count, "proof_file_ids": v.proof_file_ids,
        "final_file_ids": v.final_file_ids, "watermark_spec": v.watermark_spec, "error": v.error, "attempts": v.attempts,
        "created_at": v.created_at, "rendered_at": v.rendered_at, "published_at": v.published_at, "release_at": v.release_at,
    }


@router.get("/orders/{oid}/versions")
def order_versions(oid: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    o = db.get(Order, oid)
    if o is None:
        raise HTTPException(404, detail="没有这单")
    f = sla.facts(db, o, warn_ratio=versions.settings().DELIVERY_SLA_WARN_RATIO)
    return {"order_id": o.id, "stage": o.stage, "flow_step": o.flow_step, "watermark_alpha": versions.watermark_alpha(db),
            "sla": {"due_at": f.due_at, "first_published_at": f.first_published_at, "used_ratio": f.used_ratio, "state": f.state},
            "versions": [_out(v) for v in versions.versions_of(db, o.id)]}


@router.post("/versions/{vid}/rerender")
def rerender(vid: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """只给还没发布的当前版（订单在「出水印图」这一步）重出：放回队列，后台圈一分钟内出完并发布。"""
    v = db.get(DeliveryVersion, vid)
    if v is None:
        raise HTTPException(404, detail="没有这一版")
    o = db.get(Order, v.order_id)
    if o.flow_step != "proofing" or o.delivery_round + 1 != v.round:
        raise HTTPException(409, detail=f"这单现在是「{flow.stage_label(o)}」，第 {v.round} 版不在出图这一步；已经发布的版不重出")
    v.attempts, v.error = 0, ""
    versions.queue(v)
    v.updated_at = utcnow()
    record_event(db, "admin.delivery_rerender", f"order:{o.id}", {"version": v.id, "round": v.round})
    db.commit()
    return _out(v)


@router.post("/orders/{oid}/release-now")
def release_now(oid: int, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    """不加急的单压着的水印版（release.py）：负责人说现在就发。最早可发时间改成现在，再推一次「发布」。"""
    o = db.get(Order, oid)
    if o is None:
        raise HTTPException(404, detail="没有这单")
    v = versions.version_of(db, o.id, o.delivery_round + 1)
    if o.flow_step != "publish" or v is None or v.status != "ready":
        raise HTTPException(409, detail=f"这单现在是「{flow.stage_label(o)}」，没有压着等发的水印版")
    v.release_at = utcnow()
    record_event(db, "admin.delivery_release_now", f"order:{o.id}", {"version": v.id, "round": v.round})
    flow.emit(db, get_runtime(request.app).ctx, o, "proof_ready", by="edison", why="负责人点了「现在就发」")
    db.commit()
    return {"order_id": o.id, "stage": o.stage, "flow_step": o.flow_step, "published": o.flow_step != "publish"}
