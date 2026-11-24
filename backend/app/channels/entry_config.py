"""入口的设置（后台「入口」页改）：微信客服开关、兑换用的客服链接、兑换页上「在哪买」的字、几个限额。

存在订单中枢的设置表（intake_kv）里一行 `entry_config`（整段 JSON），跟业务设置 `config` 分开：
访客每天条数、资料清单、入口话术这些是订单中枢的设置（契约第二节第 6 条），这里不重复。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.intake.models import KV

KEY = "entry_config"
SCENE_RE = r"^[0-9a-zA-Z_-]{1,32}$"


class BuyPlace(BaseModel):
    label: str = Field(min_length=1, max_length=40)
    text: str = Field(default="", max_length=200)
    url: str = Field(default="", max_length=300)


class EntryConfig(BaseModel):
    # 微信客服：默认关。Edison 把企业认证、域名、回调配好、生成了兑换用的客服链接，再在后台打开
    wecom_enabled: bool = False
    wecom_links: dict[str, str] = Field(default_factory=dict)  # scene → 客服链接（add_contact_way 生成的，一字不改）
    wecom_reserve_for_delivery: int = Field(default=2, ge=0, le=4)  # 48 小时窗口里给交付留几条（我的建议）
    wecom_welcome_max_age_s: int = Field(default=15, ge=1, le=19)  # 欢迎语凭证 20 秒有效，留余量（我的建议）
    # 入站分流用哪张规则表（app/channels/flows/<名字>.json）；换一张表就换一条路
    entry_flow: str = Field(default="entry_default", pattern=r"^[a-z_]+$", max_length=32)
    # 兑换页上放哪几个入口（默认全部）
    redeem_entries: list[str] = Field(default_factory=lambda: ["entry.webchat", "entry.wecom"])
    # 限流（我的建议）：兑换页同一 IP 每小时查几次；网页聊天没认领时同一 IP 每天最多几条
    redeem_ip_hourly: int = Field(default=60, ge=1)
    web_visitor_ip_daily: int = Field(default=60, ge=1)
    # 兑换页「激活码从哪来」：在哪买（不写价格；价目在官网和下单页）
    buy_places: list[BuyPlace] = Field(default_factory=lambda: [
        BuyPlace(label="网页下单", text="在下单页选时长和篇数，付完款页面上直接给激活码。", url="/order"),
        BuyPlace(label="闲鱼、小红书、抖音", text="在平台下单后，激活码和兑换网址在订单的发货消息里。"),
    ])
    code_hint: str = "激活码是 PSY- 开头、后面 9 位的一串（字母和数字，不含 0、O、1、I、L）。"
    # 官网（价目、交付说明、退款）：欢迎语、访客上限那句后面带一句「想先自己看看」；问答卡的 {介绍页链接}
    site_url: str = Field(default="https://psyppt.pilipala.zj.cn", max_length=200)
    # 认领前要求登录（12 号设计第六节）：默认开；这台设备一种登录方式都没开时照旧不登录认领。
    # 关掉 = 所有设备都不登录也能认领（微信登录哪天出问题时的退路，后台「入口」页一键关）
    login_required: bool = True
    # 聊天里说这几句之一（整条消息，去掉标点）算「确认收货」：只对认客人确认的渠道（确认来源表）
    confirm_phrases: list[str] = Field(default_factory=lambda: ["确认收货", "确认", "确认收到", "已确认收货"])

    @field_validator("wecom_links")
    @classmethod
    def _scenes(cls, v: dict[str, str]) -> dict[str, str]:
        import re

        for scene in v:
            if not re.fullmatch(SCENE_RE, scene):
                raise ValueError(f"scene「{scene}」只能是字母数字下划线横线，最多 32 个字符")
        return v


def load_entry_config(db: Session) -> EntryConfig:
    row = db.get(KV, KEY)
    data: dict[str, Any] = row.value if row is not None and isinstance(row.value, dict) else {}
    return EntryConfig.model_validate(data)


def save_entry_config(db: Session, cfg: EntryConfig) -> EntryConfig:
    from app.core.events import record_event

    before = load_entry_config(db).model_dump()
    value = cfg.model_dump()
    row = db.get(KV, KEY)
    if row is None:
        db.add(KV(key=KEY, value=value, updated_at=utcnow()))
    else:
        row.value = value
        row.updated_at = utcnow()
    db.flush()
    changed = sorted(k for k in value if value[k] != before.get(k))
    record_event(db, "entry.config_changed", "", {"fields": changed, "by": "edison"})
    return cfg
