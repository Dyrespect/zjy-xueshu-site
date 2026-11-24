"""发件员：把「已批」的待发真的发出去（intake 不 import channels，所以由这里去取）。

- 网页聊天：直接标「已发」，客户刷新就看到。
- 微信客服（entry.wecom 的出站）：后台「入口」页的开关关着就不发；发前先查 48 小时 / 5 条（客户最后一次说话后
  48 小时内最多 5 条，客户再说一句重新计）；窗口只剩几条、这单在制作中时只发交付类（给交付留着）；
  再查会话状态，只在 0 未处理、1 智能助手接待时调 send_msg（官方：其他状态不让用接口发）。
  这几种发不了的标「发送失败」并写明原因，客户下次说话时自动重新排队（service.WINDOW_FAIL_PREFIXES）。
  文字超过 2048 字节、文件超过 20MB 都不发，后台能看到、能改了再批。图片和文件先 media/upload 拿 media_id。
- 多进程（11-18 底座可扩展）：每条发之前先拿租约锁 channels.outbox:<id>，拿到再看一眼还是不是「已批」，
  两个进程（或后台「马上发」和定时发件员）同时看到同一条，只有一个发出去。
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.channels.entry_config import load_entry_config
from app.channels.runtime import ChannelsRuntime
from app.channels.wecom_client import WecomError
from app.core.events import record_event
from app.core.tasks import new_holder, release_lease, try_lease
from app.intake import service
from app.intake.models import Customer, FileRecord, Order, Outbox

log = logging.getLogger("app.channels.dispatch")

TEXT_MAX_BYTES = 2048
FILE_MAX_BYTES = 20 * 1024 * 1024
IMAGE_MAX_BYTES = 10 * 1024 * 1024
SENDABLE_STATES = (0, 1)  # 官方会话状态：0 未处理、1 智能助手接待 才能用接口发
DELIVERY_CATEGORIES = ("交付", "排期通知")


async def dispatch_approved(rt: ChannelsRuntime, *, outbox_id: int | None = None, limit: int = 20) -> int:
    db_ = rt.intake.database
    with db_.session(write=False) as db:  # 只是看有哪些要发：读会话，不占写锁
        if outbox_id is not None:
            ob = db.get(Outbox, outbox_id)
            ids = [ob.id] if ob is not None and ob.status == "approved" else []
        else:
            ids = [ob.id for ob in service.approved_outbox(db, limit=limit)]
    n = 0
    for oid in ids:
        await _send_one(rt, oid)
        n += 1
    return n


async def _send_one(rt: ChannelsRuntime, outbox_id: int) -> None:
    lease, holder = f"channels.outbox:{outbox_id}", new_holder("dispatch")
    if not try_lease(rt.intake.database, lease, holder, 300):
        return  # 别的进程正在发这一条
    try:
        await _send_one_locked(rt, outbox_id)
    finally:
        release_lease(rt.intake.database, lease, holder, forget=True)


async def _send_one_locked(rt: ChannelsRuntime, outbox_id: int) -> None:
    db_ = rt.intake.database
    with db_.session() as db:
        ob = db.get(Outbox, outbox_id)
        if ob is None or ob.status != "approved":
            return
        if ob.channel == "web":
            service.mark_sent(db, ob)
            return
        if ob.channel != "wecom":
            service.mark_failed(db, ob, f"不认识的渠道：{ob.channel}")
            return
        if rt.wecom is None:
            service.mark_failed(db, ob, "企业微信凭证还没配，发不了")
            return
        ecfg = load_entry_config(db)
        if not ecfg.wecom_enabled:
            service.mark_failed(db, ob, "微信客服还没开（后台「入口」页的开关），发不了")
            return
        customer = db.get(Customer, ob.customer_id)
        win = service.window_info(db, customer)
        if not win["can_send"]:
            why = "客户最后一次说话已经超过 48 小时" if (win["hours_left"] or 0) <= 0 else "48 小时内已经发满 5 条"
            service.mark_failed(db, ob, f"{why}，等客户再说一句才能发")
            record_event(db, "entry.send_deferred", f"customer:{customer.id}", {"outbox": ob.id, "why": why})
            return
        order = db.get(Order, ob.order_id) if ob.order_id else None
        if (ob.author != "edison" and ob.category not in DELIVERY_CATEGORIES and order is not None
                and order.stage == "making" and win["sends_left"] <= ecfg.wecom_reserve_for_delivery):
            service.mark_failed(db, ob, f"窗口里给交付留着（只剩 {win['sends_left']} 条），等客户再说一句再发")
            record_event(db, "entry.send_deferred", f"customer:{customer.id}", {"outbox": ob.id, "why": "给交付留着"})
            return
        open_kfid = customer.open_kfid or rt.open_kfid
        touser = customer.external_id
        ob_customer = customer.id
        kind, text, asset = ob.kind, ob.text, ob.asset
        file_rec = db.get(FileRecord, ob.file_id) if ob.file_id else None
        image_path = service.asset_path(db, rt.intake.ctx, asset) if kind == "image" and asset else None
        file_bytes = None
        if file_rec is not None:
            if file_rec.size > FILE_MAX_BYTES:
                service.mark_failed(db, ob, "文件超过 20MB，微信客服发不了，改发交付页链接")
                return
            file_bytes = (file_rec.filename, rt.intake.ctx.storage.read_bytes(file_rec.storage_key))

    # 网络请求不占库。先查会话状态：只在 0、1 时发（我们从不把会话转人工，见 admin 的「我来接」）
    try:
        state = await rt.wecom.service_state_get(open_kfid, touser)
        if int(state.get("service_state", -1)) not in SENDABLE_STATES:
            with db_.session() as db:
                service.mark_failed(db, db.get(Outbox, outbox_id),
                                    f"会话状态现在不能发（状态 {state.get('service_state')}），等客户再说一句再发")
                record_event(db, "entry.send_deferred", f"customer:{ob_customer}", {"outbox": outbox_id, "state": state.get("service_state")})
            return
    except WecomError as e:
        with db_.session() as db:
            service.mark_failed(db, db.get(Outbox, outbox_id), f"查会话状态失败：{e}")
        return
    try:
        if kind == "text":
            if len(text.encode("utf-8")) > TEXT_MAX_BYTES:
                raise ValueError("文字超过 2048 字节（微信客服上限），改短一点")
            msgid = await rt.wecom.send_msg(touser, open_kfid, "text", {"content": text}, msgid=f"ob{outbox_id}")
        elif kind == "image":
            name, data = _image_bytes(asset, image_path, file_bytes)
            media_id = await rt.wecom.upload_media("image", name, data)
            msgid = await rt.wecom.send_msg(touser, open_kfid, "image", {"media_id": media_id}, msgid=f"ob{outbox_id}")
        elif kind == "file" and file_bytes:
            media_id = await rt.wecom.upload_media("file", file_bytes[0], file_bytes[1])
            msgid = await rt.wecom.send_msg(touser, open_kfid, "file", {"media_id": media_id}, msgid=f"ob{outbox_id}")
        else:
            raise ValueError(f"不支持的消息类型：{kind}")
    except (WecomError, ValueError, OSError) as e:
        with db_.session() as db:
            service.mark_failed(db, db.get(Outbox, outbox_id), str(e))
        return
    with db_.session() as db:
        service.mark_sent(db, db.get(Outbox, outbox_id), channel_msgid=msgid or None)


ASSET_NAMES = {"pay_qr": "付款二维码", "owner_qr": "负责人微信二维码", "service_qr": "客服二维码"}


def _image_bytes(asset: str, path: Path | None, file_bytes: tuple[str, bytes] | None) -> tuple[str, bytes]:
    """固定图片（付款二维码、负责人微信二维码）在本机哪由 intake 定（service.asset_path），这里只读。"""
    if file_bytes:
        return file_bytes
    if asset not in ASSET_NAMES:
        raise ValueError(f"不认识的图片：{asset}")
    if path is None:
        raise ValueError(f"{ASSET_NAMES[asset]}还没放上来")
    data = path.read_bytes()
    if len(data) > IMAGE_MAX_BYTES:
        raise ValueError(f"{ASSET_NAMES[asset]}图片超过 10MB")
    return path.name, data
