"""入口共用的类型（模块 D 设计第三节第 0 条）。只放类型，不是节点。

所有入口（网页聊天、微信客服、以后的小程序……）实现同一套：
- 入站：翻译成 `InboundMessage` 交给 `entry.route`；
- 出站：收 `OutboundMessage`、回 `SendResult`；
- 再登记一份 `EntrySpec`（app/channels/entries.py），说清自己的能力和「兑换页怎么带码进来」。
加一个入口 = 加一个节点文件 + 登记一份 EntrySpec，别处不动。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.db import utcnow


class EntryCaps(BaseModel):
    window_hours: int | None = Field(default=None, description="客人说话后多久内能发；None = 不限（网页）")
    window_max_sends: int | None = Field(default=None, description="窗口里最多发几条（微信客服 5）")
    can_push: bool = Field(default=True, description="客人不说话也能发（网页 True，微信客服 False）")
    text_max_bytes: int | None = Field(default=None, description="一条字数上限（微信客服 2048 字节）")
    recv_max_bytes: dict[str, int] = Field(default_factory=dict, description="收客人的：file / image / voice / video")
    send_max_bytes: dict[str, int] = Field(default_factory=dict, description="发出去的：file / image")
    has_welcome: bool = Field(default=False, description="进会话时有一次性欢迎语凭证（微信 welcome_code）")


InboundKind = Literal["text", "file", "image", "voice", "video", "enter", "other"]


class InboundMessage(BaseModel):
    entry: str = Field(description="entry.wecom | entry.webchat | …")
    session_id: int = Field(description="intake_customers.id（入口先找或建会话）")
    channel_msgid: str = Field(default="", description="去重；进入事件、网页消息可以空")
    kind: InboundKind = "text"
    text: str = ""
    file_ref: str | None = Field(default=None, description="微信 media_id；entry.route 放行前不取文件")
    file_name: str = ""
    file_size: int | None = None
    entered_with: str | None = Field(default=None, description="带码进入时的 scene_param（原样）")
    welcome_token: str | None = None
    welcome_deadline: datetime | None = None
    ip: str = Field(default="", description="网页：客户端 IP（记事件用）")
    ip_quota_ok: bool = Field(default=True, description="网页：同一 IP 今天的访客条数还没满（网页入口用底座限流器数好）")
    at: datetime = Field(default_factory=utcnow)


Purpose = Literal["welcome", "claim", "qa", "collect", "progress", "delivery", "limit", "owner"]


class OutboundMessage(BaseModel):
    session_id: int
    purpose: Purpose = "qa"
    kind: Literal["text", "file", "image"] = "text"
    text: str = ""
    file_id: int | None = None
    fallback_url: str | None = Field(default=None, description="文件发不了（超限）时改发的链接，一般是交付页")
    dedupe_key: str = Field(default="", description="同一件事不发两遍，如 claim:12")
    order_id: int | None = None
    category: str = Field(default="", description="待发的类别（后台按它决定要不要先给你看）；空 = 按 purpose 定")


class SendResult(BaseModel):
    status: Literal["sent", "queued", "deferred", "degraded", "failed", "duplicate"]
    outbox_id: int | None = None
    channel_msgid: str | None = None
    detail: str = ""


ResumeMode = Literal["link", "claim_here", "none"]


@dataclass
class EntrySpec:
    """一个入口的说明（app/channels/entries.py 汇总）。兑换页的按钮从这里来。"""

    node_id: str  # "entry.wecom"
    channel: str  # intake_customers.channel 的值："wecom" | "web"
    label: str  # 兑换页按钮字：「用微信客服继续」
    caps: EntryCaps
    resume: ResumeMode
    # 这个入口现在能不能用（微信客服：凭证配了、后台开关开了、兑换用的客服链接生成了）。参数：(db, 渠道运行时)
    available: Callable[[Any, Any], tuple[bool, str]] = field(default=lambda db, rt: (True, ""))
    # 带码进这个入口的链接（resume="link" 时）
    resume_link: Callable[[Any, str], str | None] | None = None
    hint: str = ""  # 按钮下面的一句提示
    order: int = 100  # 兑换页按钮顺序


# 进入事件、网页聊天这些入口发过来的话，出站时按 purpose 定后台的类别（「先给我看」开关按类别）
PURPOSE_CATEGORY: dict[str, str] = {
    "welcome": "欢迎语", "claim": "核销", "qa": "一般回复", "collect": "问缺的材料", "progress": "排期通知",
    "delivery": "交付", "limit": "访客上限", "owner": "负责人微信",
}
