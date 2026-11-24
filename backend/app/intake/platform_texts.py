"""发给平台买家的字（写进小红书、抖音、闲鱼、发卡站、自有网页那一单的发货内容）。

激活码交付方案第 6 节：全平台同一句，只有激活码和兑换网址；有的平台不许放站外网址，所以能按平台换模板
（模块 B 的渠道档案里写 delivery_template：code_and_url / code_only），模板文字在设置 delivery_templates 里。
三个平台都在罚导流：模板里不许出现微信号、二维码、「加微信」、谐音。红线词表只有一份：
app/platforms/redline.py（scripts/check.py 规矩 11 静态扫这里的默认模板和 platforms/；后台保存设置时也拦）。
契约：docs/任务单/06_订单中枢契约.md 第六节。
"""

from __future__ import annotations

from typing import Any

DEFAULT_TEMPLATES: dict[str, str] = {
    "code_and_url": "激活码：{code}\n打开 {url} 查看并兑换。",
    "code_only": "激活码：{code}",
}


def delivery_text(code: str, base_url: str, template: str = "code_and_url", templates: dict[str, str] | None = None) -> str:
    """填一句发货内容。base_url 是兑换网页的站点地址（PUBLIC_BASE_URL），网址 = {base_url}/c/{code}。"""
    tpls = {**DEFAULT_TEMPLATES, **(templates or {})}
    if template not in tpls:
        raise ValueError(f"没有发货模板 {template}（有：{'、'.join(tpls)}）")
    return tpls[template].format(code=code, url=f"{base_url.rstrip('/')}/c/{code}")


def delivery_text_for(db: Any, code: str, base_url: str, template: str = "code_and_url") -> str:
    """同上，模板文字读设置里的 delivery_templates。"""
    from app.intake.config_store import load_config

    return delivery_text(code, base_url, template, load_config(db).delivery_templates)
