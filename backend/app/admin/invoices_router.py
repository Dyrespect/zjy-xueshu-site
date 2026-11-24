"""后台：发票（/api/admin/invoices，要登录；只有 Edison 用）。设计 docs/任务单/07_开票_设计.md 第六节。

- GET   ""                     列表（status：pending 待开票 / draft 等订单完成 / issued 已开票 / closed 驳回作废撤回 / all）
- GET   export.csv             导出（Excel 能直接打开；防公式注入）
- GET   metrics                申请率、出票用时（评估数据）
- GET / PUT settings           设置（税率、纳税人类型、开票项目、专票开关……「待财务确认」的标出来）
- POST  {id}/issue             上传发票文件、标记已开（multipart：files、amount、invoice_no、note）→ invoice.issue
- POST  {id}/reject            驳回（写原因）→ invoice.reject
- POST  {id}/void              作废（reopen：作废重开）→ invoice.void
- PATCH {id}                   开出前改信息
- GET   order-lookup           录入前查一单：渠道、实付、完成没、有没有在办的发票
- POST  manual                 给任一渠道的单录一条（平台单）→ invoice.request(source=admin)
- GET   notices / POST notices/{id}/sent    待发的通知（邮件服务还没有），发了点一下
- POST  sweep                  现在跑一轮定时任务
- GET   {id}/files/{file_id}   后台下载
"""

from __future__ import annotations

import csv
import io
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.deps import get_db, get_write_db
from app.core.events import record_event
from app.core.nodes import NodeCall, run_node
from app.intake import clock, flow
from app.intake.models import Order
from app.intake.runtime import get_runtime
from app.invoices import metrics, service
from app.invoices.checks import InvoiceCheckFailed
from app.invoices.config import FINANCE_FIELDS, load_config, save_config
from app.invoices.facts import PLATFORM_NAMES, judge, shop_refunds
from app.invoices.models import KIND_LABELS, SOURCE_LABELS, InvoiceFile, InvoiceNotice, InvoiceRequest
from app.invoices.models_io import CloseIn, InvoiceFields, IssueFileIn, IssueIn, RequestIn, VoidIn
from app.invoices.router import run_sweep

router = APIRouter(prefix="/invoices", tags=["admin"])

STATUS_STEPS = {"pending": ("pending",), "draft": ("waiting", ""), "issued": ("issued",),
                "closed": ("rejected", "blocked", "voided", "cancelled")}


def _call(db: Session, request: Request) -> NodeCall:
    return NodeCall(db, get_runtime(request.app).ctx, "edison")


def _inv(db: Session, invoice_id: int) -> InvoiceRequest:
    inv = db.get(InvoiceRequest, invoice_id)
    if inv is None:
        raise HTTPException(404, detail="没有这张申请")
    return inv


def _row(db: Session, inv: InvoiceRequest, cfg: Any, refunds: dict) -> dict[str, Any]:
    order = db.get(Order, inv.order_id) if inv.order_id else None
    v = judge(db, order, cfg, admin=True, refunds=refunds) if order is not None else None
    f = v.facts if v else None
    warnings = list(v.warnings) if v else []
    if v is not None and v.exit != "open" and inv.flow_step in ("pending", "waiting"):
        warnings.insert(0, v.reason)
    if inv.flow_step == "issued" and f is not None and (f.fully_refunded or f.refund_pending or
                                                        f.refunded > (service.money(inv.refunded_snapshot) or 0)):
        warnings.insert(0, "开票以后又退了款或在退款：作废这张（需要的话重开），并让财务红冲")
    files = service.files_of(db, inv.id)
    return {
        "id": inv.id, "order_id": inv.order_id, "order_no": service.order_no(inv.order_id), "step": inv.flow_step or "prefill",
        "stage_label": flow.stage_label(inv) if inv.flow_step else "预填（还没付款挂上）",
        "platform": inv.platform, "platform_name": PLATFORM_NAMES.get(inv.platform, inv.platform or "—"),
        "source": inv.source, "source_label": SOURCE_LABELS.get(inv.source, inv.source),
        "kind": inv.kind, "kind_label": KIND_LABELS.get(inv.kind, inv.kind), "title_kind": inv.title_kind,
        **{k: getattr(inv, k) for k in service.CUSTOMER_FIELDS},
        "amount": inv.amount, "invoice_no": inv.invoice_no, "issue_note": inv.issue_note, "reason": inv.reason,
        "paid": f.as_dict()["paid"] if f else "", "refunded": f.as_dict()["refunded"] if f else "",
        "max_amount": f.as_dict()["max_amount"] if f else "", "order_stage": order.stage if order else "",
        "order_completed": bool(order and order.completed_at), "gate": v.exit if v else "",
        "warnings": warnings, "copy_text": service.copy_text(inv, cfg),
        "created_at": inv.created_at, "requested_at": inv.requested_at, "issued_at": inv.issued_at, "closed_at": inv.closed_at,
        "reopened_from": inv.reopened_from,
        "files": [{"id": x.id, "name": x.filename, "kind": x.kind, "size": x.size,
                   "url": f"/api/admin/invoices/{inv.id}/files/{x.id}"} for x in files],
        "notices": [{"id": n.id, "channel": n.channel, "status": n.status, "kind": n.kind} for n in service.notices_for(db, inv.id)],
    }


def _list(db: Session, status: str) -> list[InvoiceRequest]:
    q = select(InvoiceRequest).order_by(InvoiceRequest.id.desc()).limit(500)
    steps = STATUS_STEPS.get(status)
    if steps:
        q = q.where(InvoiceRequest.flow_step.in_(steps))
    return list(db.scalars(q))


@router.get("")
def list_invoices(request: Request, status: str = "pending", db: Session = Depends(get_write_db)) -> dict[str, Any]:
    ctx = get_runtime(request.app).ctx
    for inv in list(db.scalars(select(InvoiceRequest).where(InvoiceRequest.flow_step == "waiting"))):
        service.recheck(db, ctx, inv, by="edison")  # 草稿的订单完成了就顺手推进（定时任务也会推）
    db.commit()
    cfg = load_config(db)
    rows = _list(db, status)
    refunds = shop_refunds(db, {r.order_id for r in rows if r.order_id})
    counts = {k: len(_list(db, k)) for k in STATUS_STEPS}
    return {"rows": [_row(db, r, cfg, refunds) for r in rows], "counts": counts, "pending_finance": cfg.pending_finance()}


CSV_COLUMNS = [("id", "申请号"), ("order_no", "单号"), ("platform_name", "渠道"), ("stage_label", "状态"), ("requested_at", "申请时间"),
               ("kind_label", "发票类型"), ("title", "抬头"), ("tax_id", "纳税人识别号"), ("email", "邮箱"), ("bank_name", "开户行"),
               ("bank_account", "账号"), ("address", "地址"), ("phone", "电话"), ("remark", "备注"), ("max_amount", "可开金额"),
               ("paid", "实付"), ("refunded", "已退"), ("amount", "开票金额"), ("invoice_no", "发票号码"), ("issued_at", "开票时间")]


def _cell(v: Any) -> str:
    if hasattr(v, "astimezone"):  # 时间按北京时间写（设置里的时区）
        v = clock.local_now(v)
    s = "" if v is None else (v.strftime("%Y-%m-%d %H:%M") if hasattr(v, "strftime") else str(v))
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s  # 防 Excel 公式注入


@router.get("/export.csv")
def export_csv(request: Request, status: str = "pending", db: Session = Depends(get_write_db)) -> Response:
    cfg = load_config(db)
    rows = _list(db, status)
    refunds = shop_refunds(db, {r.order_id for r in rows if r.order_id})
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([label for _, label in CSV_COLUMNS] + ["开票项目", "税率", "销售方"])
    for inv in rows:
        r = _row(db, inv, cfg, refunds)
        w.writerow([_cell(r.get(k)) for k, _ in CSV_COLUMNS] + [cfg.item_name, cfg.tax_rate or "待财务填", cfg.seller_name])
    record_event(db, "invoice.exported", "invoice:export", {"status": status, "rows": len(rows), "by": "edison"})
    db.commit()
    name = f"发票_{status}_{utcnow().strftime('%Y%m%d')}.csv"
    return Response(("﻿" + buf.getvalue()).encode("utf-8"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename=invoices.csv; filename*=UTF-8''{quote(name)}"})


@router.get("/metrics")
def get_metrics(days: int = 7, db: Session = Depends(get_db)) -> dict[str, Any]:
    return metrics.weekly(db, days=max(1, min(days, 365)))


@router.get("/settings")
def get_settings(db: Session = Depends(get_db)) -> dict[str, Any]:
    cfg = load_config(db)
    return {"config": cfg.model_dump(), "finance_fields": FINANCE_FIELDS, "pending_finance": cfg.pending_finance(),
            "platforms": PLATFORM_NAMES}


@router.put("/settings")
def put_settings(body: dict[str, Any], db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        cfg = save_config(db, body.get("config", body), by="edison")
    except ValueError as e:
        db.rollback()
        raise HTTPException(422, detail=f"设置没存上：{e}") from e
    db.commit()
    return {"config": cfg.model_dump(), "finance_fields": FINANCE_FIELDS, "pending_finance": cfg.pending_finance(),
            "platforms": PLATFORM_NAMES}


def _result(db: Session, res: Any, ok: tuple[str, ...]) -> Any:
    if res.exit not in ok:
        db.rollback()
        return JSONResponse({"detail": res.detail, "exit": res.exit}, status_code=409)
    db.commit()
    out = res.output.model_dump(mode="json") if res.output is not None else {}
    return {"exit": res.exit, "detail": res.detail, **out}


@router.post("/{invoice_id}/issue")
async def issue(invoice_id: int, request: Request, files: list[UploadFile] = File(default_factory=list),
                amount: str = Form(""), invoice_no: str = Form(""), note: str = Form(""), db: Session = Depends(get_db)) -> Any:
    _inv(db, invoice_id)
    cfg = load_config(db)
    got: list[IssueFileIn] = []
    for up in files[:6]:
        data = await up.read(cfg.file_max_mb * 1024 * 1024 + 1)
        got.append(IssueFileIn(filename=(up.filename or "invoice")[:200], data=data))
    res = run_node("invoice.issue", _call(db, request), IssueIn(invoice_id=invoice_id, files=got, amount=amount.strip(),
                                                                invoice_no=invoice_no, note=note, by="edison"))
    return _result(db, res, ("issued",))


class ReasonBody(BaseModel):
    reason: str = Field(min_length=2, max_length=300)


class VoidBody(ReasonBody):
    reopen: bool = False
    fields: InvoiceFields | None = None


@router.post("/{invoice_id}/reject")
def reject(invoice_id: int, body: ReasonBody, request: Request, db: Session = Depends(get_db)) -> Any:
    _inv(db, invoice_id)
    res = run_node("invoice.reject", _call(db, request), CloseIn(invoice_id=invoice_id, reason=body.reason, by="edison"))
    return _result(db, res, ("ok",))


@router.post("/{invoice_id}/void")
def void(invoice_id: int, body: VoidBody, request: Request, db: Session = Depends(get_db)) -> Any:
    _inv(db, invoice_id)
    res = run_node("invoice.void", _call(db, request), VoidIn(invoice_id=invoice_id, reason=body.reason, reopen=body.reopen,
                                                             fields=body.fields, by="edison"))
    return _result(db, res, ("ok",))


@router.patch("/{invoice_id}")
def patch(invoice_id: int, body: InvoiceFields, db: Session = Depends(get_db)) -> Any:
    inv = _inv(db, invoice_id)
    try:
        service.update_fields(db, inv, body.model_dump(), by="edison")
    except InvoiceCheckFailed as e:
        db.rollback()
        return JSONResponse({"detail": str(e), "field": e.field}, status_code=422)
    db.commit()
    return {"ok": True}


@router.get("/order-lookup")
def order_lookup(order_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(404, detail=f"没有单号 {order_id}")
    v = judge(db, order, load_config(db), admin=True)
    have = service.active_for(db, order.id)
    return {"order_id": order.id, "order_no": service.order_no(order.id), "platform": order.platform,
            "platform_name": PLATFORM_NAMES.get(order.platform or "", order.platform or ""), "stage": order.stage,
            "stage_label": flow.stage_label(order), "gate": v.exit, "reason": v.reason, "warnings": v.warnings,
            **(v.facts.as_dict() if v.facts else {}), "active_invoice_id": have.id if have else None}


class ManualBody(BaseModel):
    order_id: int
    fields: InvoiceFields


@router.post("/manual")
def manual(body: ManualBody, request: Request, db: Session = Depends(get_db)) -> Any:
    if db.get(Order, body.order_id) is None:
        raise HTTPException(404, detail=f"没有单号 {body.order_id}")
    res = run_node("invoice.request", NodeCall(db, get_runtime(request.app).ctx, "edison"),
                   RequestIn(source="admin", order_id=body.order_id, fields=body.fields, confirmed=True, by="edison"))
    return _result(db, res, ("requested", "drafted"))


@router.get("/notices")
def notices(db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = list(db.scalars(select(InvoiceNotice).where(InvoiceNotice.status == "pending").order_by(InvoiceNotice.id.desc()).limit(200)))
    out = []
    for n in rows:
        inv = db.get(InvoiceRequest, n.invoice_id)
        out.append({"id": n.id, "invoice_id": n.invoice_id, "order_no": service.order_no(inv.order_id if inv else None),
                    "channel": n.channel, "kind": n.kind, "target": n.target, "subject": n.subject, "text": n.text,
                    "created_at": n.created_at})
    return {"rows": out}


@router.post("/notices/{notice_id}/sent")
def notice_sent(notice_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    n = db.get(InvoiceNotice, notice_id)
    if n is None:
        raise HTTPException(404, detail="没有这条通知")
    n.status, n.sent_at, n.detail = "sent", utcnow(), "负责人手动发的"
    record_event(db, "invoice.notice_sent", f"invoice:{n.invoice_id}", {"notice": n.id, "channel": n.channel, "by": "edison"})
    db.commit()
    return {"ok": True}


@router.post("/sweep")
def sweep(request: Request) -> dict[str, Any]:
    return run_sweep(request.app)


@router.get("/{invoice_id}/files/{file_id}")
def file(invoice_id: int, file_id: int, request: Request, db: Session = Depends(get_db)) -> Response:
    f = db.get(InvoiceFile, file_id)
    if f is None or f.invoice_id != invoice_id:
        raise HTTPException(404, detail="没有这个文件")
    data = get_runtime(request.app).ctx.storage.read_bytes(f.storage_key)
    media = {"pdf": "application/pdf", "ofd": "application/ofd", "xml": "application/xml"}.get(f.kind, "application/octet-stream")
    return Response(data, media_type=media, headers={"Content-Disposition": f"inline; filename=invoice-{f.id}.{f.kind}"})
