"""交付页接口（挂在 /api/delivery）：`/d/<随机长令牌>` 那一页的后端。模块 E。

- 只有拿到链接的人能看；所有返回带 `X-Robots-Tag: noindex`。
- 客人能拿到哪些文件只看 orders.deliverables_for_customer（已完成之前只有水印版，已完成才有可编辑的 PPT 和讲稿；
  scripts/check.py 第 12 条拦别处自己查成品）。
- 水印版逐页看：`/proofs/{版}/{页}` 一页一张长边 1920 的 JPEG（整页、不给缩略图、不给打包下载、不给讲稿）。
- 提修改：逐页「这页要改」+ 整体意见（≤3 条）+ 截图 → revision.collect。
- 「确认收货」（自有渠道才有按钮；平台订单去平台点）→ confirm.receipt(customer) → gate.final 放出最终版。
- 最终版下载 `/final/{文件}`：每次都重新查订单是否已完成（checks.require_final_allowed），不靠前端藏按钮。
- 后台圈（出水印图队列、时限看门）在这里的 lifespan 登记到底座调度器（网站进程或 python -m app.worker 跑，全集群一个在跑）。
设计：docs/任务单/07_制作与交付_设计.md 第七节。
"""

from __future__ import annotations

import contextlib
import json
import re
from collections.abc import AsyncIterator
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import access
from app.core.db import utcnow
from app.core.deps import client_ip, get_db, get_write_db
from app.core.events import Event, record_event
from app.core.nodes import NodeCall, run_node
from app.delivery import nodes as _nodes  # noqa: F401 登记交付这一块的节点
from app.delivery import runtime, versions
from app.delivery.checks import CheckFailed, require_final_allowed, verify_proof
from app.delivery.tick import register as register_tick
from app.delivery.watermark import order_label
from app.intake import clock, orders, service
from app.intake.config_store import load_config
from app.intake.models import PREVIEW_KIND, STAGE_LABELS, Order
from app.intake.runtime import get_ctx, get_runtime
from app.intake.service import Ctx

router = APIRouter(dependencies=[Depends(access.by_token)])  # 交付令牌就是凭证（规矩 24）；子资源只在这单里找

TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{20,64}$")
NOINDEX = {"X-Robots-Tag": "noindex, nofollow"}

# 给客人看的五步（按订单状态）
STEPS = ("收资料", "制作中", "看水印版、提修改", "确认收货", "拿最终版")
STEP_OF = {"paid": 0, "claimed": 0, "collecting": 0, "making": 1, "watermarked": 2, "revising": 2, "completed": 3,
           "delivered": 4, "void": 0, "": 0}
PLATFORM_NAMES = {"xhs": "小红书", "dy": "抖音", "xy": "闲鱼"}


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    s = runtime.configure(getattr(app.state, "delivery_settings", None))
    if s.DELIVERY_WORKER:
        register_tick(app.state.scheduler, get_runtime(app), s)
    try:
        yield
    finally:
        runtime.reset()


# ---------------------------------------------------------------- 返回结构

class ProofPageOut(BaseModel):
    page: int
    url: str


class RoundOut(BaseModel):
    round: int
    published_at: datetime | None
    pages: list[ProofPageOut]


class RevisionState(BaseModel):
    can_submit: bool
    revisions_left: int
    revision_used: int
    open: bool  # 上一轮还在改
    page_count: int
    based_on_round: int
    whole_items_max: int
    file_max_mb: int
    after_delivery: bool  # 已交付后用剩下的那轮
    hint: str


class ReceiptState(BaseModel):
    mode: Literal["button", "platform", "none"]  # button 自己点确认收货 | platform 去下单的平台点 | none 还不到时候
    hint: str
    platform_name: str
    auto_confirm_at: datetime | None
    auto_confirm_text: str
    confirmed: bool


class FinalFileOut(BaseModel):
    id: int
    name: str
    kind: str
    size: int
    url: str


class FinalState(BaseModel):
    released: bool
    waiting: bool  # 已完成了，最终版还在传
    files: list[FinalFileOut]


class DeliveryOut(BaseModel):
    order_no: str
    occasion: str
    title: str
    duration_min: int | None
    present_date: date | None
    stage: str
    status: str
    step: int
    steps: list[str]
    queue_ahead: int | None
    eta_date: date | None
    due_text: str  # 制作中：预计几点前交第一版
    cancelled: bool
    on_hold: bool
    delivered: bool
    latest_round: int
    rounds: list[RoundOut]
    revision: RevisionState
    receipt: ReceiptState
    final: FinalState
    show_feedback: bool
    feedback_done: bool


class Ok(BaseModel):
    ok: bool = True
    message: str = ""


class RevisionResult(Ok):
    revision_id: int | None = None
    free: bool = True


class ConfirmResult(Ok):
    released: bool = False
    files: list[FinalFileOut] = Field(default_factory=list)


class ViewedIn(BaseModel):
    round: int = Field(ge=1, le=99)
    pages: int = Field(ge=0, le=500)


class FeedbackIn(BaseModel):
    satisfaction: Literal["满意", "一般", "不满意"]
    comment: str = Field(default="", max_length=4000)
    share_revised: bool = False


# ---------------------------------------------------------------- 取单、拼页面数据

def _order(db: Session, token: str) -> Order:
    if not TOKEN_RE.match(token):
        raise HTTPException(404, detail="这个链接不对")
    o = db.scalar(select(Order).where(Order.delivery_token == token))
    if o is None:
        raise HTTPException(404, detail="这个链接不对，或者已经失效了")
    return o


def _final_allowed(o: Order) -> bool:
    try:
        require_final_allowed(stage=o.stage, completed_at=o.completed_at or o.finished_at, voided=o.stage == "void",
                              flow_step=o.flow_step)
    except CheckFailed:
        return False
    return o.finished_at is not None


def _final_files(db: Session, o: Order, token: str) -> list[FinalFileOut]:
    if not _final_allowed(o):
        return []
    rank = {"PPT": 0, "讲稿": 1, "PDF": 2}
    files = [f for f in orders.deliverables_for_customer(db, o) if f.purpose != PREVIEW_KIND]
    top = max((f.round for f in files), default=0)
    files = [f for f in files if f.round == top]  # 交付后又改过：只列最新那一版的最终版
    files.sort(key=lambda f: (rank.get(f.purpose, 9), f.filename))
    return [FinalFileOut(id=f.id, name=f.filename, kind=f.purpose or "其他", size=f.size, url=f"/api/delivery/{token}/final/{f.id}")
            for f in files]


def _receipt(db: Session, o: Order) -> ReceiptState:
    cfg = load_config(db)
    srcs = cfg.delivery.sources(o.platform or "legacy")
    name = PLATFORM_NAMES.get(o.platform, "下单的平台")
    confirmed = o.completed_at is not None
    if o.stage not in ("watermarked", "revising") or o.hold_reason:
        return ReceiptState(mode="none", hint="", platform_name=name, auto_confirm_at=None, auto_confirm_text="", confirmed=confirmed)
    if "customer" in srcs:
        at = versions.auto_confirm_at(db, o) if "auto" in srcs else None
        auto = f"{versions.fmt_when(at)}前没提修改、也没确认，会自动确认收货。" if at else ""
        return ReceiptState(mode="button", hint="没问题就点「确认收货」，确认后马上在这个页面放出可编辑的 PPT 和讲稿。",
                            platform_name=name, auto_confirm_at=at, auto_confirm_text=auto, confirmed=confirmed)
    return ReceiptState(mode="platform", platform_name=name, auto_confirm_at=None, auto_confirm_text="", confirmed=confirmed,
                        hint=f"满意的话到{name}订单里点「确认收货」，平台确认后这个页面会放出可编辑的 PPT 和讲稿。")


def _revision(db: Session, o: Order) -> RevisionState:
    cfg = load_config(db)
    s = versions.settings()
    left = service.revisions_left(o, cfg)
    is_open = service.open_revision(db, o) is not None
    after = o.stage == "delivered"
    in_window = True
    if after and o.finished_at is not None:
        in_window = utcnow() - o.finished_at <= timedelta(days=getattr(cfg, "revise_after_days", 7))
    can = (o.stage == "watermarked" or (after and in_window)) and left > 0 and not is_open and not o.hold_reason
    if is_open:
        hint = "修改意见收到了，改好的一版还会在这一页看。"
    elif o.stage not in ("watermarked", "delivered"):
        hint = ""
    elif left <= 0:
        hint = "修改轮数用完了。还想改的话，买一个「再改一轮」的码发给助手。"
    elif after and not in_window:
        hint = ""
    elif after:
        hint = f"还剩 {left} 轮修改：哪一页、改成什么，一次写全，改好了直接放新的可编辑版。"
    else:
        hint = f"含 {left} 轮修改：要改的地方在每页下面点「这页要改」，一次写全；提交后这一轮就用掉了。"
    return RevisionState(can_submit=can, revisions_left=max(left, 0), revision_used=o.revision_used or 0, open=is_open,
                         page_count=versions.page_count_of(db, o), based_on_round=o.delivery_round,
                         whole_items_max=s.DELIVERY_WHOLE_ITEMS_MAX, file_max_mb=s.DELIVERY_REVISION_FILE_MAX_MB,
                         after_delivery=after, hint=hint)


def _due_text(o: Order) -> str:
    if o.stage == "making" and o.started_at and o.due_hours:
        return f"开工了，预计 {versions.fmt_when(o.started_at + timedelta(hours=o.due_hours))}前交第一版水印版。"
    return ""


def _view(db: Session, o: Order, token: str) -> DeliveryOut:
    ahead = None
    if o.stage == "collecting" and o.queued_at and not o.started_at:
        ahead = db.scalar(select(func.count()).select_from(Order).where(
            Order.stage == "collecting", Order.queued_at.is_not(None), Order.started_at.is_(None),
            Order.queued_at < o.queued_at)) or 0
    rounds = [RoundOut(round=r.round, published_at=r.published_at,
                       pages=[ProofPageOut(page=p.page, url=f"/api/delivery/{token}/proofs/{r.round}/{p.page}") for p in r.pages])
              for r in versions.proof_rounds(db, o)]
    finals = _final_files(db, o, token)
    released = bool(finals) and o.finished_at is not None
    return DeliveryOut(
        order_no=order_label(o.id), occasion=o.occasion, title=o.title, duration_min=o.duration_min, present_date=o.present_date,
        stage=o.stage, status=STAGE_LABELS.get(o.stage, o.stage), step=STEP_OF.get(o.stage, 0), steps=list(STEPS),
        queue_ahead=ahead, eta_date=o.eta_date, due_text=_due_text(o), cancelled=o.stage == "void", on_hold=bool(o.hold_reason),
        delivered=o.delivered_at is not None, latest_round=o.delivery_round, rounds=rounds, revision=_revision(db, o),
        receipt=_receipt(db, o),
        final=FinalState(released=released, waiting=o.stage == "completed" and not released, files=finals),
        show_feedback=o.delivered_at is not None and o.present_date is not None and o.present_date <= clock.today(),
        feedback_done=o.feedback is not None,
    )


# ---------------------------------------------------------------- 接口

@router.get("/{token}", response_model=DeliveryOut)
def view(token: str, response: Response, db: Session = Depends(get_db)) -> DeliveryOut:
    response.headers.update(NOINDEX)
    o = _order(db, token)
    return _view(db, o, token)


@router.get("/{token}/proofs/{round_no}/{page}")
def proof(token: str, round_no: int, page: int, db: Session = Depends(get_db), ctx: Ctx = Depends(get_ctx)) -> Response:
    """一页水印图（只从客人能拿的水印版里找；已完成之后、作废之后都没有）。"""
    o = _order(db, token)
    if o.stage == "void":
        raise HTTPException(410, detail="这单作废了")
    r = next((x for x in versions.proof_rounds(db, o) if x.round == round_no), None)
    p = next((x for x in (r.pages if r else []) if x.page == page), None)
    if p is None:
        raise HTTPException(404, detail="没有这一页")
    f = next(x for x in orders.deliverables_for_customer(db, o) if x.id == p.file_id)
    data = ctx.storage.read_bytes(f.storage_key)
    try:
        verify_proof(data, long_min=versions.settings().WATERMARK_LONG_MIN)
    except CheckFailed as e:  # 不该发生：出图时已经验过。宁可不给，也不给带文字层的
        ctx.notifier.send(f"#{o.id} 第 {round_no} 版第 {page} 页水印图没过检查，没给客人看：{e.what}", link="/admin/orders", level="urgent", kind="出图失败", who=f"order:{o.id}")
        raise HTTPException(500, detail="这一页的预览图有问题，已经通知我们重出") from e
    return Response(data, media_type="image/jpeg", headers={
        **NOINDEX, "Cache-Control": "private, max-age=86400",
        "Content-Disposition": f"inline; filename*=UTF-8''{quote(f'第{round_no}版_第{page:02d}页_预览.jpg')}"})


@router.post("/{token}/viewed", response_model=Ok)
def viewed(token: str, body: ViewedIn, db: Session = Depends(get_db)) -> Ok:
    """客人看了几页（每版每天记一次，申诉举证用）。"""
    o = _order(db, token)
    today = clock.today().isoformat()
    rows = db.scalars(select(Event).where(Event.type == "delivery.proof_viewed", Event.subject == f"order:{o.id}"))
    if not any((e.content or {}).get("round") == body.round and (e.content or {}).get("day") == today for e in rows):
        record_event(db, "delivery.proof_viewed", f"order:{o.id}", {"round": body.round, "pages": body.pages, "day": today,
                                                                    "by": "customer"})
        db.commit()
    return Ok()


def _parse_items(raw: str) -> list[dict]:
    if not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except ValueError as e:
        raise HTTPException(400, detail="修改意见的格式不对") from e
    if not isinstance(data, list):
        raise HTTPException(400, detail="修改意见的格式不对")
    out = []
    for x in data[:60]:
        if not isinstance(x, dict):
            continue
        page = x.get("page")
        out.append({"page": int(page) if isinstance(page, (int, str)) and str(page).isdigit() else None,
                    "text": str(x.get("text", ""))[:2000], "files": [int(i) for i in x.get("files", []) if str(i).isdigit()][:10]})
    return out


@router.post("/{token}/revision", response_model=RevisionResult)
async def revision(
    token: str,
    items: str = Form(default="", max_length=200_000),
    text: str = Form(default="", max_length=8000),
    based_on_round: int | None = Form(default=None),
    files: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
    ctx: Ctx = Depends(get_ctx),
) -> RevisionResult:
    """逐页提修改：items = [{page, text, files: [下标]}]（page 空 = 整体意见）；只给一段话也行（text）。"""
    o = _order(db, token)
    if o.delivered_at is None:
        raise HTTPException(400, detail="还没交水印版，等发给你以后再提")
    s = versions.settings()
    limit = s.DELIVERY_REVISION_FILE_MAX_MB * 1024 * 1024
    got = []
    for up in files[:10]:
        data = await up.read()
        if len(data) > limit:
            raise HTTPException(413, detail=f"单个文件不超过 {s.DELIVERY_REVISION_FILE_MAX_MB}MB")
        if data:
            got.append({"name": Path(up.filename or "附件").name[:200], "data": data, "content_type": up.content_type or ""})
    res = run_node("revision.collect", NodeCall(db, ctx, "customer", o.id), {
        "order_id": o.id, "items": _parse_items(items), "text": text.strip(), "files": got, "based_on_round": based_on_round,
        "source": "delivery"})
    if res.exit == "fail":
        db.rollback()
        raise HTTPException(409, detail=res.detail)
    db.commit()
    out = res.output
    if res.exit == "ok":
        hours = load_config(db).delivery.revision_hours
        msg = (f"收到，改稿单交给做 PPT 的同事了，一般 {hours} 小时内交下一版，还是在这一页看。" if not out.duplicate
               else "这些意见已经提交过了，在改。")
    else:
        msg = "修改轮数用完了，这次的意见记下了。还想改的话，买一个「再改一轮」的码发给助手。"
    return RevisionResult(message=msg, revision_id=out.revision_id, free=out.free)


@router.post("/{token}/received", response_model=ConfirmResult)
def received(token: str, request: Request, db: Session = Depends(get_db), ctx: Ctx = Depends(get_ctx)) -> ConfirmResult:
    """确认收货（confirm.receipt，source=customer）：自有渠道才算；成了同一请求里放出最终版。"""
    o = _order(db, token)
    if o.delivered_at is None:
        raise HTTPException(400, detail="还没交水印版")
    ev = {"ip": client_ip(request), "ua": request.headers.get("user-agent", "")[:200], "round": o.delivery_round}
    res = run_node("confirm.receipt", NodeCall(db, ctx, "customer", o.id), {"order_id": o.id, "source": "customer", "evidence": ev})
    if res.exit != "completed":
        db.rollback()
        raise HTTPException(409, detail=res.detail or "这单现在不能在这里确认收货")
    db.commit()
    db.refresh(o)
    files = _final_files(db, o, token)
    if o.stage == "delivered" and files:
        return ConfirmResult(message="确认收货啦，可编辑的 PPT 和讲稿在下面下载。", released=True, files=files)
    return ConfirmResult(message="确认收货啦，可编辑的 PPT 和讲稿马上传上来，传好会发给你，也会放在这一页。")


@router.post("/{token}/platform-confirmed", response_model=Ok)
def platform_confirmed(token: str, db: Session = Depends(get_db), ctx: Ctx = Depends(get_ctx)) -> Ok:
    """平台单客人说「我已经在平台点了确认收货」：只通知负责人去核对（6 小时内只通知一次），订单不动。"""
    o = _order(db, token)
    if _receipt(db, o).mode != "platform":
        raise HTTPException(409, detail="这单不用去平台确认")
    since = utcnow() - timedelta(hours=6)
    recent = db.scalar(select(func.count()).select_from(Event).where(
        Event.type == "delivery.platform_claimed", Event.subject == f"order:{o.id}", Event.created_at >= since))
    name = PLATFORM_NAMES.get(o.platform, "平台")
    if not recent:
        record_event(db, "delivery.platform_claimed", f"order:{o.id}", {"platform": o.platform, "round": o.delivery_round, "by": "customer"})
        ctx.notifier.send(f"#{o.id}（{name}单）客人说已经在{name}点了确认收货：去{name}卖家后台核对，是真的就在后台点「平台已确认收货」放最终版", link="/admin/orders", level="urgent", kind="平台确认收货待核对", who=f"order:{o.id}")
        db.commit()
    return Ok(message=f"收到，我们核对{name}的订单后就放出可编辑的 PPT 和讲稿（一般半天内）。")


@router.get("/{token}/final/{file_id}")
def final_download(token: str, file_id: int, db: Session = Depends(get_write_db), ctx: Ctx = Depends(get_ctx)) -> Response:
    """下载最终版：每次都重新查订单是否已完成（不靠前端藏按钮）；只给 deliverables_for_customer 里的最终版。"""
    o = _order(db, token)
    try:
        require_final_allowed(stage=o.stage, completed_at=o.completed_at or o.finished_at, voided=o.stage == "void",
                              flow_step=o.flow_step)
    except CheckFailed as e:
        raise HTTPException(403, detail=f"确认收货后才能下载可编辑的 PPT 和讲稿（{e.what}）") from e
    f = next((x for x in orders.deliverables_for_customer(db, o) if x.id == file_id and x.purpose != PREVIEW_KIND), None)
    if f is None:
        raise HTTPException(404, detail="没有这个文件")
    data = ctx.storage.read_bytes(f.storage_key)
    record_event(db, "delivery.final_downloaded", f"order:{o.id}", {"file": f.id, "name": f.filename, "by": "customer"})
    db.commit()
    return Response(data, media_type=f.content_type or "application/octet-stream", headers={
        **NOINDEX, "Content-Disposition": f"attachment; filename*=UTF-8''{quote(f.filename)}"})


@router.post("/{token}/feedback", response_model=Ok)
def feedback(token: str, body: FeedbackIn, db: Session = Depends(get_db), ctx: Ctx = Depends(get_ctx)) -> Ok:
    o = _order(db, token)
    if o.delivered_at is None:
        raise HTTPException(400, detail="还没交付")
    service.submit_feedback(db, ctx, o, body.model_dump())
    db.commit()
    return Ok(message="谢谢你的反馈")

