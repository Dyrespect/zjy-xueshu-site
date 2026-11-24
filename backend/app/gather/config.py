"""后台「聚人设置」：运行中改一项就生效的东西（存 gather_settings 表；没存过的用这里的默认值）。

- verifier：核验方式，改这一项就换（07 第十五节卡 5「可换」；流程文件一个字不改）。
- plugin_name：插件对外的名字（Edison 还没定，先用设计里推荐的「PsyEngine 图库插件」）。
- 几段文案：链接只在 figure_packs 表里（后台「网盘链接」），模板里只有 {url} 这类占位，不写死。
「转发换下载」的说法只许出现在网页弹层里：公众号关键词回复（gzh_reply_text）不许带（07 第六节第 7 条，check.py 规矩 17）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.gather.models import GatherSetting

VERIFIERS: dict[str, str] = {
    "screenshot_trust": "转发核验：交截图就发链接，截图留着抽查（默认）",
    "follow_gzh": "关注公众号：网页不发链接，引导去公众号回复关键词",
    "share_visits": "专属链接带来 N 个新访客就自动发",
    "manual": "交截图后等负责人在后台看过再发",
}

# 公众号关键词回复、落地页正文里不许出现的说法（只许在「要全部图库？」弹层里）
FORWARD_PHRASES = ("转发到朋友圈", "5 人以上的群", "五人以上的群", "转发后")

DEFAULTS: dict[str, Any] = {
    "unlock_enabled": True,
    "verifier": "screenshot_trust",
    "share_visits_n": 3,
    "plugin_name": "PsyEngine 图库插件",
    "gzh_name": "PsyEngine",
    "gzh_keyword": "图库",
    "share_text": "心理学论文里的图，一句话就能找到，每张都带出处：{url}",
    "pack_text": "全部图库（{version} 版，{count} 张，图片和标签一起）：{url}{code_part}\n"
                 "图库每月更新，新版在公众号 {gzh} 发。要做汇报 PPT：{order_url}",
    "gzh_reply_text": "精选小包（每个图型 10 张，共 {count} 张）：{url}{code_part}\n一句话找图、全部图库：{figures_url}",
    "follow_note": "不想转发？在公众号 {gzh} 回复「{keyword}」，先拿精选小包（每个图型 10 张）。",
    "cta_text": "做汇报 PPT 看这里",
    "ai_note": "全部图库、一句话找图：{figures_url}　做汇报 PPT：{order_url}",
    "takedown_hours": 48,
}

LABELS: dict[str, str] = {
    "unlock_enabled": "网页上开放「要全部图库？」",
    "verifier": "核验方式",
    "share_visits_n": "「带来 N 个新访客」里的 N",
    "plugin_name": "插件对外的名字",
    "gzh_name": "公众号名字",
    "gzh_keyword": "公众号回复的关键词",
    "share_text": "复制分享链接时带的那句话（{url} 是链接）",
    "pack_text": "发全量链接的那段话（{version} {count} {url} {code_part} {gzh} {order_url}）",
    "gzh_reply_text": "公众号关键词回复（小包；{count} {url} {code_part} {figures_url}）",
    "follow_note": "弹层最后一行（公众号那条路；{gzh} {keyword}）",
    "cta_text": "图库页头的导流入口",
    "ai_note": "插件每次返回末尾那行（{figures_url} {order_url}）",
    "takedown_hours": "版权问题多少小时内下架",
}


class ConfigError(ValueError):
    pass


def load_config(db: Session) -> dict[str, Any]:
    cfg = dict(DEFAULTS)
    for row in db.scalars(select(GatherSetting)):
        if row.key in DEFAULTS:
            cfg[row.key] = row.value
    return cfg


def validate(key: str, value: Any) -> Any:
    if key not in DEFAULTS:
        raise ConfigError(f"没有这一项设置：{key}")
    default = DEFAULTS[key]
    if isinstance(default, bool):
        return bool(value)
    if isinstance(default, int):
        try:
            v = int(value)
        except (TypeError, ValueError):
            raise ConfigError(f"「{LABELS[key]}」要填数字") from None
        if v < 1 or v > 1000:
            raise ConfigError(f"「{LABELS[key]}」要在 1 到 1000 之间")
        return v
    v = str(value or "").strip()
    if not v:
        raise ConfigError(f"「{LABELS[key]}」不能空着；不想要就恢复默认")
    if key == "verifier" and v not in VERIFIERS:
        raise ConfigError(f"核验方式只能是：{'、'.join(VERIFIERS)}")
    if key == "gzh_reply_text":
        hit = [p for p in FORWARD_PHRASES if p in v]
        if hit:
            raise ConfigError(f"公众号回复里不能写「{hit[0]}」：公众号发起诱导分享罚的是公众号本身（运营规范 3.3.1），"
                              "转发换下载只放在网页弹层里（07 设计第六节第 7 条）")
    if len(v) > 600:
        raise ConfigError(f"「{LABELS[key]}」太长了（600 字以内）")
    return v


def save_config(db: Session, values: dict[str, Any]) -> dict[str, Any]:
    clean = {k: validate(k, v) for k, v in values.items()}
    now = utcnow()
    for k, v in clean.items():
        row = db.get(GatherSetting, k)
        if row is None:
            db.add(GatherSetting(key=k, value=v, updated_at=now))
        else:
            row.value = v
            row.updated_at = now
    db.flush()
    return load_config(db)
