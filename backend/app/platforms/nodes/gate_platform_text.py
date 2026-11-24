"""gate.platform_text 发货文案过红线。"""

from __future__ import annotations

from urllib.parse import urlparse

from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.platforms import profiles, redline
from app.platforms.models_io import TextIn, TextOut


def handler(call: NodeCall, data: TextIn) -> NodeResult:
    prof = profiles.get(call.db, data.platform) or {}
    tier = "platform_dy" if data.platform == "dy" else "platform"
    text = data.text
    for own in data.allow:  # 激活码是我们随机生成的（PSY- + 9 位大写字母数字），会碰巧拼出词表里的两个字母，不算导流
        if own:
            text = text.replace(own, " ")
    hits = redline.find(text, tier)
    host = (urlparse(call.ctx.public_base_url).hostname or "").lower()
    hits += redline.find_urls(text, () if prof.get("allow_url") is False else (host,))
    if hits:
        run_node_text = f"发货文案没发出去：里面有 {'、'.join(hits)}"
        return NodeResult(exit="blocked", output=TextOut(hits=hits), detail=run_node_text)
    return NodeResult(exit="clean", output=TextOut())


CARD = NodeCard(
    id="gate.platform_text",
    name="发货文案过红线",
    description="往任何平台写发货内容、导出给发货工具之前，查文案里有没有微信号、二维码、「加微信」、谐音、别的平台名这些导流字，"
                "以及兑换网址以外的网址；有就不发，通知 Edison。",
    category="关口",
    tech=["纯 Python", "词表 app/platforms/redline.py（只有这一份，check.py 规矩 11、获客的 copy.lint 也读它）"],
    input_model=TextIn,
    output_model=TextOut,
    exits=[NodeExit(key="clean", label="干净，可以发", kind="ok"), NodeExit(key="blocked", label="有不许出现的字，没发", kind="fail")],
    config=["redline.TIERS / PATTERNS：词表和样式（平台档，抖音再加一档）",
            "profiles.json 每个渠道的 allow_url：查实某平台不许放外部网址时关掉，那时网址也算命中",
            "兑换网址的域名（PUBLIC_BASE_URL）是唯一放行的网址"],
    emits=["无（调用方记 platforms.* 事件、发飞书）"],
    listens=["无"],
    replaceable=["词表跟模块 G 的导流红线调研更新"],
    failure="拦下不重试，等人改发货模板（订单中枢设置 delivery_templates）。静态扫描是 check.py 规矩 11，这里运行时再拦一道。"
            "调用方把这一单的激活码放进 allow：随机码里约 2.4% 会碰巧出现 VX、QQ、WX 这类词表里的字母组合，不能因此拦下。",
    owner="C",
    status="要新做",
)
register(CARD, handler)
