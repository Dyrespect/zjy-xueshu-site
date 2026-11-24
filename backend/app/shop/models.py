"""自有渠道的表（订单中枢没有「待付款」，付款前的记录放这里；契约第六节最后一段）。

- 待付款单 ShopCheckout：客人点「去付款」时建，报价快照、应付金额全是服务端算的；付款成功后记下订单中枢建的单和码。
- 退款 ShopRefund：只有后台（Edison）能发起；先退钱，退成了才作废订单。
- 支付通知 ShopNotification：网关发来的每一条（验过签的解密原文、没验过的也留一条），按 dedupe_key 去重。
订单中枢的表一列不碰；order_id 只是一个号（不建外键，模块之间不绑表）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UTCDateTime, utcnow

CHECKOUT_STATUS_LABELS: dict[str, str] = {
    "pending": "待付款",
    "paid": "已付款",
    "closed": "已关闭",
    "refunding": "退款中",
    "refunded": "已退款",
    "part_refunded": "部分退款",
}
REFUND_STATUS_LABELS: dict[str, str] = {
    "processing": "退款中",
    "success": "退款成功",
    "closed": "退款关闭",
    "abnormal": "退款异常",
}


class ShopCheckout(Base):
    __tablename__ = "shop_checkouts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    view_token: Mapped[str] = mapped_column(String(48), unique=True, index=True)  # 付款页凭它查（32 位随机）
    out_trade_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)  # 商户订单号 PS + 北京时间 + 6 位随机
    pay_node: Mapped[str] = mapped_column(String(32))  # pay.wechat / pay.alipay / pay.fake
    method: Mapped[str] = mapped_column(String(24))  # wechat_native / alipay_page / alipay_wap ……
    sku: Mapped[str] = mapped_column(String(48))
    addons: Mapped[list[str]] = mapped_column(JSON, default=list)  # 同一笔买的加购 key（再改一轮可以重复）
    quote: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # sku.quote 的输出快照
    amount_fen: Mapped[int] = mapped_column(Integer)  # 应付（分），只按报价算
    subject: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    pay_kind: Mapped[str] = mapped_column(String(16), default="")  # qr / redirect / jsapi
    pay_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # 付款指令（二维码内容、跳转地址），付款页重开时用
    gateway_txn_id: Mapped[str] = mapped_column(String(64), default="")
    payer_ref: Mapped[str] = mapped_column(String(128), default="")  # 付款人标识（openid / 支付宝买家号），认退款过的买家用
    paid_fen: Mapped[int] = mapped_column(Integer, default=0)  # 网关说实付多少
    refunded_fen: Mapped[int] = mapped_column(Integer, default=0)
    order_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    code: Mapped[str] = mapped_column(String(32), default="")
    create_exit: Mapped[str] = mapped_column(String(16), default="")  # order.create 的出口：created / exists / blocked / fail
    session_ref: Mapped[str] = mapped_column(String(64), default="")  # 下单前在网页聊天里的会话 key（给认领用）
    source: Mapped[str] = mapped_column(String(64), default="")  # 从哪来（下单页的 from 参数）
    client_ip: Mapped[str] = mapped_column(String(64), default="")
    ua_kind: Mapped[str] = mapped_column(String(8), default="")  # wechat / mobile / pc
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    last_query_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class ShopRefund(Base):
    __tablename__ = "shop_refunds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    checkout_id: Mapped[int] = mapped_column(Integer, index=True)
    order_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    out_refund_no: Mapped[str] = mapped_column(String(32), unique=True)
    amount_fen: Mapped[int] = mapped_column(Integer)
    scope: Mapped[str] = mapped_column(String(32), default="full")  # full / addon:rush ……
    reason: Mapped[str] = mapped_column(String(200), default="")
    by: Mapped[str] = mapped_column(String(32), default="edison")
    status: Mapped[str] = mapped_column(String(16), default="processing")
    gateway_refund_id: Mapped[str] = mapped_column(String(64), default="")
    void_result: Mapped[str] = mapped_column(String(200), default="")  # 退全款后作废订单的结果
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class ShopNotification(Base):
    __tablename__ = "shop_notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pay_node: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(16), default="pay")  # pay / refund / unknown
    dedupe_key: Mapped[str] = mapped_column(String(128), unique=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    out_trade_no: Mapped[str] = mapped_column(String(32), default="", index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # 解密后的原文（openid 打码）
    result: Mapped[str] = mapped_column(String(32), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
