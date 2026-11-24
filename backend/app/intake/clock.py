"""业务上的「今天」「几点」一律按北京时间算（本机时钟是美东，服务器在硅谷）。库里存的仍是 UTC。"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.db import utcnow

TZ = ZoneInfo("Asia/Shanghai")
WEEKDAYS = "一二三四五六日"


def set_timezone(name: str) -> None:
    global TZ
    TZ = ZoneInfo(name)


def local_now(now: datetime | None = None) -> datetime:
    return (now or utcnow()).astimezone(TZ)


def today(now: datetime | None = None) -> date:
    return local_now(now).date()


def weekday_cn(d: date) -> str:
    return "周" + WEEKDAYS[d.weekday()]


def fmt_date(d: date | None, *, with_weekday: bool = True) -> str:
    if d is None:
        return ""
    s = f"{d.month}月{d.day}日"
    return f"{s}（{weekday_cn(d)}）" if with_weekday else s


def fmt_chat_time(dt: datetime) -> str:
    """跟工厂 inbox 现有的 聊天记录.md 一样：`2026年11月03日  5:44`（时不补零、用空格占位）。"""
    t = dt.astimezone(TZ)
    return f"{t.year}年{t.month:02d}月{t.day:02d}日 {t.hour:>2}:{t.minute:02d}"


def add_days(d: date, n: int) -> date:
    return d + timedelta(days=n)
