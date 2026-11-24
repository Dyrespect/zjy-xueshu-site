"""通用事件记录：后面所有「留记录」都用 `record_event`。

一条记录 = 什么时候（created_at）+ 什么事（type）+ 跟谁有关（subject）+ 细节（content，JSON）。
- type 用「模块.动作」：`intake.message_received`、`intake.tool_called`、`admin.reply_approved`、
  `figures.search` ……
- subject 用「对象类型:id」：`order:12`、`customer:wx_abc`、`figure:3187`；跟谁都无关就留空。
- content 放能回放的细节（输入、模型调用、工具参数、发出去的话、谁批的），必须能转成 JSON。

`record_event` 只 add + flush，不提交：跟业务改动放在同一个事务里，一起提交、一起回滚。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Integer, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.db import Base, UTCDateTime, utcnow


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    type: Mapped[str] = mapped_column(String(64), index=True)
    subject: Mapped[str] = mapped_column(String(128), default="", index=True)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


def record_event(
    db: Session,
    type: str,
    subject: str = "",
    content: dict[str, Any] | None = None,
) -> Event:
    """写一条事件记录（不提交，调用方 commit）。"""
    if not type or len(type) > 64:
        raise ValueError("事件类型不能为空，且不超过 64 个字符")
    if len(subject) > 128:
        raise ValueError("事件对象不超过 128 个字符")
    ev = Event(type=type, subject=subject, content=content or {}, created_at=utcnow())
    db.add(ev)
    db.flush()
    return ev


def list_events(
    db: Session,
    *,
    subject: str | None = None,
    type: str | None = None,
    limit: int = 100,
) -> list[Event]:
    """按时间倒序取事件，后台回放用。"""
    stmt = select(Event).order_by(Event.id.desc()).limit(limit)
    if subject is not None:
        stmt = stmt.where(Event.subject == subject)
    if type is not None:
        stmt = stmt.where(Event.type == type)
    return list(db.scalars(stmt))
