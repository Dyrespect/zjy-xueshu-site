"""聚人模块的运行环境：每个请求拼一个 GatherCtx 交给节点（NodeCall.ctx）。

figures 的节点（figure.search、figure.ai_tool）也吃这个 ctx：它要的 figure_library、figure_cache、figures_url、ai_note 都在。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fastapi import Request

from app.core.notify import Notifier
from app.core.storage import Storage
from app.gather.settings import GatherSettings


@dataclass
class GatherCtx:
    settings: GatherSettings
    storage: Storage
    notifier: Notifier
    figure_library: Any = None
    figure_cache: Any = None
    figures_url: str = ""  # 图库网址前缀（绝对）：拼分享链接、插件返回的详情页地址
    ai_note: str = ""
    cfg: dict[str, Any] = field(default_factory=dict)


def gather_settings(request: Request) -> GatherSettings:
    st = request.app.state
    gs = getattr(st, "gather_settings", None)
    if gs is None:
        gs = GatherSettings()
        st.gather_settings = gs
    return gs


def build_ctx(request: Request, cfg: dict[str, Any] | None = None) -> GatherCtx:
    st = request.app.state
    gs = gather_settings(request)
    figures_url = gs.SITE_FIGURES_URL.strip().rstrip("/") or str(request.base_url).rstrip("/")
    return GatherCtx(gs, st.storage, st.notifier, getattr(st, "figure_library", None), getattr(st, "figure_cache", None),
                     figures_url, "", cfg or {})
