"""微信客服回调队列：回调只验签、解密、写一行、回 success（官方 5 秒不回会重试 3 次）；工人在后台消费。

- enqueue_callback：回调里唯一能调的「干活」函数（scripts/check.py 规矩 17 拦着回调别做别的）。
- process_inbox：拿 Token 去拉消息（Token 10 分钟有效，过了 9 分钟就不带 token 拉）；失败退避重试 3 次，再不行标失败、通知负责人。
- 后台「入口」页的开关关着时不入队（只记一条事件），回调照样回 success。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import select

from app.channels.entry_config import load_entry_config
from app.channels.models import WecomInbox
from app.channels.runtime import ChannelsRuntime
from app.core.db import utcnow
from app.core.events import record_event

log = logging.getLogger("app.channels.wecom")

TOKEN_FRESH = timedelta(minutes=9)
MAX_ATTEMPTS = 3
BACKOFF = (5, 30, 120)


def enqueue_callback(rt: ChannelsRuntime, data: dict[str, str]) -> int | None:
    """回调解出来的那几个字段 → 一行 channels_wecom_inbox。不是「有新消息」的事件、或开关关着，不入队。"""
    if data.get("MsgType") != "event" or data.get("Event") != "kf_msg_or_event":
        return None
    with rt.intake.database.session() as db:
        if not load_entry_config(db).wecom_enabled:
            record_event(db, "entry.wecom_ignored", "", {"why": "微信客服开关关着"})
            return None
        row = WecomInbox(open_kfid=(data.get("OpenKfId") or rt.open_kfid)[:64], token=data.get("Token", "")[:256],
                         received_at=utcnow(), run_after=utcnow())
        db.add(row)
        db.flush()
        rid = row.id
    rt.inbox_wakeup.set()
    return rid


async def process_inbox(rt: ChannelsRuntime, *, limit: int = 10) -> int:
    """消费到期的回调：拉消息（拉到没有为止）。返回处理了几行。"""
    from app.channels.wecom import sync_messages

    now = utcnow()
    with rt.intake.database.session() as db:
        rows = list(db.scalars(select(WecomInbox).where(WecomInbox.status == "pending", WecomInbox.run_after <= now)
                               .order_by(WecomInbox.id).limit(limit)))
        jobs = [(r.id, r.open_kfid, r.token if now - r.received_at < TOKEN_FRESH else "", r.attempts) for r in rows]
    n = 0
    for rid, kfid, token, attempts in jobs:
        try:
            await sync_messages(rt, kfid, token)
            status, error = "done", ""
        except Exception as e:  # 一行出错不能把工人卡死
            log.exception("拉微信客服消息失败（回调 %s）", rid)
            status, error = "failed", f"{type(e).__name__}: {e}"[:500]
        with rt.intake.database.session() as db:
            row = db.get(WecomInbox, rid)
            row.attempts = attempts + 1
            row.error = error
            if status == "done":
                row.status, row.done_at = "done", utcnow()
            elif row.attempts < MAX_ATTEMPTS:
                row.run_after = utcnow() + timedelta(seconds=BACKOFF[min(row.attempts - 1, len(BACKOFF) - 1)])
            else:
                row.status = "failed"
                record_event(db, "node.failed", "", {"node": "entry.wecom", "inbox": rid, "error": error})
                rt.intake.ctx.notifier.send(f"微信客服拉消息连着失败 {row.attempts} 次：{error[:80]}", link="/admin/entry", level="urgent", kind="微信客服出错", who="wecom")
        n += 1
    return n


async def inbox_loop(rt: ChannelsRuntime, *, interval: float = 2.0) -> None:
    while True:
        try:
            await process_inbox(rt)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("微信客服回调队列这一圈出错")
        try:
            await asyncio.wait_for(rt.inbox_wakeup.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
        rt.inbox_wakeup.clear()
