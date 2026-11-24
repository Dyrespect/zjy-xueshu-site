"""搜索页：把引擎的结果按路分组、配上「这组学什么」，记一笔搜索记录。"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any

from sqlalchemy.orm import Session

from app.figures.engine import EngineSearch, is_relevant
from app.figures.library import Library
from app.figures.models import SearchLog

CACHE_SIZE = 256
CACHE_SECONDS = 1800

# 引擎 learn() 的文案改成给人看的话（PRD P0-2「结果按路分组显示」）
LANE_CLOSE = ("close", "最像你要画的", "看整体怎么摆、放了哪些东西")
LANE_SHAPE = ("shape", "同一种画法", "学骨架：怎么分块、怎么排")
LANE_OTHER = ("other", "别的图型里画同一样东西的", "只借它画这样东西的方式")
EXTRA_LEARN = {
    "去掉": "去掉库里没有的词，用其余的词找",
    "上一层": "这一类图通常怎么画",
    "相邻": "相邻图型里画法相近的",
}


class SearchCache:
    def __init__(self) -> None:
        self._data: OrderedDict[tuple[str, str], tuple[float, dict]] = OrderedDict()
        self._lock = threading.Lock()

    def clear(self) -> None:
        """叠加层变了（下架、改标签）：缓存里的结果作废。"""
        with self._lock:
            self._data.clear()

    def get(self, key: tuple[str, str]) -> dict | None:
        with self._lock:
            hit = self._data.get(key)
            if hit is None or time.monotonic() - hit[0] > CACHE_SECONDS:
                return None
            self._data.move_to_end(key)
            return hit[1]

    def put(self, key: tuple[str, str], value: dict) -> None:
        with self._lock:
            self._data[key] = (time.monotonic(), value)
            self._data.move_to_end(key)
            while len(self._data) > CACHE_SIZE:
                self._data.popitem(last=False)


def _lane(angle: str) -> tuple[str, str, str]:
    if angle.startswith("同方法："):
        w = angle[4:]
        return (f"method:{w}", f"同样用了「{w}」的研究", "学这个领域、这种方法的惯例")
    if angle == "同画法":
        return LANE_SHAPE
    return LANE_CLOSE


def build_groups(lib: Library, res: EngineSearch) -> list[dict[str, Any]]:
    groups: OrderedDict[str, dict[str, Any]] = OrderedDict()

    def add(lane: tuple[str, str, str], rows: list[dict]) -> None:
        key, title, learn = lane
        g = groups.setdefault(key, {"key": key, "title": title, "learn": learn, "cards": []})
        g["cards"].extend(lib.card(r["d"]) for r in rows if is_relevant(r) and lib.visible(r["d"]["号"]))

    if res.main is not None:
        add(LANE_CLOSE, [])  # 「最像」永远排第一
        for r in res.main.same:
            add(_lane(str(r.get("角度", ""))), [r])
        add(LANE_SHAPE, [])
        add(LANE_OTHER, res.main.other)
    for key, title, rows in res.extras:
        add((f"extra:{key}", title, EXTRA_LEARN.get(key, "")), rows)
    return [g for g in groups.values() if g["cards"]]


def payload(lib: Library, res: EngineSearch, query: str, overridden: bool) -> dict[str, Any]:
    groups = build_groups(lib, res)
    guess = {"code": res.guess, "name": lib.type_name(res.guess)} if res.guess else None
    return {
        "query": query,
        "words": [{"word": w, "count": res.word_counts.get(w, 0)} for w in res.split.words],
        "zero_words": res.zero_words,
        "guess": guess,
        "code": res.code,
        "code_name": lib.type_name(res.code) or "不限图型",
        "overridden": overridden,
        "groups": groups,
        "total": sum(len(g["cards"]) for g in groups),
        "_used_vectors": res.used_vectors,
    }


def run_search(
    db: Session,
    lib: Library,
    cache: SearchCache,
    query: str,
    code: str | None,
    *,
    caller: str = "web",
    src: str = "",
    visitor: str = "",
    client: str = "",
) -> dict[str, Any]:
    query = " ".join((query or "").split())[:200]
    code = lib.engine.norm_code(code) if code else None
    started = time.monotonic()
    key = (query, code or "")
    body = cache.get(key)
    if body is None:
        res = lib.engine.full_search(query, code)
        body = payload(lib, res, query, overridden=code is not None)
        # 向量这次没用上（小服务超时）的不缓存：下次再试
        if body["_used_vectors"] or not lib.engine.semantic:
            cache.put(key, body)
    took = int((time.monotonic() - started) * 1000)
    log = SearchLog(
        query=query,
        guess=(body["guess"] or {}).get("code", ""),
        code=body["code"],
        overridden=body["overridden"],
        words=[w["word"] for w in body["words"]],
        zero_words=body["zero_words"],
        groups=[{"key": g["key"], "title": g["title"], "n": len(g["cards"])} for g in body["groups"]],
        total=body["total"],
        used_vectors=body["_used_vectors"],
        took_ms=took,
        caller=caller[:8],
        src=src[:32],
        visitor=visitor[:40],
        client=client[:60],
    )
    db.add(log)
    db.commit()
    out = {k: v for k, v in body.items() if not k.startswith("_")}
    out["search_id"] = log.id
    return out
