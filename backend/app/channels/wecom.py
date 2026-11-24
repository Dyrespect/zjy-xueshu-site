"""微信客服的收（entry.wecom 入站）：拉消息（cursor 存库）→ 翻成 InboundMessage → entry.route 分流。

回调里没有消息正文，只有 Token 和 OpenKfId（官方「接收消息」）；回调只入队（wecom_inbox.py），工人拿 Token 去 sync_msg 拉，
has_more 就接着拉。消息来源 origin：3 客户发的，4 系统推送（事件），5 接待人员在企业微信里发的。
- 进入会话事件（客人点客服链接进来）：scene_param 带码就认领；有欢迎语凭证（20 秒、1 条）就用它发认领结果 + 资料清单，
  凭证过了或没有（老客人）就排进待发，客人一开口先补发（发件员按 48 小时窗口发）。欢迎语全由代码拼，不调模型。
- 客人发文件：先问 entry.route，没认领就不下载（不调 media/get），放行了才取。
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.channels.entry_config import load_entry_config
from app.channels.entry_types import InboundMessage
from app.channels.models import WecomCursor
from app.channels.runtime import ChannelsRuntime
from app.channels.wecom_client import WecomError
from app.core.db import utcnow
from app.core.events import Event, record_event
from app.core.nodes import NodeCall, run_node
from app.intake import codes, service
from app.intake.models import Customer, Message, Outbox

log = logging.getLogger("app.channels.wecom")

FILE_TYPES = ("image", "file", "voice", "video")


def parse_xml(text: str) -> dict[str, str]:
    root = ET.fromstring(text)
    return {child.tag: (child.text or "") for child in root}


def get_cursor(db: Session, open_kfid: str) -> str:
    row = db.get(WecomCursor, open_kfid)
    return row.cursor if row else ""


def save_cursor(db: Session, open_kfid: str, cursor: str) -> None:
    row = db.get(WecomCursor, open_kfid)
    if row is None:
        db.add(WecomCursor(open_kfid=open_kfid, cursor=cursor, updated_at=utcnow()))
    else:
        row.cursor = cursor
        row.updated_at = utcnow()


async def sync_messages(rt: ChannelsRuntime, open_kfid: str, token: str = "") -> int:
    """拉到没有新消息为止，每页处理完就存一次 cursor（断点续拉）。返回处理了几条。"""
    if rt.wecom is None:
        return 0
    n = 0
    async with rt.lock_for(open_kfid):
        db_ = rt.intake.database
        with db_.session() as db:
            cursor = get_cursor(db, open_kfid)
        while True:
            data = await rt.wecom.sync_msg(open_kfid, cursor=cursor, token=token)
            for msg in data.get("msg_list", []):
                try:
                    await ingest(rt, msg)
                    n += 1
                except Exception:
                    log.exception("微信客服消息处理失败：%s", msg.get("msgid"))
                    with db_.session() as db:
                        record_event(db, "node.failed", "", {"node": "entry.route", "msgid": msg.get("msgid", ""),
                                                             "entry": "entry.wecom"})
                    rt.intake.ctx.notifier.send(f"微信客服有一条消息没处理成（{msg.get('msgtype', '')}），去后台会话看一下", link="/admin/conversations", level="urgent", kind="微信客服出错")
            cursor = data.get("next_cursor", cursor)
            with db_.session() as db:
                save_cursor(db, open_kfid, cursor)
            if not data.get("has_more"):
                break
    return n


async def _customer(rt: ChannelsRuntime, db: Session, external_userid: str, open_kfid: str, *, source: str = "") -> Customer:
    c = service.get_or_create_customer(db, "wecom", external_userid, open_kfid=open_kfid, source=source)
    if not c.nickname and rt.wecom is not None:
        try:
            names = await rt.wecom.customer_nicknames([external_userid])
            if names.get(external_userid):
                c.nickname = names[external_userid][:64]
        except WecomError as e:
            log.warning("拿客户昵称失败：%s", e)
    return c


def _send_time(msg: dict[str, Any]) -> datetime:
    ts = msg.get("send_time")
    return datetime.fromtimestamp(int(ts), tz=timezone.utc) if ts else utcnow()


def _call(rt: ChannelsRuntime, db: Session, by: str = "customer") -> NodeCall:
    from app.intake import flow

    flow.ensure_nodes()
    return NodeCall(db, rt.intake.ctx, by)


async def ingest(rt: ChannelsRuntime, msg: dict[str, Any]) -> None:
    msgtype = msg.get("msgtype", "")
    origin = msg.get("origin")
    open_kfid = msg.get("open_kfid", rt.open_kfid)
    external = msg.get("external_userid", "")
    msgid = msg.get("msgid", "")
    ctx = rt.intake.ctx

    if msgtype == "event":
        await handle_event(rt, msg.get("event", {}), open_kfid, _send_time(msg), msgid=msgid)
        return
    if origin != 3 or not external:  # 接待人员自己发的、系统消息：不当客户消息
        return

    at = _send_time(msg)
    with rt.intake.database.session() as db:
        customer = await _customer(rt, db, external, open_kfid)
        if service.is_duplicate(db, customer, msgid):
            return
        if msgtype == "text":
            im = InboundMessage(entry="entry.wecom", session_id=customer.id, channel_msgid=msgid, kind="text",
                                text=msg.get("text", {}).get("content", ""), at=at)
        elif msgtype in FILE_TYPES:
            body = msg.get(msgtype, {}) or {}
            im = InboundMessage(entry="entry.wecom", session_id=customer.id, channel_msgid=msgid, kind=msgtype,  # type: ignore[arg-type]
                                file_ref=body.get("media_id", ""), file_name=body.get("file_name", "") or "", at=at)
        else:
            # 小程序、位置、链接……先当一句文字收着，让助手和 Edison 看到
            im = InboundMessage(entry="entry.wecom", session_id=customer.id, channel_msgid=msgid, kind="other",
                                text=f"[客户发了{msgtype}，这边看不了内容]", at=at)
        res = run_node("entry.route", _call(rt, db), {"msg": im})
        out = res.output
        if out is None or not out.fetch_file or im.kind not in FILE_TYPES:
            return
        media: tuple[bytes, str, str] | None = None
        try:
            media = await rt.wecom.get_media(im.file_ref or "") if rt.wecom else None
        except WecomError as e:
            log.warning("下载客户文件失败：%s", e)
        if media is None:
            service.receive_text(db, ctx, customer, f"[客户发了{msgtype}，这边没下载下来]", channel_msgid=msgid, at=at, claim=False)
            return
        data, name, ctype = media
        name = im.file_name or name
        if msgtype == "voice":
            service.receive_voice(db, ctx, customer, filename=name or f"{msgid}.amr", data=data, channel_msgid=msgid, at=at)
        else:
            kind = "image" if msgtype == "image" else "file"
            service.receive_file(db, ctx, customer, filename=name or f"{msgid}.{msgtype}", data=data, content_type=ctype,
                                 kind=kind, channel_msgid=msgid, at=at)


async def handle_event(rt: ChannelsRuntime, event: dict[str, Any], open_kfid: str, at: datetime | None = None, *,
                       msgid: str = "") -> None:
    etype = event.get("event_type", "")
    external = event.get("external_userid", "")
    with rt.intake.database.session() as db:
        if etype == "enter_session" and external:
            scene, param = event.get("scene", ""), event.get("scene_param", "")
            has_code = bool(codes.normalize_code(param or ""))
            source = scene if has_code else (param or scene)  # 码不当来源记
            customer = await _customer(rt, db, external, open_kfid, source=source)
            if msgid and _seen_enter(db, customer, msgid):
                return  # 同一个进入事件又拉到一遍（游标回退、回调重试）：不再认领、不再发欢迎语
            record_event(db, "entry.wecom_enter", f"customer:{customer.id}", {
                "msgid": msgid, "scene": scene, "has_code": has_code, "param": "" if has_code else param[:64]})
            ecfg = load_entry_config(db)
            token = event.get("welcome_code", "") or None
            deadline = (at or utcnow()) + timedelta(seconds=ecfg.wecom_welcome_max_age_s)
            im = InboundMessage(entry="entry.wecom", session_id=customer.id, kind="enter", entered_with=param or None,
                                welcome_token=token, welcome_deadline=deadline, at=at or utcnow())
            res = run_node("entry.route", _call(rt, db), {"msg": im})
            out = res.output
            if out is not None and token:
                await _send_welcome(rt, db, customer, out.welcome_outbox_ids, token, deadline)
        elif etype == "msg_send_fail":
            fail_msgid = event.get("fail_msgid", "")
            record_event(db, "channels.wecom_send_fail", f"customer:{external}", {"msgid": fail_msgid, "fail_type": event.get("fail_type")})
            m = db.scalar(select(Message).where(Message.channel_msgid == fail_msgid))
            if m is not None and m.outbox_id:
                ob = db.get(Outbox, m.outbox_id)
                if ob is not None:
                    service.mark_failed(db, ob, f"企业微信事后通知发送失败（fail_type={event.get('fail_type')}）")
        else:
            record_event(db, "channels.wecom_event", "", {"event_type": etype, "event": event})


def _seen_enter(db: Session, customer: Customer, msgid: str) -> bool:
    rows = db.scalars(select(Event).where(Event.type == "entry.wecom_enter", Event.subject == f"customer:{customer.id}"))
    return any((e.content or {}).get("msgid") == msgid for e in rows)


async def _send_welcome(rt: ChannelsRuntime, db: Session, customer: Customer, outbox_ids: list[int], token: str,
                        deadline: datetime) -> None:
    """欢迎语凭证只能用一次、20 秒内：只发第一条（认领结果 + 清单合成的那一条），在提交前发掉（发件员看不到这条）。
    过了时限或发失败：那条留在待发，发件员按窗口发（客人还没说话 → 等他开口补发）。"""
    if not outbox_ids or rt.wecom is None:
        return
    ob = db.get(Outbox, outbox_ids[0])
    if ob is None or ob.status != "approved":
        return  # 设置里「欢迎语」打开了先给我看：凭证等不了，留给后台
    if utcnow() > deadline:
        record_event(db, "entry.welcome_failed", f"customer:{customer.id}", {"outbox": ob.id, "why": "凭证过了时限"})
        return
    try:
        msgid = await rt.wecom.send_msg_on_event(token, ob.text)
    except WecomError as e:
        record_event(db, "entry.welcome_failed", f"customer:{customer.id}", {"outbox": ob.id, "error": str(e)[:300]})
        return
    service.mark_sent(db, ob, channel_msgid=msgid or None)
    ob.reasons = [*(ob.reasons or []), "用欢迎语凭证发的（不占 48 小时 5 条）"]
    record_event(db, "entry.welcome_sent", f"customer:{customer.id}", {"outbox": ob.id})
