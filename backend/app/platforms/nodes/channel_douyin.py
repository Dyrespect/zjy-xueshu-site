"""channel.douyin 抖音（P2，只登记说明卡）。"""

from __future__ import annotations

from app.core.nodes import NodeCard, NodeExit, register
from app.platforms.models_io import PlatformIn, PlatformOut

CARD = NodeCard(
    id="channel.douyin",
    name="抖音",
    description="抖店订单付款后给这一单写激活码，完成或退款时告诉订单中枢。抖音不急（Edison），接口待对文档，现在只有说明卡。",
    category="渠道",
    tech=["订阅已付款消息 → 订单详情接口拿买家号 → 写发货内容（接口待对文档）", "存量订单搜索接口补漏",
          "完成、售后消息 tag 待 Edison 截图（激活码交付方案第 6 节）", "适配器占位 app/platforms/douyin.py"],
    input_model=PlatformIn,
    output_model=PlatformOut,
    exits=[NodeExit(key="delivered", label="写进发货内容了", kind="ok"),
           NodeExit(key="signal_applied", label="平台信号交给订单中枢了", kind="ok"),
           NodeExit(key="exists", label="来过", kind="ok"),
           NodeExit(key="blocked", label="买家退款作废太多次，没发码", kind="fail"),
           NodeExit(key="text_blocked", label="发货文案过不了红线", kind="fail"),
           NodeExit(key="invalid", label="推送验签没过", kind="fail"),
           NodeExit(key="fail", label="出错", kind="fail")],
    config=["App Key / Secret（.env，还没有）", "profiles.json 的 dy 一行（现在 enabled=false，模板只放激活码）"],
    emits=["无"],
    listens=["无"],
    replaceable=["暂无"],
    failure="推送验签、按消息 id 去重、漏单靠订单搜索补拉（都还没写）。",
    owner="C",
    status="要新做",
)
register(CARD)
