"""聚人模块的表（07 设计第八节；不碰 intake_*）。

- funnel_visits：每个来图库的人从哪来、带没带分享码。
- figure_unlocks：一次「要全部图库」（gather_figures 流程的对象：flow_step、stage 只有流程引擎写）。
- figure_unlock_evidence：交的截图（只存 storage 相对路径，不出对外接口）。
- figure_packs：网盘包（后台贴链接，代码里不写死）；figure_pack_grants：发链接留痕。
- gather_settings：后台「聚人设置」（核验方式、插件名字、文案）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UTCDateTime, utcnow

FLOW_KEY = "gather_figures"


class FunnelVisit(Base):
    __tablename__ = "funnel_visits"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    visitor: Mapped[str] = mapped_column(String(40), index=True)
    src: Mapped[str] = mapped_column(String(32), default="", index=True)
    share_code: Mapped[str | None] = mapped_column(String(12), nullable=True, index=True)
    share_counted: Mapped[bool] = mapped_column(Boolean, default=False)  # 这次给分享码 +1 了
    landing: Mapped[str] = mapped_column(String(300), default="")
    referrer_host: Mapped[str] = mapped_column(String(100), default="")
    ip: Mapped[str] = mapped_column(String(64), default="", index=True)


class FigureUnlock(Base):
    __tablename__ = "figure_unlocks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    flow_key: Mapped[str] = mapped_column(String(32), default=FLOW_KEY)
    flow_step: Mapped[str] = mapped_column(String(32), default="", index=True)
    stage: Mapped[str] = mapped_column(String(16), default="", index=True)
    stage_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    visitor: Mapped[str] = mapped_column(String(40), index=True)
    share_code: Mapped[str] = mapped_column(String(12), unique=True)
    src: Mapped[str] = mapped_column(String(32), default="")
    tier: Mapped[str] = mapped_column(String(8), default="full")  # full 全量 / lite 小包
    verifiers: Mapped[list[Any]] = mapped_column(JSON, default=list)  # 发起时按设置记下的核验方式（流程条件用）
    verifier: Mapped[str] = mapped_column(String(32), default="")  # 最后是哪种过的
    verdict_reason: Mapped[str] = mapped_column(String(300), default="")
    door: Mapped[str] = mapped_column(String(16), default="web_upload")  # web_upload / wecom（默认不开）
    channel_user: Mapped[str] = mapped_column(String(80), default="", index=True)  # 访客号或微信 external_userid
    share_visits: Mapped[int] = mapped_column(Integer, default=0)  # 他的链接带来了几个新访客
    passed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    ip: Mapped[str] = mapped_column(String(64), default="")


class UnlockEvidence(Base):
    __tablename__ = "figure_unlock_evidence"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    unlock_id: Mapped[int] = mapped_column(Integer, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    file: Mapped[str] = mapped_column(String(500))  # storage 相对路径（只在后台按号取图时用）
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    visitor: Mapped[str] = mapped_column(String(40), default="", index=True)
    admin_mark: Mapped[str] = mapped_column(String(8), default="")  # "" / ok / fake


class FigurePack(Base):
    __tablename__ = "figure_packs"
    __table_args__ = (UniqueConstraint("version", "tier", name="uq_figure_packs_version_tier"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    version: Mapped[str] = mapped_column(String(16))
    tier: Mapped[str] = mapped_column(String(8))  # full / lite
    provider: Mapped[str] = mapped_column(String(16), default="baidu")
    url: Mapped[str] = mapped_column(String(500))
    extract_code: Mapped[str] = mapped_column(String(16), default="")
    count: Mapped[int] = mapped_column(Integer, default=0)
    size_mb: Mapped[float] = mapped_column(Float, default=0.0)
    manifest_sha256: Mapped[str] = mapped_column(String(64), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    note: Mapped[str] = mapped_column(String(200), default="")


class PackGrant(Base):
    __tablename__ = "figure_pack_grants"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    unlock_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    pack_id: Mapped[int] = mapped_column(Integer, index=True)
    tier: Mapped[str] = mapped_column(String(8), default="full")
    door: Mapped[str] = mapped_column(String(16), default="web_upload")
    channel_user: Mapped[str] = mapped_column(String(80), default="", index=True)
    sent_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    resend_count: Mapped[int] = mapped_column(Integer, default=0)


class GatherSetting(Base):
    __tablename__ = "gather_settings"
    key: Mapped[str] = mapped_column(String(48), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON, default=None)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    note: Mapped[str] = mapped_column(Text, default="")
