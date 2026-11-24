"""统一站点地图：把 site_map.json 按 .env 里三块的网址前缀拼成链接（不写死域名；空 = 同域相对地址）。"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from app.gather.settings import GatherSettings

SITE_MAP = Path(__file__).parent / "site_map.json"
SECTIONS = ("main", "app", "figures")


@lru_cache(maxsize=1)
def site_map() -> dict[str, Any]:
    return json.loads(SITE_MAP.read_text(encoding="utf-8"))


def bases(gs: GatherSettings) -> dict[str, str]:
    return {
        "main": gs.SITE_MAIN_URL.strip().rstrip("/"),
        "app": gs.SITE_APP_URL.strip().rstrip("/"),
        "figures": gs.SITE_FIGURES_URL.strip().rstrip("/"),
    }


def href(gs: GatherSettings, section: str, path: str, **query: str) -> str:
    url = bases(gs)[section] + path
    q = {k: v for k, v in query.items() if v}
    return f"{url}{'&' if '?' in url else '?'}{urlencode(q)}" if q else url


def order_url(gs: GatherSettings, placement: str) -> str:
    """去下单页，带来源（订单上的 source = tuku_<位置>，周报算「图库带来几单」）。"""
    return href(gs, "app", "/order", **{"from": f"tuku_{placement}"})


def resolved(gs: GatherSettings, viewing: str = "figures") -> dict[str, Any]:
    """给前端页头页脚用：每个链接拼好地址；从图库去下单页的带 from=tuku_nav。"""
    m = site_map()
    groups = []
    for g in m["groups"]:
        items = []
        for it in g["items"]:
            extra = {"from": "tuku_nav"} if viewing == "figures" and it["path"] == "/order" else {}
            items.append({"label": it["label"], "href": href(gs, it["section"], it["path"], **extra),
                          "section": it["section"]})
        groups.append({"key": g["key"], "title": g["title"], "items": items})
    brands = {k: {"name": v["name"], "href": href(gs, v["section"], v["path"])} for k, v in m["brands"].items()}
    return {
        "bases": bases(gs),
        "brands": brands,
        "groups": groups,
        "company": gs.SITE_COMPANY,
        "credit_code": gs.SITE_CREDIT_CODE,
        "icp": gs.SITE_ICP,
        "icp_url": "https://beian.miit.gov.cn/",
    }
