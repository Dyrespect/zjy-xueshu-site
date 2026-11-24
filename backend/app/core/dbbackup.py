"""数据库备份的底层几件事（方言相关的写法只放 core）：在线拷一份、查完整性、数核对数。运维模块的备份节点调它。

- SQLite：用 sqlite3 自带的在线备份（Connection.backup），网站照常读写，拷出来的是某一刻一致的库；**不是直接拷文件**
  （WAL 模式下直接拷 app.db 会漏掉还在 -wal 里的数据，甚至拷到一半的坏库）。
- PostgreSQL：不在这里做，用托管库自带的自动备份和时间点恢复，或 pg_dump / pgBackRest（docs/方案 万人路线图）。
  online_backup 遇到非 SQLite 抛 NotImplementedError，调用方写清楚原因。
- 核对数（facts）：数某张表的行数、某一列的合计（金额用 Decimal 加，不用浮点），只用 SQLAlchemy 的通用写法。
"""

from __future__ import annotations

import sqlite3
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import column, create_engine, func, inspect, select, table, text


def sqlite_path(database_url: str) -> Path | None:
    if database_url.startswith("sqlite:///"):
        return Path(database_url.removeprefix("sqlite:///"))
    return None


def online_backup(database_url: str, dest: Path, *, pages_per_step: int = 2000) -> int:
    """把库在线拷到 dest（会覆盖）。返回字节数。每拷 pages_per_step 页让一下写锁，不卡网站。"""
    src_path = sqlite_path(database_url)
    if src_path is None:
        raise NotImplementedError("只有 SQLite 能在线备份；PostgreSQL 用托管库的自动备份或 pg_dump")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True, timeout=30)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst, pages=pages_per_step, sleep=0.01)
    finally:
        dst.close()
        src.close()
    return dest.stat().st_size


def integrity(db_file: Path) -> str:
    """SQLite 完整性检查：好的返回 ok。"""
    eng = create_engine(f"sqlite:///{db_file}")
    try:
        with eng.connect() as c:
            rows = [r[0] for r in c.execute(text("PRAGMA integrity_check"))]
    finally:
        eng.dispose()
    return "ok" if rows == ["ok"] else "；".join(str(r) for r in rows[:5])


def facts(url: str, specs: list[Any]) -> dict[str, str | int | None]:
    """按 specs（key、table、agg：count / sum_decimal / sum_int、column）数核对数；表不存在的记 None。"""
    eng = create_engine(url)
    out: dict[str, str | int | None] = {}
    try:
        insp = inspect(eng)
        with eng.connect() as c:
            for sp in specs:
                key, tname, agg, col = (sp["key"], sp["table"], sp["agg"], sp.get("column", "")) if isinstance(sp, dict) else (
                    sp.key, sp.table, sp.agg, sp.column)
                if not insp.has_table(tname):
                    out[key] = None
                    continue
                t = table(tname, column(col)) if col else table(tname)
                if agg == "count":
                    out[key] = int(c.execute(select(func.count()).select_from(t)).scalar() or 0)
                elif agg == "sum_int":
                    out[key] = int(c.execute(select(func.coalesce(func.sum(t.c[col]), 0))).scalar() or 0)
                else:
                    total = Decimal("0")
                    for (v,) in c.execute(select(t.c[col])):
                        try:
                            total += Decimal(str(v)) if v not in (None, "") else 0
                        except InvalidOperation:
                            continue
                    out[key] = f"{total:.2f}"
    finally:
        eng.dispose()
    return out
