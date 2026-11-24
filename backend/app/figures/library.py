"""图库：引擎 + 出处 + 图片，给接口用的那一层。

- 进程里只建一份（`get_library` 按引擎路径缓存）：索引 7349 条、向量 30 MB，加载一次约 1 秒。
- 对外只给「号」和缩略图 / 预览图的网址；原图路径只在 `original_file()` 里用，不出这个模块。
"""

from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.figures.engine import FigureEngine, load_engine

log = logging.getLogger("app.figures.library")

# 按「这张图在汇报里干什么用」分四组（PRD P0-1）
GROUPS = [
    ("why", "为什么做", ("W",)),
    ("design", "研究设计", ("P", "S", "D")),
    ("analysis", "分析", ("A",)),
    ("results", "结果", ("R",)),
]
TIER = {1: "正刊", 2: "子刊", 3: "学科好刊"}
NOT_JOURNAL = re.compile(r"预印本|wikipedia|wikimedia|讲义|tutorial|the effect|causal inference", re.I)
_SMALL = {"of", "and", "the", "in", "for", "on", "&", "a", "an", "to"}


def thumb_url(fid: int, asset_base: str = "") -> str:
    """缩略图网址。asset_base（FIGURE_ASSET_BASE）有值时直接给对象存储 / CDN 的地址。"""
    base = asset_base.strip().rstrip("/")
    return f"{base}/thumb/{fid}.webp" if base else f"/api/figures/{fid}/thumb"


def preview_url(fid: int, asset_base: str = "") -> str:
    base = asset_base.strip().rstrip("/")
    return f"{base}/preview/{fid}.webp" if base else f"/api/figures/{fid}/preview"


def tier_label(d: dict) -> str:
    if d.get("档") in TIER:
        return TIER[d["档"]]
    src = d.get("来源") or ""
    if src.startswith("中文期刊"):
        return "中文期刊"
    if src.startswith("预印本"):
        return "预印本"
    if src.startswith("教材讲义"):
        return "教材讲义"
    return ""


def _journal_tokens(name: str) -> list[str]:
    name = re.sub(r"\(.*?\)|（.*?）|:.*$", "", name.lower())
    return [t for t in re.findall(r"[a-z0-9]+|[一-鿿]+", name) if t not in _SMALL]


def _same_journal(a: list[str], b: list[str]) -> bool:
    """「J Youth Adolesc」和「Journal of Youth and Adolescence」算同一本：词数一样，每个缩写词是全称词的开头。"""
    if len(a) != len(b) or not a:
        return False
    return all(x.startswith(y) or y.startswith(x) for x, y in zip(a, b))


def count_journals(names: list[str]) -> int:
    """库里来自多少本期刊：去掉预印本、教材讲义，大小写、缩写和全称算同一本。"""
    groups: list[list[str]] = []
    for name in sorted(set(names), key=len, reverse=True):
        if not name.strip() or NOT_JOURNAL.search(name):
            continue
        toks = _journal_tokens(name)
        if not toks:
            continue
        if not any(_same_journal(toks, g) for g in groups):
            groups.append(toks)
    return len(groups)


@dataclass
class Source:
    doi: str = ""
    link: str = ""
    caption: str = ""
    authors: str = ""


class Library:
    def __init__(
        self, engine: FigureEngine, academic_root: Path, sources: dict[int, Source], asset_base: str = ""
    ) -> None:
        self.engine = engine
        self.root = academic_root.resolve()
        self.sources = sources
        self.asset_base = asset_base.strip().rstrip("/")  # 有值 = 图走对象存储，不读原图
        docs = engine.docs
        self.type_counts: dict[str, int] = {c: 0 for c in engine.names}
        for d in docs:
            c = d["h"]["主图型"]
            if c in self.type_counts:
                self.type_counts[c] += 1
        self.total = len(docs)
        self.journals = count_journals([d["期刊"] for d in docs])
        self._caption_cap = max((len(d["图注"] or "") for d in docs), default=0)
        # 叠在索引上的一层（figures/overlay.py 从 figure_overrides 读）：下架的号、审过的改标签
        self.hidden: frozenset[int] = frozenset()
        self.overrides: dict[int, dict[str, Any]] = {}

    def set_overlay(self, hidden: set[int], overrides: dict[int, dict[str, Any]]) -> None:
        """换一层叠加（审核通过、下架后马上调；整份替换，读的线程看到的要么全旧要么全新）。"""
        self.overrides = dict(overrides)
        self.hidden = frozenset(hidden)

    def visible(self, fid: int) -> bool:
        """下架的图（版权方要求删除）网站上不再出现：搜索、浏览、详情、更多类似、开放接口都按它过滤。"""
        return fid not in self.hidden

    def code_of(self, d: dict) -> str:
        code = self.overrides.get(d["号"], {}).get("code")
        return code if code in self.engine.names else d["h"]["主图型"]

    # ---- 基本信息 ----
    def type_name(self, code: str) -> str:
        return self.engine.names.get(code, "")

    def groups(self) -> list[dict[str, Any]]:
        out = []
        for key, title, prefixes in GROUPS:
            types = [
                {"code": c, "name": n, "count": self.type_counts.get(c, 0)}
                for c, n in self.engine.names.items()
                if c.startswith(prefixes)
            ]
            out.append({"key": key, "title": title, "types": types})
        return out

    def card(self, d: dict) -> dict[str, Any]:
        code = self.code_of(d)
        what = self.overrides.get(d["号"], {}).get("what")
        return {
            "id": d["号"],
            "thumb_url": thumb_url(d["号"], self.asset_base),
            "title": what or d["h"].get("讲的是什么") or d["题目"],
            "journal": d["期刊"],
            "year": str(d["年份"] or ""),
            "tier": tier_label(d),
            "type_code": code,
            "type_name": self.type_name(code),
        }

    def browse(self, code: str, offset: int, limit: int) -> tuple[int, list[dict]]:
        rows = [d for d in self.engine.docs if self.code_of(d) == code and self.visible(d["号"])]
        rows.sort(key=lambda d: (d["档"] if d["档"] in TIER else 9, -_year(d), d["号"]))
        return len(rows), [self.card(d) for d in rows[offset : offset + limit]]

    def detail(self, fid: int) -> dict[str, Any] | None:
        d = self.engine.doc(fid)
        if d is None or not self.visible(fid):
            return None
        h = d["h"]
        src = self.sources.get(fid, Source())
        caption = src.caption or d["图注"] or ""
        truncated = not src.caption and self._caption_cap > 0 and len(caption) >= self._caption_cap
        code = self.code_of(d)
        types = [{"code": code, "name": self.type_name(code)}] + [
            {"code": c, "name": self.type_name(c)} for c in (h.get("次图型") or []) if c in self.engine.names
        ]
        return {
            **self.card(d),
            "preview_url": preview_url(fid, self.asset_base),
            "paper_title": d["题目"],
            "authors": src.authors,
            "doi": src.doi,
            "link": src.link,
            "caption": caption + ("…" if truncated else ""),
            "cite": self.cite(d, src),
            "types": types,
            "tags": [
                {"label": label, "words": _as_list(h.get(key))}
                for label, key in (  # 「讲的是什么」就是详情页的大标题，不再重复放
                    ("研究的情况", "研究的情况"),
                    ("方法范式", "方法范式"),
                    ("手段", "手段"),
                    ("画面上有什么", "画面上有什么"),
                    ("结构", "结构"),
                )
                if _as_list(h.get(key))
            ],
            "credits": list(self.overrides.get(fid, {}).get("credits", [])),
        }

    @staticmethod
    def cite(d: dict, src: Source) -> str:
        """复制出处：作者或题目, 年份, 期刊, DOI（有 DOI 写 DOI，没有写原文链接）。"""
        who = src.authors or (d["题目"] or "").rstrip(".")
        parts = [p for p in (who, str(d["年份"] or ""), d["期刊"]) if p]
        if src.doi:
            parts.append(f"doi:{src.doi}")
        elif src.link:
            parts.append(src.link)
        return ", ".join(parts)

    # ---- 原图（只在本模块里用）----
    def original_file(self, fid: int) -> Path | None:
        """本机原图（生成缩略图 / 预览图用）。图走对象存储时（服务器上）一律不读原图。"""
        if self.asset_base:
            return None
        d = self.engine.doc(fid)
        if d is None or not d.get("文件"):
            return None
        p = (self.root / d["文件"]).resolve()
        if self.root not in p.parents or not p.is_file():
            return None
        return p


def _as_list(v: Any) -> list[str]:
    if not v:
        return []
    return [v] if isinstance(v, str) else [str(x) for x in v if str(x).strip()]


def _year(d: dict) -> int:
    try:
        return int(str(d["年份"])[:4])
    except ValueError:
        return 0


def load_sources(path: Path) -> dict[int, Source]:
    """离线脚本 scripts/figures_build_sources.py 合成的 出处.json。没有就返回空（详情页只写期刊和题目）。"""
    if not path.is_file():
        log.warning("没有出处文件 %s：详情页不放原文链接和完整图注（先跑 scripts/figures_build_sources.py）", path)
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for k, v in (data.get("条目") or {}).items():
        out[int(k)] = Source(
            doi=v.get("doi", ""), link=v.get("链接", ""), caption=v.get("图注", ""), authors=v.get("作者", "")
        )
    return out


_ENGINES: dict[tuple, FigureEngine] = {}
_ENGINES_LOCK = threading.Lock()


def get_engine(engine_path: Path, *, embed_url: str = "", embed_timeout: float = 2.0) -> FigureEngine:
    """进程里同样的配置只加载一次（索引 7349 条、向量 30 MB，约 1 秒；测试里几十个 app 共用一份）。"""
    key = (str(engine_path), embed_url, embed_timeout)
    with _ENGINES_LOCK:
        engine = _ENGINES.get(key)
        if engine is None:
            engine = load_engine(engine_path, embed_url=embed_url, embed_timeout=embed_timeout)
            _ENGINES[key] = engine
            log.info(
                "找图引擎加载好了：%d 张，语义检索%s",
                len(engine.docs),
                "能用" if engine.semantic else f"没用上（{engine.vector_note}）",
            )
        return engine
