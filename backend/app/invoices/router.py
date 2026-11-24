"""开票的客人接口（挂在 /api/invoices，不登录）。路由只认人、转节点，判断都在节点和 service 里。设计第六节。

认人两种，都是只有这单主人才有的随机令牌：
- 交付页 /d/<交付页令牌>：令牌 → 订单（intake_orders.delivery_token）。
- 付款结果页 /order/pay/<付款页令牌>：令牌 → 付款单 → 订单，走模块 B 的只读节点 shop.checkout_lookup（不读它的表、不靠激活码）。
下载发票每次都重新校验「这张发票是这一单的、而且是已开票」（checks.require_owner，K1）。
返回都带 no-store、noindex；每个 IP 每小时最多 INVOICE_PUBLIC_HOURLY_LIMIT 次（防撞令牌）。
lifespan：invoice.sweep 登记到底座调度器（草稿推进、开票后退款提醒、过期预填清掉；全集群一个在跑）。限流在 core.ratelimit。
"""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import access
from app.core.deps import client_ip, get_db, get_ratelimiter
from app.core.nodes import NodeCall, has_handler, run_node
from app.intake.models import Order
from app.intake.runtime import get_runtime
from app.invoices import nodes as _nodes  # noqa: F401  登记本模块的节点（含流程对象和流程文件夹）
from app.invoices import service
from app.invoices.checks import InvoiceCheckFailed, require_owner
from app.invoices.config import load_config
from app.invoices.models import InvoiceFile, InvoiceRequest
from app.invoices.models_io import CloseIn, InvoiceFields, RequestIn, SweepIn
from app.invoices.settings import InvoiceSettings

log = logging.getLogger("app.invoices")
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{20,64}$")
NOINDEX = {"X-Robots-Tag": "noindex, nofollow", "Cache-Control": "no-store"}
MEDIA = {"pdf": "application/pdf", "ofd": "application/ofd", "xml": "application/xml"}


def _no_store(response: Response) -> None:
    response.headers.update(NOINDEX)


router = APIRouter(dependencies=[Depends(_no_store)])


# ---------------------------------------------------------------- 运行时：配置、限流

class _Runtime:
    def __init__(self, settings: InvoiceSettings) -> None:
        self.settings = settings


def runtime(app: FastAPI) -> _Runtime:
    rt = getattr(app.state, "invoices", None)
    if rt is None:
        rt = _Runtime(getattr(app.state, "invoice_settings", None) or InvoiceSettings())
        app.state.invoices = rt
    return rt


def _limit(request: Request) -> None:
    rt = runtime(request.app)
    if not get_ratelimiter(request).hit("invoices.public", client_ip(request), limit=rt.settings.INVOICE_PUBLIC_HOURLY_LIMIT,
                                        window=3600):
        raise HTTPException(429, detail="操作太频繁了，过一会儿再试")


def _ctx(request: Request) -> Any:
    return get_runtime(request.app).ctx


def _call(db: Session, request: Request, by: str = "customer") -> NodeCall:
    return NodeCall(db, _ctx(request), by)


def _fail(status: int, detail: str, field: str = "") -> JSONResponse:
    return JSONResponse({"detail": detail, "field": field}, status_code=status, headers=NOINDEX)


# ---------------------------------------------------------------- 认人

def _order_by_delivery(db: Session, token: str) -> Order:
    if not TOKEN_RE.match(token):
        raise HTTPException(404, detail="链接不对")
    order = db.scalar(select(Order).where(Order.delivery_token == token))
    if order is None:
        raise HTTPException(404, detail="链接不对")
    return order


def _checkout(db: Session, request: Request, token: str) -> tuple[bool, int | None]:
    """付款页令牌 → (有这个付款单, 订单号)。shop.checkout_lookup 没登记时付款页不出发票。"""
    if not TOKEN_RE.match(token) or not has_handler("shop.checkout_lookup"):
        raise HTTPException(404, detail="这个付款单看不了发票，去交付页申请")
    r = run_node("shop.checkout_lookup", _call(db, request), {"view_token": token})
    found = r.exit == "ok" and r.output is not None and r.output.found
    return found, (r.output.order_id if found else None)


def _order_by_checkout(db: Session, request: Request, token: str) -> Order:
    found, oid = _checkout(db, request, token)
    if not found:
        raise HTTPException(404, detail="没有这个付款单")
    order = db.get(Order, oid) if oid else None
    if order is None:
        raise HTTPException(409, detail="还没付款成功，付完再看发票")
    return order


# ---------------------------------------------------------------- 入参出参

class ApplyBody(BaseModel):
    fields: InvoiceFields
    confirmed: bool = False


class DraftBody(ApplyBody):
    checkout_token: str = Field(min_length=20, max_length=64)


class WithdrawBody(BaseModel):
    invoice_id: int


class InvoiceFileOut(BaseModel):
    id: int
    name: str
    kind: str
    size: int
    url: str


class InvoiceOut(BaseModel):
    id: int
    step: str
    stage: str
    stage_label: str
    note: str
    kind: str
    kind_label: str
    title_kind: str
    title_kind_label: str
    title: str
    tax_id: str
    email: str
    bank_name: str
    bank_account: str
    address: str
    phone: str
    remark: str
    amount: str
    invoice_no: str
    reason: str
    created_at: Any = None
    requested_at: Any = None
    issued_at: Any = None
    closed_at: Any = None
    can_withdraw: bool
    files: list[InvoiceFileOut]


class KindOut(BaseModel):
    key: str
    label: str
    required: list[str]


class PublicConfigOut(BaseModel):
    enabled: bool
    kinds: list[KindOut]
    allow_personal: bool
    allow_remark: bool
    labels: dict[str, str]
    notice: str
    promise: str
    seller_name: str
    item_name: str


class PanelOut(BaseModel):
    enabled: bool
    eligible: bool
    can_apply: bool
    why_not: str
    order_no: str
    completed: bool
    apply_note: str
    current: InvoiceOut | None
    history: list[InvoiceOut]
    config: PublicConfigOut


class SubmitOut(BaseModel):
    exit: str
    invoice_id: int | None = None
    note: str = ""


# ---------------------------------------------------------------- 接口

@router.get("/config", dependencies=[Depends(access.public)], response_model=PublicConfigOut)
def get_config(db: Session = Depends(get_db)) -> Any:
    return service.public_config(load_config(db))


def _submit(db: Session, request: Request, req: RequestIn) -> Any:
    res = run_node("invoice.request", _call(db, request, req.by), req)
    if res.exit in ("invalid", "not_eligible"):
        db.rollback()
        return _fail(422 if res.exit == "invalid" else 409, res.detail, res.output.field if res.output else "")
    db.commit()
    out = res.output
    return SubmitOut(exit=res.exit, invoice_id=out.invoice_id if out else None, note=out.note if out else res.detail)


@router.post("/drafts", response_model=SubmitOut, dependencies=[Depends(access.by_token), Depends(_limit)])
def post_draft(body: DraftBody, request: Request, db: Session = Depends(get_db)) -> Any:
    """下单页：拿到付款页令牌后存预填（付款前，还没有订单）。令牌要真有这个付款单。"""
    found, oid = _checkout(db, request, body.checkout_token)
    if not found:
        raise HTTPException(404, detail="没有这个付款单")
    if oid:  # 已经付了：直接挂到这单上
        return _submit(db, request, RequestIn(source="pay_page", order_id=oid, checkout_token=body.checkout_token,
                                              fields=body.fields, confirmed=body.confirmed))
    return _submit(db, request, RequestIn(source="checkout", checkout_token=body.checkout_token, fields=body.fields,
                                          confirmed=body.confirmed))


def _panel(db: Session, request: Request, order: Order, file_url: Any) -> Any:
    service.refresh_order(db, _ctx(request), order.id, by="customer")
    db.commit()
    return service.panel(db, order, file_url=file_url)


# 付款结果页

@router.post("/checkout/{token}", response_model=PanelOut, dependencies=[Depends(access.by_token), Depends(_limit)])
def checkout_panel(token: str, request: Request, db: Session = Depends(get_db)) -> Any:
    """付款结果页的发票一块：有下单页预填就挂到这单上（订单没完成是草稿）。"""
    order = _order_by_checkout(db, request, token)
    service.bind_prefill(db, _ctx(request), checkout_token=token, order=order)
    db.commit()
    return _panel(db, request, order, lambda f: f"/api/invoices/checkout/{quote(token)}/files/{f.id}")


@router.post("/checkout/{token}/apply", response_model=SubmitOut, dependencies=[Depends(access.by_token), Depends(_limit)])
def checkout_apply(token: str, body: ApplyBody, request: Request, db: Session = Depends(get_db)) -> Any:
    order = _order_by_checkout(db, request, token)
    return _submit(db, request, RequestIn(source="pay_page", order_id=order.id, checkout_token=token, fields=body.fields,
                                          confirmed=body.confirmed))


@router.post("/checkout/{token}/withdraw", response_model=SubmitOut, dependencies=[Depends(access.by_token), Depends(_limit)])
def checkout_withdraw(token: str, body: WithdrawBody, request: Request, db: Session = Depends(get_db)) -> Any:
    return _withdraw(db, request, _order_by_checkout(db, request, token), body.invoice_id)


@router.get("/checkout/{token}/files/{file_id}", dependencies=[Depends(access.by_token), Depends(_limit)])
def checkout_file(token: str, file_id: int, request: Request, db: Session = Depends(get_db)) -> Response:
    return _download(db, request, _order_by_checkout(db, request, token), file_id)


# 交付页

@router.get("/order/{token}", response_model=PanelOut, dependencies=[Depends(access.by_token), Depends(_limit)])
def order_panel(token: str, request: Request, db: Session = Depends(get_db)) -> Any:
    order = _order_by_delivery(db, token)
    return _panel(db, request, order, lambda f: f"/api/invoices/order/{quote(token)}/files/{f.id}")


@router.post("/order/{token}/apply", response_model=SubmitOut, dependencies=[Depends(access.by_token), Depends(_limit)])
def order_apply(token: str, body: ApplyBody, request: Request, db: Session = Depends(get_db)) -> Any:
    order = _order_by_delivery(db, token)
    return _submit(db, request, RequestIn(source="delivery", order_id=order.id, fields=body.fields, confirmed=body.confirmed))


@router.post("/order/{token}/withdraw", response_model=SubmitOut, dependencies=[Depends(access.by_token), Depends(_limit)])
def order_withdraw(token: str, body: WithdrawBody, request: Request, db: Session = Depends(get_db)) -> Any:
    return _withdraw(db, request, _order_by_delivery(db, token), body.invoice_id)


@router.get("/order/{token}/files/{file_id}", dependencies=[Depends(access.by_token), Depends(_limit)])
def order_file(token: str, file_id: int, request: Request, db: Session = Depends(get_db)) -> Response:
    return _download(db, request, _order_by_delivery(db, token), file_id)


def _withdraw(db: Session, request: Request, order: Order, invoice_id: int) -> Any:
    inv = db.get(InvoiceRequest, invoice_id)
    if inv is None or inv.order_id != order.id:
        raise HTTPException(404, detail="没有这张申请")
    res = run_node("invoice.withdraw", _call(db, request), CloseIn(invoice_id=inv.id, reason="客人撤回", by="customer"))
    if res.exit != "ok":
        db.rollback()
        return _fail(409, res.detail)
    db.commit()
    return SubmitOut(exit="ok", invoice_id=inv.id, note=res.output.note if res.output else "")


def _download(db: Session, request: Request, order: Order, file_id: int) -> Response:
    """K1：这张发票是这一单的、而且是已开票，才给文件。"""
    f = db.get(InvoiceFile, file_id)
    inv = db.get(InvoiceRequest, f.invoice_id) if f is not None else None
    if inv is None or inv.order_id != order.id:  # 别的单的发票文件一律 404（12 号设计第十节：不说 403，不让人试出别人的文件号存不存在）
        raise HTTPException(404, detail="没有这张发票")
    try:
        require_owner(invoice_order_id=inv.order_id if inv else None, order_id=order.id,
                      issued=inv is not None and inv.flow_step == "issued")
    except InvoiceCheckFailed as e:
        raise HTTPException(403 if inv is not None else 404, detail=e.public()) from e
    data = _ctx(request).storage.read_bytes(f.storage_key)
    service.record_download(db, inv, f, by="customer")
    db.commit()
    name = f"发票_{service.order_no(order.id)}_{f.id}.{f.kind}"
    return Response(data, media_type=MEDIA.get(f.kind, "application/octet-stream"), headers={
        **NOINDEX, "Content-Disposition": f"attachment; filename=invoice-{f.id}.{f.kind}; filename*=UTF-8''{quote(name)}"})


# ---------------------------------------------------------------- 定时任务

def run_sweep(app: FastAPI) -> dict[str, Any]:
    rt = runtime(app)
    with app.state.db.session() as db:
        r = run_node("invoice.sweep", NodeCall(db, get_runtime(app).ctx, "system:invoice_sweep"),
                     SweepIn(prefill_ttl_days=rt.settings.INVOICE_PREFILL_TTL_DAYS))
        db.commit()
        return r.output.model_dump() if r.output else {}


def _sweep_and_log(app: FastAPI) -> None:
    res = run_sweep(app)
    if res.get("promoted") or res.get("refund_after_issue"):
        log.info("发票定时任务：%s", res)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    rt = runtime(app)
    if rt.settings.INVOICE_TIMER_ENABLED:
        every = max(30, rt.settings.INVOICE_TIMER_INTERVAL_SEC)
        app.state.scheduler.every("invoices.sweep", every, lambda: _sweep_and_log(app), initial_delay=every)
    yield
