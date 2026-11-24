"""叠在索引上的一层：审过的改标签、版权下架（模块 L，07 设计第六节第 3 条、第八节 figure_overrides）。

索引文件（学术汇报里的 图库索引_新.jsonl）只读不改；网站读时把这一层合并上去。改动后马上 refresh，搜索缓存清掉。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.notify import Notifier
from app.figures.models import FigureOverride

FIELDS = ("what", "code", "hidden")


@dataclass
class FiguresCtx:
    """figures 节点要的运行环境（app.state 上的东西）。别的模块调 figure.search / figure.ai_tool 时照这个给。

    figures_url：图库网站的网址前缀（拼详情页地址；空 = 只给 / 开头的相对地址）。
    """

    figure_library: Any
    figure_cache: Any
    notifier: Notifier | None = None
    figures_url: str = ""
    ai_note: str = ""
    takedown_hours: int = 48


def load_overlay(db: Session) -> tuple[set[int], dict[int, dict[str, Any]]]:
    hidden: set[int] = set()
    over: dict[int, dict[str, Any]] = {}
    rows = db.scalars(select(FigureOverride).where(FigureOverride.active.is_(True)).order_by(FigureOverride.id)).all()
    for r in rows:
        if r.field == "hidden":
            if r.value:
                hidden.add(r.figure_id)
            continue
        o = over.setdefault(r.figure_id, {"credits": []})
        o[r.field] = r.value
        if r.credit and f"标签由 {r.credit} 改过" not in o["credits"]:
            o["credits"].append(f"标签由 {r.credit} 改过")
    return hidden, over


def refresh(db: Session, lib: Any, cache: Any = None) -> None:
    """从库里重读叠加层装到 Library 上；搜索缓存作废。lib 没加载（图库 503）时什么都不做。"""
    if lib is None:
        return
    hidden, over = load_overlay(db)
    lib.set_overlay(hidden, over)
    if cache is not None:
        cache.clear()


def hidden_ids(db: Session) -> set[int]:
    """打包脚本、开放接口用：下架了哪些号。"""
    return load_overlay(db)[0]
