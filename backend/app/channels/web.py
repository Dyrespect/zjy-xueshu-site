"""网页聊天（entry.webchat 的入站）：给不用微信的人，也是试机器人的地方。跟微信客服同一个大脑（intake）。

不用登录：第一次打开时后端发一个随机长 key，浏览器存着；`/chat/<key>` 这个地址就是回来的路
（页面上提醒客户记下）。key 就是凭证，只能看到自己的对话和自己的文件。
客人发的每一句、每个文件先翻成 InboundMessage 交给 entry.route 分流：有码就认领、没认领只问答（每天有上限）、
没认领不收文件（上传前先问，409 + 固定话术，不写存储）。
"""

from __future__ import annotations

import re
import secrets
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import access
from app.channels import limits, mailer
from app.channels.entry_config import load_entry_config
from app.channels.entry_types import InboundMessage
from app.channels.models import Contact
from app.channels.runtime import ChannelsRuntime, channels_dep
from app.core.db import utcnow
from app.core.deps import client_ip, get_db, get_ratelimiter
from app.core.nodes import NodeCall, run_node
from app.intake import brief, flow, service
from app.intake.config_store import load_config
from app.intake.models import STAGE_LABELS, Customer, FileRecord, Message, Order, Outbox
from app.intake.reception import kb as rkb

router = APIRouter(prefix="/web", tags=["channels"], dependencies=[Depends(access.by_token)])  # 聊天 key 就是凭证

KEY_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
ALLOWED_EXT = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".png", ".jpg", ".jpeg", ".webp", ".xls", ".xlsx",
               ".csv", ".txt", ".md", ".zip", ".rar", ".7z"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
SESSION_LIMIT_PER_HOUR = 30


class SessionOut(BaseModel):
    key: str


class WebFile(BaseModel):
    id: int
    name: str
    size: int
    url: str


class WebMessage(BaseModel):
    id: int
    sender: Literal["me", "bot", "edison"]
    kind: str
    text: str
    # 固定内容的样子：terms 交付什么 + 注意事项；payment 付款方式；owner_qr 负责人微信二维码；pay_qr 付款二维码
    card: str | None = None
    file: WebFile | None = None
    image_url: str | None = None
    created_at: datetime


class WebOrder(BaseModel):
    order_no: str
    sku_name: str
    stage: str
    stage_label: str


class WebBrief(BaseModel):
    """需求卡（09 需求引导）：这单的需求卡在哪、确认了没有。聊天页顶上一条。"""

    path: str
    confirmed: bool
    text: str


class WebChatOut(BaseModel):
    key: str
    welcome: str
    status: str
    delivery_path: str | None
    messages: list[WebMessage]
    order: WebOrder | None = None
    brief: WebBrief | None = None
    # 「我的订单」：配了邮件服务才开；这个人绑过邮箱就不再提示
    account_enabled: bool = False
    email_bound: bool = False
    # 接待机器人（docs/任务单/12_接待机器人_设计.md）：顶上一直挂着的「回复由 AI 生成」；小鱼正在打字（有排了时间、还没到点的回复）
    notice: str = ""
    typing: bool = False


class TextIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


def _customer(db: Session, key: str) -> Customer:
    if not KEY_RE.match(key):
        raise HTTPException(404, detail="这个聊天地址不对")
    c = db.scalar(select(Customer).where(Customer.channel == "web", Customer.external_id == key))
    if c is None:
        raise HTTPException(404, detail="这个聊天地址不对，或者已经失效了")
    return c


def _to_web(m: Message, key: str, files: dict[int, FileRecord]) -> WebMessage:
    sender: Literal["me", "bot", "edison"] = "me" if m.direction == "in" else ("edison" if m.sender == "edison" else "bot")
    f = files.get(m.file_id) if m.file_id else None
    wf = WebFile(id=f.id, name=f.filename, size=f.size, url=f"/api/channels/web/{key}/files/{f.id}") if f else None
    image_url = None
    if m.asset and m.kind == "image":
        image_url = f"/api/channels/web/{key}/assets/{m.asset}"
    elif f and m.kind == "image":
        image_url = wf.url if wf else None
    return WebMessage(id=m.id, sender=sender, kind=m.kind, text=m.text, card=m.asset or None, file=wf,
                      image_url=image_url, created_at=m.created_at)


def _messages(db: Session, customer: Customer) -> list[WebMessage]:
    msgs = list(db.scalars(select(Message).where(Message.customer_id == customer.id).order_by(Message.created_at, Message.id)))
    ids = {m.file_id for m in msgs if m.file_id}
    files = {f.id: f for f in db.scalars(select(FileRecord).where(FileRecord.id.in_(ids)))} if ids else {}
    return [_to_web(m, customer.external_id, files) for m in msgs]


@router.post("/sessions", response_model=SessionOut, dependencies=[Depends(access.public)])  # 开一个新会话
def new_session(request: Request, rt: ChannelsRuntime = Depends(channels_dep), db: Session = Depends(get_db)) -> SessionOut:
    if not get_ratelimiter(request).hit("channels.web_session", client_ip(request), limit=SESSION_LIMIT_PER_HOUR, window=3600):
        raise HTTPException(429, detail="开得太频繁了，过一会儿再试")
    key = secrets.token_urlsafe(24)
    service.get_or_create_customer(db, "web", key)
    db.commit()
    return SessionOut(key=key)


def node_call(db: Session, rt: ChannelsRuntime, by: str = "customer") -> NodeCall:
    flow.ensure_nodes()
    return NodeCall(db, rt.intake.ctx, by)


@router.get("/{key}", response_model=WebChatOut)
def chat(key: str, db: Session = Depends(get_db)) -> WebChatOut:
    from app.channels.texts import sku_name_of

    c = _customer(db, key)
    order = service.current_order(db, c)
    if order is None:
        order = db.scalar(select(Order).where(Order.customer_id == c.id).order_by(Order.id.desc()).limit(1))
    cfg = load_config(db)
    delivery = f"/d/{order.delivery_token}" if order is not None and order.delivered_at else None
    status = STAGE_LABELS.get(order.stage, "") if order is not None and order.flow_step else ""
    wo = WebOrder(order_no=f"{order.id:05d}", sku_name=sku_name_of(cfg, order), stage=order.stage,
                  stage_label=status) if order is not None and order.flow_step else None
    bound = c.person_id is not None and db.scalar(select(Contact.id).where(Contact.person_id == c.person_id).limit(1)) is not None
    wb = None
    if order is not None and order.flow_step and (brief.editable(order) or brief.confirmed(db, order)):
        ok = brief.confirmed(db, order)
        bs = brief.load_settings(db)
        wb = WebBrief(path=brief.brief_path(order), confirmed=ok, text=bs.text("chat_done" if ok else "chat_todo"))
    typing = db.scalar(select(Outbox.id).where(Outbox.customer_id == c.id, Outbox.status == "approved", Outbox.author == "bot",
                                               Outbox.send_after.is_not(None), Outbox.send_after > utcnow()).limit(1)) is not None
    return WebChatOut(key=key, welcome=cfg.welcome_text, status=status, delivery_path=delivery, messages=_messages(db, c),
                      order=wo, brief=wb, account_enabled=mailer.enabled(), email_bound=bool(bound),
                      notice=rkb.load(db).disclosure.web_footer, typing=typing)


@router.post("/{key}/messages", response_model=WebMessage)
def send_text(key: str, body: TextIn, request: Request, rt: ChannelsRuntime = Depends(channels_dep),
              db: Session = Depends(get_db)) -> WebMessage:
    c = _customer(db, key)
    ip = client_ip(request)
    lim = limits.limiter(request.app)
    ip_ok = lim.count("entry.web_visitor", ip, 86400) < load_entry_config(db).web_visitor_ip_daily
    im = InboundMessage(entry="entry.webchat", session_id=c.id, kind="text", text=body.text.strip(), ip=ip, ip_quota_ok=ip_ok)
    res = run_node("entry.route", node_call(db, rt), {"msg": im})
    db.commit()
    if res.exit == "visitor_qa":
        lim.add("entry.web_visitor", ip)  # 只数真花了模型钱的访客问答
    msg = db.get(Message, res.output.message_id) if res.output is not None and res.output.message_id else None
    if msg is None:
        raise HTTPException(409, detail="这句没收到，再发一次")
    return _to_web(msg, key, {})


@router.post("/{key}/files", response_model=WebMessage)
async def send_file(key: str, request: Request, file: UploadFile = File(...), rt: ChannelsRuntime = Depends(channels_dep),
                    db: Session = Depends(get_db)) -> WebMessage:
    c = _customer(db, key)
    name = Path(file.filename or "文件").name
    ext = Path(name).suffix.lower()
    kind = "image" if ext in IMAGE_EXT else "file"
    # 先问 entry.route（还没认领不收资料：主窗口 11-18 裁决 K1，入口设计卡 1 规则 7），放行了才读文件、才存
    im = InboundMessage(entry="entry.webchat", session_id=c.id, kind=kind, file_name=name, file_size=file.size,
                        ip=client_ip(request))
    res = run_node("entry.route", node_call(db, rt), {"msg": im})
    if res.output is None or not res.output.fetch_file:
        db.commit()  # 记下「拒收」这条事件
        raise HTTPException(409, detail=(res.output.reply_text if res.output is not None else "") or load_config(db).text("file_refused"))
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, detail="这种文件发不了：PDF、Word、PPT、Excel、图片、压缩包都可以")
    limit = rt.settings.WEB_UPLOAD_MAX_MB * 1024 * 1024
    data = bytearray()
    while chunk := await file.read(1024 * 1024):
        data.extend(chunk)
        if len(data) > limit:
            raise HTTPException(413, detail=f"文件太大了，单个不超过 {rt.settings.WEB_UPLOAD_MAX_MB}MB")
    if not data:
        raise HTTPException(400, detail="文件是空的")
    got = service.receive_file(db, rt.intake.ctx, c, filename=name, data=bytes(data),
                               content_type=file.content_type or "", kind=kind)
    db.commit()
    msg, rec = got
    return _to_web(msg, key, {rec.id: rec} if rec else {})


@router.get("/{key}/files/{file_id}")
def download(key: str, file_id: int, rt: ChannelsRuntime = Depends(channels_dep), db: Session = Depends(get_db)) -> Response:
    c = _customer(db, key)
    linked = db.scalar(select(Message).where(Message.customer_id == c.id, Message.file_id == file_id).limit(1))
    f = db.get(FileRecord, file_id)
    if linked is None or f is None:
        raise HTTPException(404, detail="没有这个文件")
    storage = rt.intake.ctx.storage
    data = storage.read_bytes(f.storage_key)
    return Response(data, media_type=f.content_type or "application/octet-stream",
                    headers={"Content-Disposition": _disposition(f.filename)})


@router.get("/{key}/assets/{asset}")
def asset(key: str, asset: Literal["pay_qr", "owner_qr"], rt: ChannelsRuntime = Depends(channels_dep),
          db: Session = Depends(get_db)) -> Response:
    """发给这个客户的固定图片（付款二维码、负责人微信二维码）：发过才能看。"""
    c = _customer(db, key)
    sent = db.scalar(select(Message).where(Message.customer_id == c.id, Message.asset == asset).limit(1))
    p = service.asset_path(db, rt.intake.ctx, asset)
    if sent is None or p is None:
        raise HTTPException(404, detail="图片还没放上来")
    return FileResponse(p)


def _disposition(name: str) -> str:
    from urllib.parse import quote

    return f"attachment; filename*=UTF-8''{quote(name)}"
