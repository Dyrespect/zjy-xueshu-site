"""开票模块的表（设计 docs/任务单/07_开票_设计.md 第四节）。订单中枢的表一列不碰，order_id 只是一个号。

- InvoiceRequest：一张发票申请一行，走流程 invoice_basic（flow_step / stage 只有 app/intake/flow.py 写）。
  active_order_id 唯一：在办的（等订单完成 / 待开票 / 已开票）等于 order_id，驳回、作废、撤回后清空，
  所以「一单只能申请一次，作废后可重新申请」由库来保证。
- InvoiceFile：开好的发票文件（PDF、OFD、XML）。storage_key 只在后端用，任何接口都不返回。
- InvoiceNotice：发给客人的通知；发不了的是 pending（待发），Edison 在后台复制去发。
- InvoiceKV：设置（key=settings）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UTCDateTime, utcnow

FLOW_KEY = "invoice_basic"
ACTIVE_STAGES = ("draft", "requested", "issued")  # 在办的：占着这单的「一次申请」

KIND_LABELS = {"normal": "电子普通发票", "special": "增值税专用发票"}
TITLE_KIND_LABELS = {"unit": "单位", "personal": "个人"}
SOURCE_LABELS = {"checkout": "下单页预填", "pay_page": "付款页", "delivery": "交付页", "admin": "后台录入"}


class InvoiceRequest(Base):
    __tablename__ = "invoice_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 流程（只有流程引擎写 flow_step、stage）
    flow_key: Mapped[str] = mapped_column(String(32), default=FLOW_KEY)
    flow_step: Mapped[str] = mapped_column(String(32), default="", index=True)
    stage: Mapped[str] = mapped_column(String(16), default="", index=True)
    stage_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    order_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)  # 付款前预填时还没有
    active_order_id: Mapped[int | None] = mapped_column(Integer, nullable=True, unique=True)  # 在办的才有
    checkout_token_hash: Mapped[str] = mapped_column(String(64), default="", index=True)  # 付款页令牌的 sha256
    source: Mapped[str] = mapped_column(String(16), default="delivery")
    platform: Mapped[str] = mapped_column(String(16), default="")  # 订单的渠道（快照）

    # 客人填的（kind：normal 电子普通发票 / special 增值税专用发票；title_kind：unit / personal）
    kind: Mapped[str] = mapped_column(String(16), default="normal")
    title_kind: Mapped[str] = mapped_column(String(16), default="unit")
    title: Mapped[str] = mapped_column(String(120), default="")
    tax_id: Mapped[str] = mapped_column(String(24), default="")
    email: Mapped[str] = mapped_column(String(120), default="")
    bank_name: Mapped[str] = mapped_column(String(80), default="")
    bank_account: Mapped[str] = mapped_column(String(48), default="")
    address: Mapped[str] = mapped_column(String(160), default="")
    phone: Mapped[str] = mapped_column(String(32), default="")
    remark: Mapped[str] = mapped_column(String(120), default="")
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)  # 客人点了「核对无误」

    requested_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)  # 进「待开票」（出票用时从这算）
    issued_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)  # 驳回 / 作废 / 撤回
    amount: Mapped[str] = mapped_column(String(16), default="")  # 开票金额（两位小数）
    paid_snapshot: Mapped[str] = mapped_column(String(16), default="")  # 出票那一刻的实付
    refunded_snapshot: Mapped[str] = mapped_column(String(16), default="")
    invoice_no: Mapped[str] = mapped_column(String(32), default="")  # 发票号码（选填）
    issue_note: Mapped[str] = mapped_column(String(200), default="")
    reason: Mapped[str] = mapped_column(String(300), default="")  # 驳回 / 作废的原因，或关口说的「为什么还不能开」
    reopened_from: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 作废重开：从哪一张来
    by: Mapped[str] = mapped_column(String(32), default="customer")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class InvoiceFile(Base):
    __tablename__ = "invoice_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invoice_id: Mapped[int] = mapped_column(Integer, index=True)
    filename: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(8))  # pdf / ofd / xml
    size: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), default="")
    storage_key: Mapped[str] = mapped_column(String(300))  # 只在后端用
    by: Mapped[str] = mapped_column(String(32), default="edison")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class InvoiceNotice(Base):
    __tablename__ = "invoice_notices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invoice_id: Mapped[int] = mapped_column(Integer, index=True)
    kind: Mapped[str] = mapped_column(String(16), default="issued")  # issued / rejected / voided
    channel: Mapped[str] = mapped_column(String(8))  # email / chat
    status: Mapped[str] = mapped_column(String(8), index=True)  # sent / queued / pending / skipped
    target: Mapped[str] = mapped_column(String(160), default="")  # 发给谁（邮箱、会话号）
    subject: Mapped[str] = mapped_column(String(160), default="")
    text: Mapped[str] = mapped_column(Text, default="")
    detail: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class InvoiceKV(Base):
    __tablename__ = "invoice_kv"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    by: Mapped[str] = mapped_column(String(32), default="")
