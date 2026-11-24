"""运维模块的表（docs/任务单/07_运维与数据_设计.md 第四节）。只放运维自己的数；业务数从 events 表数，不碰业务模块的表。

- OpsSample：原始，每分钟 × kind × key × dim 一行（http：路由模板 ×「GET 2xx」；page：页面组 × pv；gauge：仪表名 × 子项）。
  n 次数、total 合计（毫秒或读数）、max 最大、hist 耗时分桶计数（分桶边界见 stats.BUCKETS_MS）。保留期见设置 retention.raw_days。
- OpsHourly：同样的列按小时合成一行（分桶相加），保留 retention.hourly_days。
- OpsError：每个 5xx 一行：路由模板（不存原始网址，里面有令牌）、请求号、类型、脱敏后的摘要。
- OpsVisitor：当天访客散列（HMAC(SESSION_SECRET, 日期) + IP + UA 取 16 位，换天换盐；不存 IP）。
- OpsAlert：告警（同一个 key 只有一条在开着；去重、静默靠它）。
- OpsKV：设置（settings）、调度上次跑的时间（jobs）、健康检查缓存等。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UTCDateTime, utcnow


class OpsSample(Base):
    __tablename__ = "ops_samples"
    __table_args__ = (UniqueConstraint("minute", "kind", "key", "dim", name="uq_ops_samples_slot"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    minute: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    kind: Mapped[str] = mapped_column(String(8), index=True)  # http | page | gauge
    key: Mapped[str] = mapped_column(String(160))
    dim: Mapped[str] = mapped_column(String(48), default="")
    n: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[float] = mapped_column(Float, default=0.0)
    max: Mapped[float] = mapped_column(Float, default=0.0)
    hist: Mapped[list[int]] = mapped_column(JSON, default=list)


class OpsHourly(Base):
    __tablename__ = "ops_hourly"
    __table_args__ = (UniqueConstraint("hour", "kind", "key", "dim", name="uq_ops_hourly_slot"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hour: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    kind: Mapped[str] = mapped_column(String(8), index=True)
    key: Mapped[str] = mapped_column(String(160))
    dim: Mapped[str] = mapped_column(String(48), default="")
    n: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[float] = mapped_column(Float, default=0.0)
    max: Mapped[float] = mapped_column(Float, default=0.0)
    hist: Mapped[list[int]] = mapped_column(JSON, default=list)


class OpsError(Base):
    __tablename__ = "ops_errors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    rid: Mapped[str] = mapped_column(String(64), default="")
    method: Mapped[str] = mapped_column(String(8), default="")
    route: Mapped[str] = mapped_column(String(160), default="")
    status: Mapped[int] = mapped_column(Integer, default=500)
    kind: Mapped[str] = mapped_column(String(64), default="")  # 异常类型；没接住的异常以外是「5xx」
    message: Mapped[str] = mapped_column(String(300), default="")  # 已脱敏
    ms: Mapped[float] = mapped_column(Float, default=0.0)


class OpsVisitor(Base):
    __tablename__ = "ops_visitors"
    __table_args__ = (UniqueConstraint("day", "vh", name="uq_ops_visitors_day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    day: Mapped[str] = mapped_column(String(10), index=True)  # 北京时间日期 2026-11-18
    vh: Mapped[str] = mapped_column(String(16))
    page: Mapped[str] = mapped_column(String(24), default="")  # 当天第一次来时进的页面组


class OpsAlert(Base):
    __tablename__ = "ops_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(120), index=True)  # 规则 id + 对象，如 http_5xx、external_down:deepseek
    rule: Mapped[str] = mapped_column(String(48), index=True)
    level: Mapped[str] = mapped_column(String(8))  # urgent 要立刻处理 | today 今天看一下 | info 只是记录
    title: Mapped[str] = mapped_column(String(200))
    detail: Mapped[str] = mapped_column(Text, default="")
    impact: Mapped[str] = mapped_column(String(200), default="")
    link: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(12), default="open", index=True)  # open | resolved
    first_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    last_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    count: Mapped[int] = mapped_column(Integer, default=1)  # 这条开着期间又触发了几次
    notified_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    notify_count: Mapped[int] = mapped_column(Integer, default=0)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    resolved_by: Mapped[str] = mapped_column(String(32), default="")
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class OpsKV(Base):
    __tablename__ = "ops_kv"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
