"""需求卡的客人页面接口（/api/channels/brief/*，docs/任务单/09_需求引导_方案.md）和「没确认提醒一次」。

- 地址 /b/{这单的交付令牌}：跟交付页同一个凭证（认领后才有、只在这单的聊天里发），网页、微信客服、小红书、闲鱼的单
  都是认领后从兑换页或聊天里点进来，同一张需求卡。
- 客人点选 → PUT 存；传旧材料、模板 → POST files（收进这单的资料，用途「参考」「模板」）；对着确认卡点「对，开工」→ POST confirm。
  事都在 app/intake/brief.py；这里只做接口、文件大小格式、给客人看的「接下来做什么」。
- 认领后（或负责人发回重确认后）2 小时没确认：走入口的固定话术节点 entry.notice + 这个人的入口节点发一次提醒（不自动开工），
  同时告诉负责人一声（客人在聊天里说「可以」的，负责人在后台代确认）。
- 这条链路不调模型（scripts/check.py 规矩 21）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import access
from app.channels import entries, inbound
from app.channels.redeem import web_session
from app.channels.runtime import ChannelsRuntime, channels_dep
from app.core.deps import client_ip, get_db
from app.core.nodes import NodeCall, NodeError, has_handler, run_node
from app.intake import brief, clock, flow, service
from app.intake.models import Customer, Order

router = APIRouter(prefix="/brief", tags=["channels"], dependencies=[Depends(access.by_token)])  # 交付令牌就是凭证

CONSENT_NODE = "website.consent"
ALLOWED_EXT = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".potx", ".png", ".jpg", ".jpeg", ".webp", ".zip", ".rar", ".7z", ".txt", ".md"}


class SaveIn(BaseModel):
    answers: dict[str, Any] = Field(default_factory=dict)


class ConfirmIn(BaseModel):
    version: int | None = None
    # 还没勾过同意的单（平台单），确认卡上要勾三项：协议和隐私、材料交给 AI 处理（含境外）、定制不退。
    # 后端没勾全不让确认（422）；勾了记进事件 website.consent（挂在订单上），跟确认同一个事务
    consents: list[str] = Field(default_factory=list, max_length=8)
    terms_version: str = Field(default="", max_length=32)
    privacy_version: str = Field(default="", max_length=32)


def _order(db: Session, token: str) -> Order:
    if not (16 <= len(token) <= 64) or not all(ch.isalnum() or ch in "-_" for ch in token):
        raise HTTPException(404, detail="这个地址不对")
    o = db.scalar(select(Order).where(Order.delivery_token == token))
    if o is None or o.customer_id is None:
        raise HTTPException(404, detail="这个地址不对，或者这单还没认领")
    return o


def _chat_path(db: Session, order: Order, web_key: str | None) -> str:
    """回聊天的地址只给这单主人的浏览器（请求带的聊天 key 是这个人的某个门），转发出去的链接拿不到聊天。"""
    me = web_session(db, web_key)
    if me is None or order.customer_id not in inbound._session_ids(db, me):
        return ""
    return f"/chat/{me.external_id}"


def _next(db: Session, rt: ChannelsRuntime, order: Order, chat_path: str) -> dict[str, str]:
    """确认以后给客人看的「接下来」：开工了没有、还差什么资料、去哪发。"""
    owner = db.get(Customer, order.customer_id) if order.customer_id else None
    where = "回到聊天发给助手" if (owner is not None and owner.channel == "web") or chat_path else "回到微信客服里发给助手"
    if order.started_at is not None:
        hours = order.due_hours
        return {"text": f"已经开工了{f'，{hours} 小时内先发你一版带水印的' if hours else ''}。", "where": where, "chat_path": chat_path}
    if order.queued_at and order.start_date:
        return {"text": f"资料齐了，排在 {clock.fmt_date(order.start_date)}开工。", "where": where, "chat_path": chat_path}
    collect = service.collect_for(db, order, rt.intake.ctx) if order.stage in ("claimed", "collecting") else None
    ask = collect.ask_text if collect is not None else ""
    return {"text": f"开工还差：{ask.removeprefix('还要：')}。" if ask else "资料齐了就排期开工。", "where": where,
            "chat_path": chat_path}


def _out(db: Session, rt: ChannelsRuntime, order: Order, web_key: str | None) -> dict[str, Any]:
    v = brief.view(db, rt.intake.ctx, order)
    chat = _chat_path(db, order, web_key)
    v["chat_path"] = chat
    v["next"] = _next(db, rt, order, chat)
    return v


def _call(db: Session, rt: ChannelsRuntime, by: str = "customer") -> NodeCall:
    flow.ensure_nodes()
    return NodeCall(db, rt.intake.ctx, by)


@router.get("/{token}")
def view(token: str, x_web_key: str | None = Header(default=None), rt: ChannelsRuntime = Depends(channels_dep),
         db: Session = Depends(get_db)) -> dict[str, Any]:
    return _out(db, rt, _order(db, token), x_web_key)


@router.put("/{token}")
def save(token: str, body: SaveIn, x_web_key: str | None = Header(default=None), rt: ChannelsRuntime = Depends(channels_dep),
         db: Session = Depends(get_db)) -> dict[str, Any]:
    o = _order(db, token)
    _call(db, rt)
    try:
        brief.save(db, rt.intake.ctx, o, body.answers, by="customer")
    except ValueError as e:
        db.rollback()
        raise HTTPException(409 if not brief.editable(o) else 400, detail=str(e)) from e
    db.commit()
    return _out(db, rt, o, x_web_key)


def _record_consent(call: NodeCall, order: Order, body: ConfirmIn, request: Request) -> str:
    """开工前客人本人勾的同意：交给 website.consent 校验和留痕。返回空 = 过了；否则是给客人看的原因。
    节点不在（官网模块没装）也不放过：没有同意记录不开工。"""
    if not has_handler(CONSENT_NODE):
        return "开工前的确认现在记不下来，过一会儿再点一次"
    try:
        r = run_node(CONSENT_NODE, call, {
            "order_id": order.id, "items": list(body.consents), "terms_version": body.terms_version,
            "privacy_version": body.privacy_version, "ip": client_ip(request)[:64],
            "ua": request.headers.get("user-agent", "")[:300]})
    except NodeError:  # 协议版本号这类格式不对
        return "开工前的确认信息不完整，刷新页面再勾一次"
    return "" if r.exit == "ok" else ((r.detail or "三项都勾上才能开工").replace("没勾全", "开工前还要勾上"))


@router.post("/{token}/confirm")
def confirm(token: str, body: ConfirmIn, request: Request, x_web_key: str | None = Header(default=None),
            rt: ChannelsRuntime = Depends(channels_dep), db: Session = Depends(get_db)) -> dict[str, Any]:
    o = _order(db, token)
    call = _call(db, rt)
    if brief.editable(o) and not brief.has_consent(db, o):
        why = _record_consent(call, o, body, request)
        if why:
            db.rollback()
            raise HTTPException(422, detail=why)
    try:
        brief.confirm(db, rt.intake.ctx, o, method="customer", by="customer", version=body.version)
    except ValueError as e:
        db.rollback()
        raise HTTPException(409, detail=str(e)) from e
    db.commit()
    db.expire_all()
    return _out(db, rt, _order(db, token), x_web_key)


@router.post("/{token}/files")
async def upload(token: str, kind: Literal["ref", "template"] = Form("ref"), file: UploadFile = File(...),
                 x_web_key: str | None = Header(default=None), rt: ChannelsRuntime = Depends(channels_dep),
                 db: Session = Depends(get_db)) -> dict[str, Any]:
    o = _order(db, token)
    name = Path(file.filename or "文件").name
    if Path(name).suffix.lower() not in ALLOWED_EXT:
        raise HTTPException(400, detail="这种文件传不了：PPT、PDF、Word、图片、压缩包都可以")
    limit = rt.settings.WEB_UPLOAD_MAX_MB * 1024 * 1024
    data = bytearray()
    while chunk := await file.read(1024 * 1024):
        data.extend(chunk)
        if len(data) > limit:
            raise HTTPException(413, detail=f"文件太大了，单个不超过 {rt.settings.WEB_UPLOAD_MAX_MB}MB")
    if not data:
        raise HTTPException(400, detail="文件是空的")
    _call(db, rt)
    try:
        brief.add_file(db, rt.intake.ctx, o, filename=name, data=bytes(data), content_type=file.content_type or "", kind=kind)
    except ValueError as e:
        db.rollback()
        raise HTTPException(409, detail=str(e)) from e
    db.commit()
    return _out(db, rt, o, x_web_key)


@router.delete("/{token}/files/{file_id}")
def remove(token: str, file_id: int, x_web_key: str | None = Header(default=None), rt: ChannelsRuntime = Depends(channels_dep),
           db: Session = Depends(get_db)) -> dict[str, Any]:
    o = _order(db, token)
    try:
        brief.remove_file(db, rt.intake.ctx, o, file_id)
    except LookupError as e:
        raise HTTPException(404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(409, detail=str(e)) from e
    db.commit()
    return _out(db, rt, o, x_web_key)


# ---------------------------------------------------------------- 给客人发话（提醒、负责人发回）

def notify(call: NodeCall, order: Order, template: Literal["brief_remind", "brief_sent_back"], *, note: str = "") -> bool:
    """走入口的固定话术节点拼话、这个人的入口节点发（微信窗口关着就进待发，客人再开口补发）。"""
    db = call.db
    c = db.get(Customer, order.customer_id) if order.customer_id else None
    spec = entries.spec_for(c.channel) if c is not None else None
    if c is None or spec is None:
        return False
    b = brief.ensure(db, order)
    msg = run_node("entry.notice", call, {
        "session_id": c.id, "template": template, "order_id": order.id, "purpose": "collect",
        "extra": {"brief_url": brief.brief_url(call.ctx, order), "note": f"（{note}）" if note else ""},
        "dedupe_key": f"{template}:{order.id}:{b.version}"}).output.message
    if not msg.text.strip():
        return False
    run_node(spec.node_id, call, msg)
    return True


def remind_tick(rt: ChannelsRuntime) -> list[int]:
    """认领后（或发回后）几小时没确认的单，提醒客人一次、告诉负责人一声；不自动开工。"""
    flow.ensure_nodes()
    sent: list[int] = []
    with rt.intake.database.session() as db:
        call = NodeCall(db, rt.intake.ctx, "system")
        for o in brief.due_reminders(db):
            ok = notify(call, o, "brief_remind")
            brief.mark_reminded(db, o)
            if ok:
                sent.append(o.id)
                c = db.get(Customer, o.customer_id) if o.customer_id else None
                hours = brief.load_settings(db).remind_after_hours
                rt.intake.ctx.notifier.send(
                    f"#{o.id} {service.display_name(c) if c else ''} 认领 {hours} 小时了还没确认需求卡，提醒了客人一次；"
                    "客人在聊天里说可以的，去后台订单卡上代确认", link="/admin/orders", level="digest", kind="需求卡没确认", who=f"order:{o.id}")
    return sent
