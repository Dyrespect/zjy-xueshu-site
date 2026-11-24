"""业务读数的接口位：运维不 import 业务模块，业务的读数由后台这一层（app/admin/ops_sources.py）登记进来。

五种接口位（每种都是「名字 → 函数」，同名后登记的覆盖先登记的）：
- gauge   仪表读数：fn(db, app) -> list[Gauge]               水印队列、做单产能……（计数落库时每 5 分钟读一次、深检查时读一次）
- todo    待处理事项：fn(db, app) -> list[TodoGroup]          待开票、待核对订单号、待贴文案、超时没交的单……（日报、运维页）
- suggestion 新建议：fn(db, start, end) -> list[SuggestionGroup]  图库标签反馈、提需求、投图、网站意见（日报）
- external 外部依赖：fn(app) -> list[ExternalTarget]          支付网关、DeepSeek、微信客服……（深检查；只说配没配和连哪个地址，不给密钥）
- lifecycle 保存期限盘点：fn(db, cfg_items) -> list[LifecycleRow]  过了保存期限的客户材料、水印图……有多少（只数不删）

都是只读；某个函数出错，运维照样出结果，那一项写「没读到：原因」。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

log = logging.getLogger("app.ops.sources")


class Gauge(BaseModel):
    key: str  # 例 watermark.rendering
    label: str
    value: float | None
    unit: str = ""
    detail: str = ""
    link: str = ""


class TodoGroup(BaseModel):
    kind: str
    label: str  # 待开票、待核对订单号……
    count: int
    link: str  # 后台页面（相对地址 /admin/...）
    latest: list[str] = Field(default_factory=list)  # 最新几条的一句话（已经不含手机号、税号这类）
    level: str = "today"  # urgent | today | info


class SuggestionGroup(BaseModel):
    kind: str
    label: str  # 标签反馈、提需求、投图、网站意见
    count: int
    link: str
    latest: list[str] = Field(default_factory=list)  # 最新几条的标题（截短，不含联系方式）


class ExternalTarget(BaseModel):
    key: str
    label: str
    url: str  # 只连这个地址看通不通（HEAD / GET 首页），不带密钥
    configured: bool
    note: str = ""


class LifecycleRow(BaseModel):
    key: str
    label: str
    days: int | None
    expired: int | None  # 过了期限的有几条（None = 读不到 / 期限没定）
    note: str = ""


GaugeFn = Callable[[Any, Any], list[Gauge]]
TodoFn = Callable[[Any, Any], list[TodoGroup]]
SuggestionFn = Callable[[Any, datetime, datetime], list[SuggestionGroup]]
ExternalFn = Callable[[Any], list[ExternalTarget]]
LifecycleFn = Callable[[Any, list[Any]], list[LifecycleRow]]

_REG: dict[str, dict[str, Callable[..., Any]]] = {k: {} for k in ("gauge", "todo", "suggestion", "external", "lifecycle")}


def register(kind: str, name: str, fn: Callable[..., Any]) -> None:
    if kind not in _REG:
        raise ValueError(f"没有这种接口位：{kind}")
    _REG[kind][name] = fn


def names(kind: str) -> list[str]:
    return sorted(_REG[kind])


def collect(kind: str, *args: Any) -> tuple[list[Any], list[str]]:
    """跑某种接口位的全部函数：返回（结果合在一起，出错的说明）。"""
    out: list[Any] = []
    errors: list[str] = []
    for name, fn in sorted(_REG[kind].items()):
        try:
            out.extend(fn(*args))
        except Exception as e:  # noqa: BLE001  一个读数坏了不影响别的
            log.warning("运维读数 %s/%s 出错：%s", kind, name, type(e).__name__)
            errors.append(f"{name} 没读到：{type(e).__name__}")
    return out, errors
