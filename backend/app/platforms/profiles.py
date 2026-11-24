"""渠道档案：profiles.json 是默认值，后台改过的（用哪个适配器实现、开没开）存在 platforms_profiles 表里盖过它。

加一个新渠道：写一个适配器 + 一个渠道节点文件，在 profiles.json 加一行，后台登记商品。订单中枢、支付、别的渠道都不用动。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.platforms.models import PlatformsProfile

PROFILE_FILE = Path(__file__).with_name("profiles.json")
PLATFORM_NODES = {"xhs": "channel.xhs", "xy": "channel.xianyu", "dy": "channel.douyin"}


@lru_cache(maxsize=1)
def defaults() -> dict[str, dict[str, Any]]:
    data = json.loads(PROFILE_FILE.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def load(db: Session) -> dict[str, dict[str, Any]]:
    out = {k: dict(v) for k, v in defaults().items()}
    for row in db.scalars(select(PlatformsProfile)):
        p = out.get(row.platform)
        if p is None:
            continue
        if row.adapter in p.get("adapters", []):
            p["adapter"] = row.adapter
        p["enabled"] = bool(row.enabled)
    for p in out.values():
        p["mode"] = intake_mode(p)
    return out


def get(db: Session, platform: str) -> dict[str, Any] | None:
    return load(db).get(platform)


def intake_mode(p: dict[str, Any]) -> str:
    """收单段：固定链接 = 买家填订单号 → 负责人核对 → 建单（verify_then_create），码只在我们页面上，发货文案不用过红线。"""
    return "verify_then_create" if p.get("adapter") == "fixed_link" else str(p.get("intake", "parse_paid"))


def save(db: Session, platform: str, *, adapter: str, enabled: bool, by: str) -> dict[str, Any]:
    base = defaults().get(platform)
    if base is None or platform == "web":
        raise ValueError("没有这个渠道")
    if adapter not in base.get("adapters", []):
        raise ValueError(f"这个渠道没有 {adapter} 这种收单方式（有：{'、'.join(base.get('adapters', []))}）")
    row = db.get(PlatformsProfile, platform)
    if row is None:
        row = PlatformsProfile(platform=platform)
        db.add(row)
    row.adapter, row.enabled, row.by, row.updated_at = adapter, enabled, by, utcnow()
    db.flush()
    return load(db)[platform]
