"""渠道在一个 app 里的运行时：企业微信客户端和加解密（凭证配了才有）、拉消息的锁、后台任务。

测试里在进 lifespan 之前设 `app.state.channels_settings`、`app.state.wecom_transport`（假的企业微信）。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, Request
from wechatpy.enterprise.crypto import WeChatCrypto

from app.channels.settings import ChannelsSettings
from app.channels.wecom_client import WecomClient
from app.core.config import Settings
from app.intake.runtime import IntakeRuntime, get_runtime


@dataclass
class ChannelsRuntime:
    settings: ChannelsSettings
    core: Settings
    intake: IntakeRuntime
    wecom: WecomClient | None
    crypto: WeChatCrypto | None
    sync_locks: dict[str, asyncio.Lock] = field(default_factory=dict)
    tasks: set[asyncio.Task[Any]] = field(default_factory=set)
    inbox_wakeup: asyncio.Event = field(default_factory=asyncio.Event)  # 回调入队后叫醒工人

    @property
    def open_kfid(self) -> str:
        return self.core.WECOM_OPEN_KFID

    def lock_for(self, open_kfid: str) -> asyncio.Lock:
        if open_kfid not in self.sync_locks:
            self.sync_locks[open_kfid] = asyncio.Lock()
        return self.sync_locks[open_kfid]

    def spawn(self, coro) -> asyncio.Task[Any]:
        task = asyncio.get_running_loop().create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task


def wecom_configured(core: Settings) -> dict[str, bool]:
    return {
        "corpid": bool(core.WECOM_CORPID),
        "secret": bool(core.WECOM_KF_SECRET.get_secret_value()),
        "token": bool(core.WECOM_TOKEN.get_secret_value()),
        "aes_key": bool(core.WECOM_AES_KEY.get_secret_value()),
        "open_kfid": bool(core.WECOM_OPEN_KFID),
    }


def get_channels(app: FastAPI) -> ChannelsRuntime:
    rt = getattr(app.state, "channels", None)
    if rt is None:
        core: Settings = app.state.settings
        cs: ChannelsSettings = getattr(app.state, "channels_settings", None) or ChannelsSettings()
        transport = getattr(app.state, "wecom_transport", None)
        client = None
        if core.WECOM_CORPID and core.WECOM_KF_SECRET.get_secret_value():
            client = WecomClient(core.WECOM_CORPID, core.WECOM_KF_SECRET.get_secret_value(),
                                 base_url=cs.WECOM_API_BASE, transport=transport)
        crypto = None
        if core.WECOM_CORPID and core.WECOM_TOKEN.get_secret_value() and core.WECOM_AES_KEY.get_secret_value():
            crypto = WeChatCrypto(core.WECOM_TOKEN.get_secret_value(), core.WECOM_AES_KEY.get_secret_value(), core.WECOM_CORPID)
        rt = ChannelsRuntime(cs, core, get_runtime(app), client, crypto)
        app.state.channels = rt
    return rt


def channels_dep(request: Request) -> ChannelsRuntime:
    return get_channels(request.app)
