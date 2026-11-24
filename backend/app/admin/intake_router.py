"""后台：接单这一块（会话、待发、订单、设置）。挂在 /api/admin/intake，整个要登录。激活码在 codes_router.py。

接单 v2：助手的回复直接发，后台只用来看、统计、必要时「我来接」。会话页看得清：客户说了什么、助手发了什么、
为什么（工具调用摘要）、还能发几条（微信客服 48 小时 / 5 条）；订单卡上有制作方会话（全部消息）。
设置里打开了「先给我看」的类别才有待批，批准以后马上让 channels 发一次。每个动作都留事件记录（service 里写）。

11-18 订单中枢：订单状态 = 流程步骤（stage），后台能看、能按流程里标了 manual 的连线手动推一步、已完成之前能作废
（码退回 / 码作废）、能给没认领的会话手动开单（先做后付）。「我来接」只停助手，不再把微信会话转人工（主窗口裁决 K3）。
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.channels.dispatch import dispatch_approved
from app.channels.runtime import get_channels, wecom_configured
from app.channels.wecom_client import WecomError
from app.core.deps import get_db
from app.delivery import release
from app.core.events import list_events
from app.core.events import record_event
from app.core.nodes import NodeCall, has_node, run_node
from app.intake import clock, flow, orders, pricing, service
from app.intake.config_store import REPLY_CATEGORIES, BizConfig, load_config, save_config
from app.intake.flow import StageError
from app.intake.handoff import handoff_out, latest_handoff
from app.intake.production import maker_state
from app.intake.llm import model_label
from app.intake.models import (
    DELIVERABLE_KINDS,
    MATERIAL_PURPOSES,
    OUTBOX_STATUS_LABELS,
    PAGE_KIND,
    STAGE_LABELS,
    ActivationCode,
    BotRun,
    Customer,
    FileRecord,
    Message,
    Order,
    Outbox,
    Revision,
)
from app.intake.runtime import get_runtime

router = APIRouter(prefix="/intake", tags=["admin"])


def _ctx(request: Request) -> service.Ctx:
    return get_runtime(request.app).ctx


def _customer(db: Session, cid: int) -> Customer:
    c = db.get(Customer, cid)
    if c is None:
        raise HTTPException(404, detail="没有这个客户")
    return c


def _order(db: Session, oid: int) -> Order:
    o = db.get(Order, oid)
    if o is None:
        raise HTTPException(404, detail="没有这单")
    return o


def _latest_order(db: Session, c: Customer) -> Order | None:
    return orders.latest_order(db, c)


def _stage_label(o: Order | None) -> str:
    if o is None:
        return "访客（没认领）"
    return flow.stage_label(o)


def _file_out(f: FileRecord) -> dict[str, Any]:
    return {"id": f.id, "name": f.filename, "size": f.size, "purpose": f.purpose, "note": f.note,
            "role": f.role, "round": f.round, "url": f"/api/admin/intake/files/{f.id}",
            "is_image": (f.content_type or "").startswith("image/") or Path(f.filename).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")}


async def _dispatch(request: Request, outbox_id: int | None = None) -> None:
    await dispatch_approved(get_channels(request.app), outbox_id=outbox_id)


# ---------------------------------------------------------------- 会话

def _pending_count(db: Session, cid: int) -> int:
    return db.scalar(select(func.count()).select_from(Outbox).where(Outbox.customer_id == cid, Outbox.status == "pending")) or 0


@router.get("/conversations")
def conversations(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = []
    for c in db.scalars(select(Customer)):
        last = db.scalar(select(Message).where(Message.customer_id == c.id).order_by(Message.id.desc()).limit(1))
        order = _latest_order(db, c)
        pending = _pending_count(db, c.id)
        failed = db.scalar(select(func.count()).select_from(Outbox).where(Outbox.customer_id == c.id, Outbox.status == "failed")) or 0
        needs = len([n for n in (order.needs_edison or []) if not n.get("resolved")]) if order else 0
        if last is None and not pending:
            continue  # 开了网页聊天但一句没说的不列
        rows.append({
            "id": c.id,
            "name": service.display_name(c),
            "channel": c.channel,
            "source": c.source,
            "status": order.stage if order else "",
            "status_label": _stage_label(order),
            "last_text": (last.text if last.kind == "text" else f"[{ {'file': '文件', 'image': '图片', 'voice': '语音'}.get(last.kind, last.kind) }] {last.text}") if last else "",
            "last_from": ("customer" if last.direction == "in" else last.sender) if last else "",
            "last_at": c.last_activity_at,
            "pending": pending,
            "failed": failed,
            "needs": needs,
            "takeover": c.human_takeover,
        })
    rows.sort(key=lambda r: (r["pending"] == 0 and r["failed"] == 0, r["needs"] == 0, -r["last_at"].timestamp()))
    return rows


def _run_brief(run: BotRun | None) -> dict[str, Any] | None:
    if run is None:
        return None
    return {
        "id": run.id, "model": run.model, "tools": run.tool_calls, "error": run.error,
        "requests": run.requests, "input_tokens": run.input_tokens, "output_tokens": run.output_tokens,
        "started_at": run.started_at,
    }


def _handoff_brief(db: Session, o: Order) -> dict[str, Any] | None:
    """订单卡上的交接状态：待领 / 已领 / 直接写入。"""
    h = latest_handoff(db, o)
    if h is not None:
        return handoff_out(h)
    if o.started_at and o.handoff_folder:  # 加交接记录之前就交接过的单（都是直接写入）
        return {"id": None, "mode": "direct", "status": "direct", "status_label": "直接写入", "folder": o.handoff_folder,
                "files": [], "size": 0, "created_at": o.started_at, "claimed_at": None, "claimed_folder": ""}
    return None


def _order_out(db: Session, ctx: service.Ctx, o: Order) -> dict[str, Any]:
    cfg = load_config(db)
    rule = cfg.rule(o.occasion)
    materials = service.order_files(db, o)
    have = {f.purpose for f in materials if f.purpose}
    conds = service.conditions_for(db, o, cfg)
    plan = service.plan_for(db, o, cfg)
    deliverables = service.order_files(db, o, "deliverable")
    pages = service.order_files(db, o, "page")
    revisions = list(db.scalars(select(Revision).where(Revision.order_id == o.id).order_by(Revision.id)))
    rev_files = {f.id: f for f in service.order_files(db, o, "revision")}
    tier = cfg.tier(o.tier_key)
    code = db.get(ActivationCode, o.code_id) if o.code_id else None
    pmsgs = service.production_messages(db, o)
    pfids = {i for m in pmsgs for i in (m.file_ids or [])}
    pfiles = {f.id: f for f in db.scalars(select(FileRecord).where(FileRecord.id.in_(pfids)))} if pfids else {}
    fl = flow.flow_of(o) if o.flow_step else None
    addon_keys = orders.addon_keys(o)
    can_void = bool(o.flow_step) and flow.accepts(o, "voided")
    return {
        "id": o.id,
        "status": o.stage,
        "status_label": _stage_label(o),
        "stage": o.stage, "flow_key": o.flow_key, "flow_step": o.flow_step,
        "stage_track": [{"key": st.key, "label": st.label} for st in fl.stages if st.key != "void"] if fl else [],
        "progress": orders.progress(db, o, cfg),
        "manual": flow.manual_options(o) if o.flow_step else [],
        "can_void": can_void, "can_return_code": can_void and o.started_at is None and o.code_id is not None,
        "voided_from": o.voided_from, "voided_from_label": STAGE_LABELS.get(o.voided_from, o.voided_from), "void_reason": o.void_reason,
        "hold_reason": o.hold_reason,
        "platform": o.platform, "platform_order_id": o.platform_order_id or "", "buyer_id": o.buyer_id[-6:] if o.buyer_id else "",
        "source": o.source, "paid_at": o.paid_at, "paid_amount": o.paid_amount, "claimed_at": o.claimed_at,
        "platform_completed_at": o.platform_completed_at, "completed_at": o.completed_at,
        "sku": o.sku, "sku_name": pricing.sku_name(cfg, o.sku, addon_keys) if o.sku else "",
        "addons": [{"key": a.get("key"), "name": pricing.addon_names(cfg, [a.get("key", "")])[0], "by": a.get("by"), "code": a.get("code", "")}
                   for a in (o.addons or [])],
        "max_pages": tier.max_pages if tier else None, "due_hours": o.due_hours, "page_rule": cfg.page_rule_text,
        "occasion": o.occasion, "title": o.title, "duration_min": o.duration_min,
        "duration_default": o.duration_default, "duration_confirmed": o.duration_confirmed,
        "paper_count": o.paper_count, "page_count": o.page_count,
        "present_date": o.present_date, "present_date_text": o.present_date_text,
        "school": o.school, "language": o.language, "structure_req": o.structure_req,
        "requirement_quotes": o.requirement_quotes or [], "quoted_price": o.quoted_price,
        "tier_key": o.tier_key, "tier_name": tier.name if tier else "",
        "code": code.code if code else "", "redeemed_at": o.claimed_at or o.redeemed_at,
        "revisions_left": service.revisions_left(o, cfg), "extra_revisions": o.extra_revisions,
        "rush": o.rush, "rush_by_edison": any(a.get("key") == "rush" and a.get("by") == "edison" for a in (o.addons or [])),
        "needs": o.needs_edison or [],
        "required": [{"purpose": p, "ok": p in have} for p in (rule.required if rule else [])],
        "optional_hint": "、".join(m.text for m in rule.nice) if rule and rule.nice else (rule.optional_hint if rule else ""),
        "materials": [_file_out(f) for f in materials],
        "conditions": [c.__dict__ for c in conds],
        "plan": {"start_date": plan.start_date, "eta_date": plan.eta_date} if plan else None,
        "queued": o.queued_at is not None, "start_date": o.start_date, "eta_date": o.eta_date,
        "started_at": o.started_at, "handoff_folder": o.handoff_folder,
        "handoff": _handoff_brief(db, o), "handoff_mode": ctx.settings.HANDOFF_MODE,
        "deliverables": [_file_out(f) for f in deliverables],
        "pages": len([p for p in pages if p.round > o.delivery_round]),
        "delivery_round": o.delivery_round, "delivered_at": o.delivered_at,
        # 不加急的单第一版压着（delivery/release.py）：几点自动发给客人；订单卡上有「现在就发」
        "hold_until": release.waiting(db, o),
        "has_new_deliverable": service.has_undelivered_deliverable(db, o),
        "can_submit_package": flow.accepts(o, "package_received") if o.flow_step else False,
        "revisions": [{"id": r.id, "text": r.text, "items": r.items or [], "free": r.free, "status": r.status, "created_at": r.created_at,
                       "files": [_file_out(rev_files[i]) for i in r.file_ids if i in rev_files]} for r in revisions],
        "received_at": o.received_at, "feedback": o.feedback, "finished_at": o.finished_at,
        "delivery_url": ctx.delivery_url(o),
        "maker_state": maker_state(o) if o.started_at else "",
        "production": [{
            "id": m.id, "direction": m.direction, "kind": m.kind, "author": m.author, "text": m.text,
            "files": [_file_out(pfiles[i]) for i in (m.file_ids or []) if i in pfiles],
            "read_at": m.read_at, "relayed_at": m.relayed_at, "created_at": m.created_at,
        } for m in pmsgs],
        "created_at": o.created_at,
    }


@router.get("/conversations/{cid}")
def conversation(cid: int, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    c = _customer(db, cid)
    ctx = _ctx(request)
    msgs = list(db.scalars(select(Message).where(Message.customer_id == c.id).order_by(Message.created_at, Message.id)))
    fids = {m.file_id for m in msgs if m.file_id}
    files = {f.id: f for f in db.scalars(select(FileRecord).where(FileRecord.id.in_(fids)))} if fids else {}
    outbox = list(db.scalars(select(Outbox).where(
        Outbox.customer_id == c.id, Outbox.status.in_(("pending", "approved", "failed"))).order_by(Outbox.id)))
    run_ids = {ob.run_id for ob in outbox if ob.run_id}
    runs = {r.id: r for r in db.scalars(select(BotRun).where(BotRun.id.in_(run_ids)))} if run_ids else {}
    last_run = db.scalar(select(BotRun).where(BotRun.customer_id == c.id).order_by(BotRun.id.desc()).limit(1))
    order = _latest_order(db, c)
    rt = get_runtime(request.app)
    cfg = load_config(db)
    return {
        "customer": {"id": c.id, "name": service.display_name(c), "nickname": c.nickname, "channel": c.channel,
                     "source": c.source, "takeover": c.human_takeover, "note": c.note, "created_at": c.created_at},
        "window": service.window_info(db, c),
        "messages": [{
            "id": m.id, "direction": m.direction, "sender": m.sender, "kind": m.kind, "text": m.text,
            "file": _file_out(files[m.file_id]) if m.file_id in files else None,
            "card": m.asset or None,
            "image_url": f"/api/admin/intake/assets/{m.asset}" if m.kind == "image" and m.asset in service.ASSETS else None,
            "created_at": m.created_at,
        } for m in msgs],
        "outbox": [{
            "id": ob.id, "status": ob.status, "status_label": OUTBOX_STATUS_LABELS.get(ob.status, ob.status),
            "kind": ob.kind, "asset": ob.asset, "text": ob.text, "original_text": ob.original_text,
            "category": ob.category, "author": ob.author, "auto": ob.auto, "reasons": ob.reasons, "error": ob.error,
            "created_at": ob.created_at, "run": _run_brief(runs.get(ob.run_id)) if ob.run_id else None,
        } for ob in outbox],
        "order": _order_out(db, ctx, order) if order else None,
        "last_run": _run_brief(last_run),
        "bot_ready": rt.runner.model is not None,
        "base_skus": [{"sku": k, "name": pricing.sku_name(cfg, k), "price": pricing.fmt_money(pricing.sku_price(cfg, k))}
                      for k in pricing.base_skus(cfg)],
    }


class EditText(BaseModel):
    text: str | None = Field(default=None, max_length=4000)


@router.post("/outbox/{oid}/approve")
async def approve(oid: int, body: EditText, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    ob = db.get(Outbox, oid)
    if ob is None:
        raise HTTPException(404, detail="没有这条")
    try:
        service.approve_outbox(db, ob, text=body.text)
    except ValueError as e:
        raise HTTPException(409, detail=str(e)) from e
    db.commit()
    await _dispatch(request, oid)
    db.expire_all()
    ob = db.get(Outbox, oid)
    return {"id": ob.id, "status": ob.status, "error": ob.error}


@router.post("/outbox/{oid}/reject")
def reject(oid: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    ob = db.get(Outbox, oid)
    if ob is None:
        raise HTTPException(404, detail="没有这条")
    try:
        service.reject_outbox(db, ob)
    except ValueError as e:
        raise HTTPException(409, detail=str(e)) from e
    db.commit()
    return {"id": ob.id, "status": ob.status}


class TextIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


@router.post("/conversations/{cid}/messages")
async def edison_says(cid: int, body: TextIn, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    c = _customer(db, cid)
    order = _latest_order(db, c)
    ob = service.create_outbox(db, _ctx(request), c, order, text=body.text.strip(), category="一般回复",
                               author="edison", reasons=["你自己写的"], approved=True)
    db.commit()
    await _dispatch(request, ob.id)
    db.expire_all()
    ob = db.get(Outbox, ob.id)
    return {"id": ob.id, "status": ob.status, "error": ob.error}


class TakeoverIn(BaseModel):
    on: bool


@router.post("/conversations/{cid}/takeover")
async def takeover(cid: int, body: TakeoverIn, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    """「我来接」只停助手，你在后台打字由接口发出去；不再把微信会话转成人工（转了接口就发不了消息，主窗口裁决 K3）。"""
    c = _customer(db, cid)
    service.set_takeover(db, _ctx(request), c, body.on)
    db.commit()
    return {"takeover": c.human_takeover, "note": ""}


class ManualOrderIn(BaseModel):
    sku: str = Field(min_length=1, max_length=48)
    addons: list[str] = Field(default_factory=list)
    why: str = Field(default="", max_length=200)


@router.post("/conversations/{cid}/manual-order")
def manual_order(cid: int, body: ManualOrderIn, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    """给这个会话手动开一单（先做后付、熟人）：不收码，platform=manual，直接到已认领。"""
    c = _customer(db, cid)
    try:
        o = orders.create_manual_order(db, _ctx(request), c, body.sku, body.addons, by="edison", why=body.why)
    except ValueError as e:
        raise HTTPException(409, detail=str(e)) from e
    db.commit()
    return _order_out(db, _ctx(request), o)


class CustomerPatch(BaseModel):
    nickname: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=4000)


@router.patch("/conversations/{cid}")
def patch_customer(cid: int, body: CustomerPatch, db: Session = Depends(get_db)) -> dict[str, Any]:
    c = _customer(db, cid)
    if body.nickname is not None:
        c.nickname = body.nickname.strip()
    if body.note is not None:
        c.note = body.note
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- 订单

class OrderPatch(BaseModel):
    occasion: str | None = None
    title: str | None = Field(default=None, max_length=256)
    duration_min: int | None = Field(default=None, ge=1, le=240)
    clear_duration: bool = False
    duration_confirmed: bool | None = None
    present_date: date | None = None
    clear_present_date: bool = False
    school: str | None = Field(default=None, max_length=64)
    language: str | None = Field(default=None, max_length=16)
    structure_req: str | None = None
    requirement_quotes: list[str] | None = None
    paper_count: int | None = Field(default=None, ge=1, le=50)
    page_count: int | None = Field(default=None, ge=1, le=500)


@router.patch("/orders/{oid}")
def patch_order(oid: int, body: OrderPatch, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    o = _order(db, oid)
    ch: dict[str, Any] = {}
    data = body.model_dump(exclude_unset=True)
    if "occasion" in data and data["occasion"]:
        if data["occasion"] not in load_config(db).occasions:
            raise HTTPException(400, detail="没有这个场合")
        ch["occasion"] = data["occasion"]
    for k in ("title", "school", "language", "structure_req", "requirement_quotes", "paper_count", "page_count"):
        if k in data and data[k] is not None:
            ch[k] = data[k]
    if data.get("duration_min") is not None:
        ch.update(duration_min=data["duration_min"], duration_default=False, duration_confirmed=False)
    if data.get("clear_duration"):
        ch.update(duration_min=None, duration_default=False, duration_confirmed=False)
    if data.get("duration_confirmed") is not None:
        ch["duration_confirmed"] = data["duration_confirmed"]
    if data.get("present_date") is not None:
        ch["present_date"] = data["present_date"]
    if data.get("clear_present_date"):
        ch["present_date"] = None
    service.update_order(db, _ctx(request), o, ch)
    db.commit()
    return _order_out(db, _ctx(request), o)


class FlagIn(BaseModel):
    flag: Literal["rush"]
    value: bool = True


@router.post("/orders/{oid}/flags")
async def set_flag(oid: int, body: FlagIn, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    """后台给加急 / 收回后台给的加急（「先做后付」改成手动开单了）。"""
    o = _order(db, oid)
    service.set_rush(db, _ctx(request), o, body.value)
    db.commit()
    await _dispatch(request)
    return _order_out(db, _ctx(request), o)


class PushIn(BaseModel):
    on: str = Field(min_length=1, max_length=32)
    why: str = Field(default="", max_length=200)


@router.post("/orders/{oid}/push")
async def push(oid: int, body: PushIn, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    """按流程里标了 manual 的连线手动推一步；不合法的 409。"""
    o = _order(db, oid)
    try:
        if body.on == "start_now":
            service.start_now(db, _ctx(request), o)
        else:
            flow.push(db, _ctx(request), o, body.on, by="edison", why=body.why or "后台手动推")
    except (StageError, ValueError) as e:
        db.rollback()
        raise HTTPException(409, detail=str(e)) from e
    except OSError as e:
        db.rollback()
        raise HTTPException(500, detail=f"写工厂 inbox 失败：{e}") from e
    db.commit()
    await _dispatch(request)
    db.expire_all()
    return _order_out(db, _ctx(request), _order(db, oid))


class VoidIn(BaseModel):
    code_action: Literal["return", "void"]
    why: str = Field(default="", max_length=200)


@router.post("/orders/{oid}/void")
def void(oid: int, body: VoidIn, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    """作废：return 撤单（码退回还能用，只许开工前）/ void 退款（码作废）。已完成之后 409。"""
    o = _order(db, oid)
    res = run_node("order.void", NodeCall(db, _ctx(request), "edison", o.id),
                   {"order_id": o.id, "code_action": body.code_action, "why": body.why or "后台作废"})
    if res.exit != "ok":
        db.rollback()
        raise HTTPException(409, detail=res.detail)
    db.commit()
    return _order_out(db, _ctx(request), o)


@router.post("/orders/{oid}/needs/{idx}/resolve")
def resolve_need(oid: int, idx: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    o = _order(db, oid)
    service.resolve_need(db, o, idx)
    db.commit()
    return {"ok": True}


class PurposeIn(BaseModel):
    purpose: str


@router.post("/orders/{oid}/files/{fid}/purpose")
def set_purpose(oid: int, fid: int, body: PurposeIn, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    o = _order(db, oid)
    f = db.get(FileRecord, fid)
    if f is None or f.order_id != o.id:
        raise HTTPException(404, detail="没有这个文件")
    if body.purpose not in MATERIAL_PURPOSES:
        raise HTTPException(400, detail="用途不对")
    f.purpose = body.purpose
    service.refresh_status(db, _ctx(request), o)
    db.commit()
    return _order_out(db, _ctx(request), o)


@router.post("/orders/{oid}/start-now")
async def start_now(oid: int, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    o = _order(db, oid)
    try:
        service.start_now(db, _ctx(request), o)
    except ValueError as e:
        raise HTTPException(409, detail=str(e)) from e
    except OSError as e:
        raise HTTPException(500, detail=f"写工厂 inbox 失败：{e}") from e
    db.commit()
    return _order_out(db, _ctx(request), o)


@router.post("/orders/{oid}/deliverables")
async def upload_deliverable(oid: int, request: Request, file: UploadFile = File(...), kind: str = Form("PPT"),
                             db: Session = Depends(get_db)) -> dict[str, Any]:
    o = _order(db, oid)
    if kind not in (*DELIVERABLE_KINDS, PAGE_KIND):
        raise HTTPException(400, detail="成品类型不对")
    data = await file.read()
    if not data:
        raise HTTPException(400, detail="文件是空的")
    page_no = None
    if kind == PAGE_KIND:
        import re as _re

        m = _re.search(r"(\d+)(?!.*\d)", Path(file.filename or "").stem)
        page_no = int(m.group(1)) if m else len(service.round_files(db, o, o.delivery_round + 1, role="page")) + 1
        from app.intake.watermark import WatermarkError, check_page

        try:
            check_page(data)
        except WatermarkError as e:
            raise HTTPException(400, detail=str(e)) from e
    service.add_deliverable(db, _ctx(request), o, filename=Path(file.filename or "成品").name, data=data, kind=kind,
                            content_type=file.content_type or "", page_no=page_no)
    db.commit()
    return _order_out(db, _ctx(request), o)


class FactoryPick(BaseModel):
    job: str
    filename: str
    kind: str = "PPT"


def _jobs_dir(request: Request) -> Path:
    return Path(_ctx(request).settings.FACTORY_JOBS)


PULL_NO_JOBS = "现在是 pull 模式（网站在服务器上），服务器看不到 Mac 上的工厂 jobs，用「上传成品」"


@router.get("/factory-jobs")
def factory_jobs(request: Request) -> list[dict[str, Any]]:
    """工厂 jobs/<单>/成品/ 里的文件（只读）。最近改过的 30 单。pull 模式下服务器看不到 Mac 的 jobs，返回空。"""
    if _ctx(request).settings.HANDOFF_MODE == "pull":
        return []
    root = _jobs_dir(request)
    if not root.is_dir():
        return []
    jobs = [p for p in root.iterdir() if p.is_dir() and (p / "成品").is_dir() and not p.name.startswith("_")]
    jobs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    out = []
    for j in jobs[:30]:
        files = [f for f in sorted((j / "成品").iterdir()) if f.is_file() and f.suffix.lower() in (".pptx", ".docx", ".pdf", ".zip", ".md")]
        if files:
            out.append({"job": j.name, "files": [{"name": f.name, "size": f.stat().st_size} for f in files]})
    return out


@router.post("/orders/{oid}/deliverables/from-factory")
def deliverable_from_factory(oid: int, body: FactoryPick, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    o = _order(db, oid)
    if _ctx(request).settings.HANDOFF_MODE == "pull":
        raise HTTPException(409, detail=PULL_NO_JOBS)
    root = _jobs_dir(request).resolve()
    src = (root / body.job / "成品" / body.filename).resolve()
    if root not in src.parents or not src.is_file():
        raise HTTPException(404, detail="工厂里没有这个文件")
    if body.kind not in DELIVERABLE_KINDS:
        raise HTTPException(400, detail="成品类型不对")
    service.add_deliverable(db, _ctx(request), o, filename=src.name, data=src.read_bytes(), kind=body.kind)
    db.commit()
    return _order_out(db, _ctx(request), o)


@router.post("/orders/{oid}/deliver")
async def deliver(oid: int, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    """交这一版（deliver.receive）：传好的最终版 + 整页图 → 出水印图、发布给客户看；已完成之后交的直接放最终版。"""
    o = _order(db, oid)
    res = run_node("deliver.receive", NodeCall(db, _ctx(request), "edison", o.id), {"order_id": o.id, "note": "后台交的"})
    if res.exit != "ok":
        db.rollback()
        raise HTTPException(409, detail=res.detail)
    db.commit()
    await _dispatch(request)
    db.expire_all()
    return _order_out(db, _ctx(request), _order(db, oid))


@router.post("/orders/{oid}/discard-unpublished")
def discard_unpublished(oid: int, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    """作废这一版还没发布的文件（传错了、要整版重传）：已经发布、放出的版次不动。"""
    o = _order(db, oid)
    names = service.discard_unpublished(db, _ctx(request), o, by="edison", why="后台作废这一版没交的文件")
    if not names:
        raise HTTPException(409, detail="这一版没有还没交的文件")
    db.commit()
    return _order_out(db, _ctx(request), o)


@router.post("/orders/{oid}/cancel")
def cancel(oid: int, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    """旧接口：= 作废、码退回（开工前）。"""
    return void(oid, VoidIn(code_action="return", why="后台取消"), request, db)


@router.post("/orders/{oid}/confirm")
async def confirm(oid: int, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    """平台那边已完成（你在平台后台看到确认收货）：confirm.receipt(source=edison)。"""
    o = _order(db, oid)
    res = run_node("confirm.receipt", NodeCall(db, _ctx(request), "edison", o.id), {"order_id": o.id, "source": "edison"})
    if res.exit not in ("completed", "recorded"):
        db.rollback()
        raise HTTPException(409, detail=res.detail or "这单现在不能确认收货")
    db.commit()
    await _dispatch(request)
    db.expire_all()
    return _order_out(db, _ctx(request), _order(db, oid))


@router.post("/orders/{oid}/release-final")
async def release_final(oid: int, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    """发最终版（gate.final）：只有已完成能发。"""
    o = _order(db, oid)
    res = run_node("gate.final", NodeCall(db, _ctx(request), "edison", o.id), {"order_id": o.id})
    if res.exit == "fail":
        db.rollback()
        raise HTTPException(409, detail=res.detail)
    db.commit()
    await _dispatch(request)
    db.expire_all()
    return _order_out(db, _ctx(request), _order(db, oid))


@router.get("/orders")
def orders_list(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    out = []
    cfg = load_config(db)
    for o in db.scalars(select(Order).order_by(Order.updated_at.desc()).limit(300)):
        c = db.get(Customer, o.customer_id) if o.customer_id else None
        if c is not None and not o.flow_step:
            has_msgs = db.scalar(select(func.count()).select_from(Message).where(Message.customer_id == c.id)) or 0
            if not has_msgs:
                continue
        out.append({
            "id": o.id, "customer_id": c.id if c else None,
            "name": service.display_name(c) if c else f"{o.platform or '平台'}单 {o.platform_order_id or ''}".strip(),
            "channel": c.channel if c else "", "platform": o.platform,
            "status": o.stage, "status_label": _stage_label(o), "stage": o.stage, "progress": orders.progress(db, o, cfg),
            "occasion": o.occasion, "duration_min": o.duration_min, "present_date": o.present_date,
            "eta_date": o.eta_date, "start_date": o.start_date, "due_hours": o.due_hours,
            "quoted_price": o.quoted_price, "rush": o.rush, "redeemed": o.code_id is not None,
            "sku_name": pricing.sku_name(cfg, o.sku, orders.addon_keys(o)) if o.sku else "",
            "tier_name": cfg.tier(o.tier_key).name if cfg.tier(o.tier_key) else "",
            "maker_state": maker_state(o) if o.started_at else "",
            "hold_reason": o.hold_reason,
            "needs": len([n for n in (o.needs_edison or []) if not n.get("resolved")]),
            "pending": _pending_count(db, c.id) if c else 0,
            "has_new_deliverable": service.has_undelivered_deliverable(db, o),
            "updated_at": o.updated_at,
        })
    return out


@router.get("/files/{fid}")
def download(fid: int, request: Request, db: Session = Depends(get_db)) -> Response:
    f = db.get(FileRecord, fid)
    if f is None:
        raise HTTPException(404, detail="没有这个文件")
    data = _ctx(request).storage.read_bytes(f.storage_key)
    inline = (f.content_type or "").startswith("image/") or f.filename.lower().endswith(".pdf")
    disp = "inline" if inline else "attachment"
    return Response(data, media_type=f.content_type or "application/octet-stream",
                    headers={"Content-Disposition": f"{disp}; filename*=UTF-8''{quote(f.filename)}"})


@router.get("/assets/{name}")
def asset(name: Literal["pay_qr", "owner_qr", "service_qr"], request: Request, db: Session = Depends(get_db)) -> Response:
    p = service.asset_path(db, _ctx(request), name)
    if p is None:
        raise HTTPException(404, detail="还没放上来")
    return FileResponse(p)


# ---------------------------------------------------------------- 设置

@router.get("/settings")
def get_settings(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    ctx = _ctx(request)
    rt = get_runtime(request.app)
    ch = get_channels(request.app)
    s = ctx.settings
    cfg = load_config(db)
    return {
        "config": cfg.model_dump(mode="json"),
        "categories": list(REPLY_CATEGORIES),
        "purposes": list(MATERIAL_PURPOSES),
        "deliverable_kinds": [*DELIVERABLE_KINDS, PAGE_KIND],
        "price_hash": pricing.price_hash(cfg),
        "images": {name: service.asset_path(db, ctx, name) is not None for name in service.ASSETS},
        "payment_ready": cfg.payment.ready(),
        "production_token": bool(s.PRODUCTION_TOKEN.get_secret_value()),
        "wecom": {**wecom_configured(ch.core), "callback_path": "/api/channels/wecom/callback"},
        "model": {"configured": rt.runner.model is not None, "name": model_label(rt.runner.model)},
        "factory_inbox": str(s.FACTORY_INBOX),
        "handoff_mode": s.HANDOFF_MODE,
        "factory_pull_token": bool(s.FACTORY_PULL_TOKEN.get_secret_value()),
    }


class SettingsIn(BaseModel):
    config: BizConfig


def _lint_settings(cfg: BizConfig) -> list[str]:
    """对外文字保存前的检查：发货模板过红线词表（app/platforms/redline.py，只有这一份）；交付什么、注意事项、欢迎语、
    付款说明调模块 G 的 copy.lint（它登记了才调；没登记先跳过）。"""
    problems: list[str] = []
    try:
        from app.platforms import redline
    except ImportError:  # 红线词表还没有：只靠 check.py 的静态检查
        redline = None
    if redline is not None:
        for key, text in cfg.delivery_templates.items():
            for w in redline.find(text, "platform"):
                problems.append(f"发货模板「{key}」里有「{w}」：平台在罚导流，发货内容只放激活码和兑换网址（看契约第六节、app/platforms/redline.py）")
    if has_node("copy.lint"):
        for field, profile in (("deliver_text", "platform_dy"), ("notes_text", "platform_dy"), ("welcome_text", "site")):
            res = run_node("copy.lint", NodeCall(None, None, "edison"), {"text": getattr(cfg, field), "profile": profile})
            problems += [f"{field}：{p}" for p in (getattr(res.output, "problems", None) or [])]
    return problems


@router.put("/settings")
def put_settings(body: SettingsIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    if not body.config.occasions:
        raise HTTPException(400, detail="至少留一个场合")
    if body.config.daily_quota < 1:
        raise HTTPException(400, detail="每天名额至少 1")
    if not body.config.duration_tiers or not body.config.paper_bands:
        raise HTTPException(400, detail="至少留一个时长档、一个篇数档")
    qr = body.config.payment.qr_image.strip()
    if qr and not Path(qr).is_file():
        raise HTTPException(400, detail=f"付款二维码图片找不到：{qr}")
    problems = _lint_settings(body.config)
    if problems:
        raise HTTPException(422, detail={"message": "对外文字没过检查", "problems": problems})
    before = load_config(db)
    save_config(db, body.config)
    changed = sorted(k for k, v in body.config.model_dump().items() if before.model_dump().get(k) != v and k != "schema_version")
    record_event(db, "admin.settings_saved", "", {"config": body.config.model_dump(mode="json")})
    record_event(db, "intake.config_changed", "", {"price_hash_before": pricing.price_hash(before),
                                                   "price_hash_after": pricing.price_hash(body.config),
                                                   "fields": changed, "by": "edison"})
    db.commit()
    return {"config": load_config(db).model_dump(mode="json")}


class SceneIn(BaseModel):
    scene: str = Field(min_length=1, max_length=32, pattern=r"^[0-9a-zA-Z_-]+$")


@router.post("/wecom/contact-way")
async def contact_way(body: SceneIn, request: Request) -> dict[str, Any]:
    ch = get_channels(request.app)
    if ch.wecom is None or not ch.open_kfid:
        raise HTTPException(503, detail="企业微信凭证还没配（WECOM_CORPID、WECOM_KF_SECRET、WECOM_OPEN_KFID）")
    try:
        url = await ch.wecom.add_contact_way(ch.open_kfid, body.scene)
    except WecomError as e:
        raise HTTPException(502, detail=f"企业微信返回：{e.errmsg}") from e
    return {"url": url, "scene": body.scene}


@router.get("/events")
def events(subject: str | None = None, limit: int = 100, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    return [{"id": e.id, "type": e.type, "subject": e.subject, "content": e.content, "created_at": e.created_at}
            for e in list_events(db, subject=subject, limit=min(limit, 500))]
