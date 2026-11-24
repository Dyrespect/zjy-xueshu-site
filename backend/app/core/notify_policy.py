"""通知策略：只推要 Edison 动手的，其余进每日汇报。

Edison 11-19：「客户进来了、客户聊天了、开始做了、做完了、开始改了，都要汇报吗？……万一我们一天要接 50 个客户……要杀了我吗？」

业务代码调 `notifier.send(text, link, level=…, kind=…, who=…)`，三个级别（每个调用点归哪级见 docs/运维/运维手册.md 第三节的表）：
- urgent 立刻推：转人工、退款 / 投诉 / 反馈、修改次数用完还要改、钱和订单对不上、系统错（出图失败、助手回复失败）、版权删除……
  · 同类（kind）同一位客人或同一单（who）NOTIFY_MERGE_MINUTES（默认 10）分钟内只推第一条，后面的折进去，
    下次再推这一类时末尾说「上一条之后又来了 N 条」；
  · 每小时最多推 NOTIFY_URGENT_PER_HOUR（默认 10）条，多的不推、进日报「需要你看一眼的」，下一条推送末尾提示。
- digest 不推，进当天日报「需要你看一眼的」（按类别归拢，每类列最新几条，带后台链接）。
- count 不推、不逐条列：日报只给个数（新客户、认领、开工、交付、完成从事件表数）。

每条都记一行 core_notify_items（正文已脱敏），日报从这里读，运维按保留期清（设置里 retention.notify_days）。
写表和推送都在后台线程里做：调用方往往开着事务、拿着数据库写锁，不能等外网，也不能在同一个 SQLite 上再开写会话自己等自己。
网站、worker 各有一个线程；合并和每小时上限按表里的记录数，跨进程也对（几乎同时到的两条可能都推）。
"""

from __future__ import annotations

import atexit
import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Index, Integer, String, Text, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.db import Base, Database, UTCDateTime, utcnow
from app.core.notify import LEVELS, Level, Notifier
from app.core.redact import redact_text

log = logging.getLogger("app.notify")

# 记录的状态：urgent 推了 pushed / 推了没成 failed / 同类同一个 10 分钟内折进去 folded / 推满了每小时上限 overflow；
# digest、count 原样记级别名
STATUS_LABELS = {"pushed": "推了", "failed": "该推没推出去", "folded": "合并进前一条", "overflow": "推满了每小时上限，没推",
                 "digest": "进日报", "count": "只计数"}


class NotifyItem(Base):
    __tablename__ = "core_notify_items"
    __table_args__ = (Index("ix_core_notify_items_group", "kind", "who", "at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    level: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(12), index=True)
    kind: Mapped[str] = mapped_column(String(32), default="")
    who: Mapped[str] = mapped_column(String(64), default="")
    text: Mapped[str] = mapped_column(Text, default="")  # 已脱敏
    link: Mapped[str] = mapped_column(String(300), default="")


@dataclass
class _Item:
    at: datetime
    level: str
    kind: str
    who: str
    text: str
    link: str


class PolicyNotifier(Notifier):
    """包在具体发法（inner：飞书应用机器人、群机器人或只写日志）外面的一层。send() 排进队列就返回 True，后台线程按级别处理。"""

    def __init__(
        self,
        inner: Notifier,
        database: Database,
        *,
        merge_minutes: int = 10,
        urgent_per_hour: int = 10,
        background: bool = True,
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self.inner = inner
        self.database = database
        self.merge = timedelta(minutes=merge_minutes)
        self.urgent_per_hour = urgent_per_hour
        self.background = background
        self._now = now
        self._q: queue.Queue[_Item] = queue.Queue(maxsize=5000)
        self._mu = threading.Lock()
        self._thread: threading.Thread | None = None

    # ---------------------------------------------------------------- 入口

    def send(self, text: str, link: str = "", *, level: Level = "digest", kind: str = "", who: str = "") -> bool:
        lv = level if level in LEVELS else "digest"
        item = _Item(at=self._now(), level=lv, kind=kind[:32], who=who[:64], text=redact_text(text)[:1000], link=link[:300])
        if not self.background:
            return self.handle(item)
        self._start()
        try:
            self._q.put_nowait(item)
        except queue.Full:
            log.warning("通知排队的太多了，这条只写日志：%s", item.text[:80])
            return False
        return True

    # ---------------------------------------------------------------- 处理一条

    def handle(self, item: _Item) -> bool:
        if item.level != "urgent":
            self._save(item, item.level)
            return True
        status, tail = self._decide(item)
        if status != "push":
            self._save(item, status)
            return True
        ok = self.inner.send(item.text + tail, item.link, level="urgent", kind=item.kind, who=item.who)
        self._save(item, "pushed" if ok else "failed")
        return ok

    def _decide(self, item: _Item) -> tuple[str, str]:
        """（push / folded / overflow，推的时候末尾补的话）。"""
        with self.database.session(write=False) as db:
            last = None
            if item.kind and item.who:
                last = db.scalar(select(func.max(NotifyItem.at)).where(
                    NotifyItem.kind == item.kind, NotifyItem.who == item.who, NotifyItem.status == "pushed"))
                if last is not None and self.merge and item.at - last < self.merge:
                    return "folded", ""
            pushed = db.scalar(select(func.count()).select_from(NotifyItem).where(
                NotifyItem.status == "pushed", NotifyItem.at >= item.at - timedelta(hours=1))) or 0
            if pushed >= self.urgent_per_hour:
                return "overflow", ""
            tail = []
            if last is not None:
                folded = db.scalar(select(func.count()).select_from(NotifyItem).where(
                    NotifyItem.kind == item.kind, NotifyItem.who == item.who, NotifyItem.status == "folded", NotifyItem.at > last)) or 0
                if folded:
                    tail.append(f"上一条之后同一位又来了 {folded} 条，一起看")
            last_push = db.scalar(select(func.max(NotifyItem.at)).where(NotifyItem.status == "pushed"))
            since = max(last_push, item.at - timedelta(days=1)) if last_push is not None else item.at - timedelta(days=1)
            over = db.scalar(select(func.count()).select_from(NotifyItem).where(
                NotifyItem.status == "overflow", NotifyItem.at > since)) or 0
            if over:
                tail.append(f"另有 {over} 条要紧的没单独推（每小时最多推 {self.urgent_per_hour} 条），在今晚日报里")
        return "push", ("\n（" + "；".join(tail) + "）") if tail else ""

    def _save(self, item: _Item, status: str) -> None:
        with self.database.session() as db:
            db.add(NotifyItem(at=item.at, level=item.level, status=status, kind=item.kind, who=item.who, text=item.text, link=item.link))

    # ---------------------------------------------------------------- 后台线程

    def _start(self) -> None:
        with self._mu:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._run, name="notify-policy", daemon=True)
            self._thread.start()
            atexit.register(self.flush, 3.0)  # 进程退出前尽量把排着的处理完

    def _run(self) -> None:
        while True:
            item = self._q.get()
            try:
                self.handle(item)
            except Exception as e:  # noqa: BLE001  线程不能死；这一条只剩日志
                log.warning("通知处理出错（%s），这条只写日志：%s", type(e).__name__, item.text[:80])
            finally:
                self._q.task_done()

    def flush(self, timeout: float = 5.0) -> bool:
        """等排着的处理完（测试、进程退出时用）。"""
        end = time.monotonic() + timeout
        while self._q.unfinished_tasks and time.monotonic() < end:
            time.sleep(0.01)
        return not self._q.unfinished_tasks


# ---------------------------------------------------------------- 给日报读

def look_items(db: Session, start: datetime, end: datetime, *, latest_n: int = 3) -> list[dict[str, Any]]:
    """[start, end) 里「需要你看一眼的」：没单独推的要紧事（推满了、没推出去）在前，digest 按类别归拢在后。
    每组：{status, kind, count, latest: [(text, link)…]（最新 latest_n 条）}。count 级别和合并进前一条的不列。"""
    rows = db.execute(select(NotifyItem.status, NotifyItem.kind, NotifyItem.text, NotifyItem.link)
                      .where(NotifyItem.at >= start, NotifyItem.at < end, NotifyItem.status.in_(("overflow", "failed", "digest")))
                      .order_by(NotifyItem.at.desc(), NotifyItem.id.desc())).all()
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for status, kind, text, link in rows:
        g = groups.setdefault((status, kind if status == "digest" else ""), {"status": status, "kind": kind if status == "digest" else "",
                                                                             "count": 0, "latest": []})
        g["count"] += 1
        if len(g["latest"]) < latest_n:
            g["latest"].append((text, link))
    order = {"overflow": 0, "failed": 1, "digest": 2}
    return sorted(groups.values(), key=lambda g: (order[g["status"]], -g["count"], g["kind"]))
