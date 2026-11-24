"""channels 模块（入口，模块 D）的接口入口（挂在 /api/channels）：
网页聊天 /web/*、兑换网页 /redeem/*、微信客服回调 /wecom/callback、账号和「我的订单」/account/*、
登录 /login/*（微信里静默、电脑扫码、手机号）、服务号消息推送 /mp/callback（12 号设计）。

启动时把三样后台的事登记到底座调度器（网站进程或 python -m app.worker 跑，11-18 底座可扩展）：
- 发件员：每秒把「已批」的待发发出去（后台批准的时候也会马上发一次）；几个进程同时跑也不会重发（dispatch.py 每条先拿租约锁）；
- 微信客服回调队列：拉消息、分流（开关关着不入队）；全集群一个在跑（拉消息的游标只能一个人拉）；
- 客户记忆：每 30 秒按游标消费事件，刷新老客户的偏好和两份摘要；全集群一个在跑（游标不能两个人消费）；
- 需求卡提醒：每 5 分钟看一次，认领后 2 小时没确认需求卡的提醒客人一次（09 需求引导，brief_web.py）；全集群一个在跑。
发邮件的发件员也在这里装上（没配邮件服务就是关的）。
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

from fastapi import APIRouter, FastAPI

import app.channels.nodes  # noqa: F401  登记入口模块的节点和入口说明（EntrySpec）
from app.channels import account, brief_web, login_web, mailer, redeem_router, sms, web, wecom_router
from app.channels.dispatch import dispatch_approved
from app.channels.runtime import get_channels
from app.channels.wecom_inbox import process_inbox

router = APIRouter()
router.include_router(web.router)
router.include_router(redeem_router.router)
router.include_router(wecom_router.router)
router.include_router(account.router)
router.include_router(brief_web.router)
router.include_router(login_web.router)

MEMORY_EVERY = 30.0
BRIEF_REMIND_EVERY = 300.0


def memory_tick(app: FastAPI) -> str:
    from app.core.nodes import NodeCall, run_node
    from app.intake import flow

    rt = get_channels(app)
    flow.ensure_nodes()
    with rt.intake.database.session() as db:
        res = run_node("customer.memory", NodeCall(db, rt.intake.ctx, "system"), {"action": "consume"})
        return res.output.detail if res.output is not None else ""


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    rt = get_channels(app)
    rt.inbox_wakeup = asyncio.Event()  # 回调入队后叫醒（只在后台任务合在网站进程里时管用；分开时 worker 每 2 秒看一次）
    fake = getattr(app.state, "email_sender", None)
    sender, label = (fake, "test") if fake is not None else mailer.build_sender(rt.settings, rt.core.APP_ENV)
    mailer.set_sender(sender, label)
    if not hasattr(app.state, "sms_sender"):  # 测试里先放好假网关；没配短信 = None（整块关）
        app.state.sms_sender = sms.build_sender(rt.settings, rt.core.APP_ENV)
    sched = app.state.scheduler
    if rt.settings.CHANNELS_DISPATCH:
        sched.every("channels.dispatch", 1.0, lambda: dispatch_approved(rt), singleton=False)
    if rt.settings.CHANNELS_TICK:
        sched.every("channels.wecom_inbox", 2.0, lambda: process_inbox(rt))
        sched.every("channels.memory", MEMORY_EVERY, lambda: memory_tick(app))
        sched.every("channels.brief_remind", BRIEF_REMIND_EVERY, lambda: brief_web.remind_tick(rt), initial_delay=BRIEF_REMIND_EVERY)
        sched.every("channels.login_prune", 3600.0, lambda: login_web.prune_tick(rt), initial_delay=600.0)
    try:
        yield
    finally:
        for t in list(rt.tasks):
            t.cancel()
        mailer.set_sender(None)
