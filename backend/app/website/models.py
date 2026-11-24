"""官网的表：只有一张设置表（key=settings 一条），后台「官网」页改。

同意记录不另建表：记在事件里（website.consent，subject = checkout:<付款单令牌>），跟订单的其他留痕在一处查。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UTCDateTime, utcnow


class WebsiteKV(Base):
    __tablename__ = "website_kv"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    by: Mapped[str] = mapped_column(String(32), default="")
