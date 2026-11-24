"""平台渠道的表（模块 C）。订单中枢的表一列不碰：建单、发码、信号一律走节点。

- 收件箱 PlatformsInbox：每一条进来的东西——负责人录的单、买家在固定链接页填的订单号（待核对）、以后平台推送。
  按 dedupe_key（渠道:平台订单号）去重；记下建出来的单和码、要贴到平台的发货文案、走到哪个出口。
- 商品 PlatformsProduct：平台上挂的一个商品对应哪个货号（平台多半一个商品一个价，加购也各挂一个）。
  固定链接方式下每个商品一个口令（token），买家打开 /x/<口令> 填订单号。
- 渠道档案的后台改动 PlatformsProfile：只存「用哪个适配器实现、开没开」，盖过 profiles.json 的默认值。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UTCDateTime, utcnow

INBOX_EXIT_LABELS: dict[str, str] = {
    "manual": "待贴发货文案",
    "delivered": "码已给到买家",
    "pending_verify": "待核对订单号",
    "rejected": "核对没通过",
    "blocked": "买家退款太多次，没发码",
    "text_blocked": "发货文案过不了红线",
    "fail": "出错了",
}


class PlatformsInbox(Base):
    __tablename__ = "platforms_inbox"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(String(8), index=True)  # xhs / xy / dy
    source: Mapped[str] = mapped_column(String(16))  # manual 后台录单 / buyer_claim 买家填订单号 / push 平台推送 / tool 发货工具
    dedupe_key: Mapped[str] = mapped_column(String(96), unique=True)  # 渠道:平台订单号
    platform_order_id: Mapped[str] = mapped_column(String(64), index=True)
    product_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sku: Mapped[str] = mapped_column(String(48), default="")
    addons: Mapped[list[str]] = mapped_column(JSON, default=list)
    paid_amount: Mapped[str] = mapped_column(String(16), default="")
    buyer_hint: Mapped[str] = mapped_column(String(64), default="")  # 负责人顺手记的买家平台号（弱标识，号能改）
    verified: Mapped[bool] = mapped_column(Boolean, default=False)  # 平台推送验过签 / 负责人亲手录的 / 负责人核对过
    verify_status: Mapped[str] = mapped_column(String(16), default="")  # 只给 buyer_claim：pending / ok / rejected
    claim_token: Mapped[str] = mapped_column(String(48), default="", index=True)  # 买家页面凭它刷结果
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # 原始表单（手机号、地址这类不收）
    exit: Mapped[str] = mapped_column(String(16), default="")
    order_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    code: Mapped[str] = mapped_column(String(32), default="")
    delivery_text: Mapped[str] = mapped_column(Text, default="")  # 要贴到平台的那句（人工渠道）
    pasted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)  # 负责人点了「贴好了」
    signals: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)  # 点过的平台信号 [{kind, at, exit}]
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)  # 点了「平台已完成」
    by: Mapped[str] = mapped_column(String(32), default="")
    client_ip: Mapped[str] = mapped_column(String(64), default="")
    error: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class PlatformsProduct(Base):
    __tablename__ = "platforms_products"
    __table_args__ = (UniqueConstraint("platform", "product_ref", name="uq_platforms_products_platform_ref"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(String(8), index=True)
    product_ref: Mapped[str] = mapped_column(String(64))  # 平台上的笔记 / 商品 id（没有就写个好认的名字）
    title: Mapped[str] = mapped_column(String(64), default="")  # 后台看的名字
    sku: Mapped[str] = mapped_column(String(48))
    addons: Mapped[list[str]] = mapped_column(JSON, default=list)
    listed_price: Mapped[str] = mapped_column(String(16), default="")  # 负责人在平台上标的价（对账提醒用）
    token: Mapped[str] = mapped_column(String(24), unique=True)  # 固定链接 /x/<token>
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class PlatformsProfile(Base):
    __tablename__ = "platforms_profiles"

    platform: Mapped[str] = mapped_column(String(8), primary_key=True)
    adapter: Mapped[str] = mapped_column(String(24), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    by: Mapped[str] = mapped_column(String(32), default="edison")
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)
