"""后台：激活码（/api/admin/intake/codes，要登录）。

- 按货号批量生成（code.issue 节点；时长档 × 篇数档，或加购；在哪卖、数量、备注、有效期可选）→ 下载 CSV（发卡站
  Dujiao-Next 的卡密导入格式：表头一列 secret，下面一行一个码；一个货号一个文件，如 激活码_常规1篇_20261118-1.csv）
- 列表（没用 / 用了 / 作废；用在哪单、哪天）→ 作废（只有没用的能作废；用了的跟着订单作废走）
认领只走 order.claim 节点，这里没有认领接口。
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timezone
from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.core.nodes import NodeCall, run_node
from app.intake import clock, codes, pricing, service
from app.intake.config_store import load_config
from app.intake.models import CODE_STATUS_LABELS, ActivationCode, Customer, Order

router = APIRouter(prefix="/intake/codes", tags=["admin"])


def _out(row: ActivationCode, cfg, orders: dict[int, tuple[int | None, str]]) -> dict[str, Any]:
    o = orders.get(row.order_id) if row.order_id else None
    return {
        "id": row.id, "code": row.code, "sku": row.sku, "addons": row.addons or [],
        "sku_name": pricing.sku_name(cfg, row.sku, row.addons or []), "platform": row.platform,
        "platform_order_id": row.platform_order_id or "",
        "status": row.status, "status_label": CODE_STATUS_LABELS.get(row.status, row.status),
        "batch": row.batch, "note": row.note, "expires_at": row.expires_at,
        "order_id": row.order_id, "customer_id": o[0] if o else None, "customer_name": o[1] if o else "",
        "used_at": row.used_at, "voided_at": row.voided_at, "created_at": row.created_at,
    }


@router.get("")
def list_codes(status: Literal["unused", "used", "void", "all"] = "all", sku: str = "", batch: str = "", q: str = "",
               limit: int = 300, db: Session = Depends(get_db)) -> dict[str, Any]:
    cfg = load_config(db)
    stmt = select(ActivationCode)
    if status != "all":
        stmt = stmt.where(ActivationCode.status == status)
    if sku:
        stmt = stmt.where(ActivationCode.sku == sku)
    if batch:
        stmt = stmt.where(ActivationCode.batch == batch)
    if q.strip():
        norm = codes.normalize_code(q) or q.strip().upper()
        stmt = stmt.where(ActivationCode.code.contains(norm.replace("PSY-", "")))
    rows = list(db.scalars(stmt.order_by(ActivationCode.id.desc()).limit(min(max(limit, 1), 2000))))
    oids = {r.order_id for r in rows if r.order_id}
    orders: dict[int, tuple[int | None, str]] = {}
    for o in db.scalars(select(Order).where(Order.id.in_(oids))) if oids else []:
        c = db.get(Customer, o.customer_id) if o.customer_id else None
        orders[o.id] = (o.customer_id, service.display_name(c) if c else "还没认领")
    counts = dict(db.execute(select(ActivationCode.status, func.count()).group_by(ActivationCode.status)).all())
    batches = [{"batch": b, "sku": k, "sku_name": pricing.sku_name(cfg, k), "count": n, "created_at": at}
               for b, k, n, at in db.execute(
                   select(ActivationCode.batch, ActivationCode.sku, func.count(), func.min(ActivationCode.created_at))
                   .group_by(ActivationCode.batch, ActivationCode.sku)
                   .order_by(func.min(ActivationCode.created_at).desc()).limit(20)).all()]
    return {
        "rows": [_out(r, cfg, orders) for r in rows],
        "counts": {k: counts.get(k, 0) for k in CODE_STATUS_LABELS},
        "skus": [{"sku": k, "name": pricing.sku_name(cfg, k), "price": pricing.fmt_money(pricing.sku_price(cfg, k)),
                  "kind": "addon" if k.startswith("addon-") else "base"} for k in pricing.sellable_skus(cfg)],
        "batches": batches,
    }


class GenerateIn(BaseModel):
    sku: str = Field(min_length=1, max_length=48)
    addons: list[str] = Field(default_factory=list)
    platform: Literal["fk", "xy", "dy", "xhs", "web", "manual"] = "fk"
    count: int = Field(ge=1, le=2000)
    note: str = Field(default="", max_length=256)
    expires_on: date | None = None  # 这天（北京时间）结束前有效


@router.post("/generate")
def generate(body: GenerateIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    expires = None
    if body.expires_on is not None:
        if body.expires_on < clock.today():
            raise HTTPException(400, detail="有效期不能早于今天")
        expires = datetime.combine(body.expires_on, time(23, 59, 59), tzinfo=clock.TZ).astimezone(timezone.utc)
    res = run_node("code.issue", NodeCall(db, None, "edison"), {
        "action": "issue", "sku": body.sku, "count": body.count, "addons": body.addons, "platform": body.platform,
        "note": body.note, "expires_at": expires})
    if res.exit != "ok":
        raise HTTPException(400, detail=res.detail)
    db.commit()
    return {"batch": res.output.batch, "count": len(res.output.codes), "codes": res.output.codes}


@router.get("/export.csv")
def export_csv(batch: str = "", sku: str = "", status: Literal["unused", "all"] = "unused",
               db: Session = Depends(get_db)) -> Response:
    """发卡站导入用（codes.export_csv）。一个货号一个文件：给批次（一批就是一个货号）或者给货号。默认只导没用的。"""
    if batch:
        skus = set(db.scalars(select(ActivationCode.sku).where(ActivationCode.batch == batch).distinct()))
        if not skus:
            raise HTTPException(404, detail="没有这个批次")
        if sku and sku not in skus:
            raise HTTPException(400, detail="这个批次不是这个货号的")
        sku = sku or sorted(skus)[0]
    if not sku:
        raise HTTPException(400, detail="选一个货号或批次（发卡站一个货号一个商品，一个货号导一个文件）")
    stmt = select(ActivationCode.code).where(ActivationCode.sku == sku)
    if batch:
        stmt = stmt.where(ActivationCode.batch == batch)
    if status == "unused":
        stmt = stmt.where(ActivationCode.status == "unused")
    lines = list(db.scalars(stmt.order_by(ActivationCode.id)))
    label = re.sub(r"[\s·・.\\/:*?\"<>|+：]+", "", pricing.sku_name(load_config(db), sku)) or sku
    name = f"激活码_{label}_{batch or clock.today().strftime('%Y%m%d')}.csv"
    return Response(codes.export_csv(lines), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})


@router.post("/{cid}/void")
def void_code(cid: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    row = db.get(ActivationCode, cid)
    if row is None:
        raise HTTPException(404, detail="没有这个码")
    try:
        codes.void(db, row)
    except ValueError as e:
        raise HTTPException(409, detail=str(e)) from e
    db.commit()
    return _out(row, load_config(db), {})
