"""适配器清单：（渠道, 实现名）→ 适配器。渠道档案的 adapter 选哪一个。加一种实现 = 写一个类 + 在这里加一行。"""

from __future__ import annotations

from typing import Any

from app.platforms.douyin import DouyinOpenApi
from app.platforms.xhs import XhsFixedLink, XhsManualPaste
from app.platforms.xianyu import XianyuManual

ADAPTERS: dict[tuple[str, str], type] = {
    ("xhs", "manual_paste"): XhsManualPaste,
    ("xhs", "fixed_link"): XhsFixedLink,
    ("xy", "manual"): XianyuManual,
    ("dy", "openapi"): DouyinOpenApi,
}


def get_adapter(platform: str, name: str) -> Any:
    cls = ADAPTERS.get((platform, name))
    if cls is None:
        raise ValueError(f"没有适配器 {platform}/{name}")
    return cls()
