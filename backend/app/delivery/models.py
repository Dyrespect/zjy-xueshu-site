"""交付这一块自己的表：版本表（一版一行）。

这是节点的工作记录，不是订单状态（订单状态只由流程引擎写）。文件本身都登记在订单中枢的成品表 intake_files：
最终版（PPT、讲稿……）和水印图（purpose=水印版）由 service.add_deliverable 写，整页底图是 purpose=页图（role=page，
任何接口都不返回）。这里记的是「这一版用了哪几个文件、出图到哪一步、用什么参数出的、什么时候发布的」，
申诉时（抖音虚拟类争议要商家举证交付时间、交付内容）能说清。设计第六节。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UTCDateTime, utcnow

# received 收下了（还没出图）| rendering 在出图队列里 | ready 图出完了、等发布 | published 发布给客人了
# | failed 出图失败（重试用完）| final 已完成之后交的（只放最终版，不出水印图）
VERSION_STATUSES = ("received", "rendering", "ready", "published", "failed", "final")


class DeliveryVersion(Base):
    __tablename__ = "delivery_versions"
    __table_args__ = (UniqueConstraint("order_id", "round", name="uq_delivery_versions_order_round"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("intake_orders.id"), index=True)
    round: Mapped[int] = mapped_column(Integer)  # 第几版（= 订单交过的版数 + 1）
    status: Mapped[str] = mapped_column(String(16), default="received", index=True)
    source: Mapped[str] = mapped_column(String(16), default="maker_cli")  # maker_cli 制作方 | admin_upload 后台 | api
    note: Mapped[str] = mapped_column(String(2000), default="")
    revision_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 回应哪张改稿单
    slide_count: Mapped[int] = mapped_column(Integer, default=0)  # pptx 页数（不含隐藏页）
    page_count: Mapped[int] = mapped_column(Integer, default=0)  # 整页图张数
    page_file_ids: Mapped[list[int]] = mapped_column(JSON, default=list)  # 整页底图（按页码排）
    final_file_ids: Mapped[list[int]] = mapped_column(JSON, default=list)  # 这一版的最终版文件
    proof_file_ids: Mapped[list[int]] = mapped_column(JSON, default=list)  # 出好的水印图（按页码排）
    page_sha256: Mapped[list[str]] = mapped_column(JSON, default=list)  # 每页底图的 sha256（举证用）
    watermark_spec: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # 这一版的出图参数
    error: Mapped[str] = mapped_column(Text, default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_try_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    rendered_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    # 不加急的单第一版最早几点发给客人（压着到点自动发；负责人点「现在就发」改成现在）。release.py
    release_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
