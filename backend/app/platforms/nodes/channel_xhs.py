"""channel.xhs 小红书。"""

from __future__ import annotations

from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.platforms import service
from app.platforms.models_io import PlatformIn, PlatformOut

PLATFORM = "xhs"

EXITS = [
    NodeExit(key="delivered", label="码给到买家了（固定链接页上）", kind="ok"),
    NodeExit(key="manual", label="发货文案交给负责人去平台贴", kind="wait"),
    NodeExit(key="pending_verify", label="买家填了订单号，等负责人核对", kind="wait"),
    NodeExit(key="signal_applied", label="平台信号交给订单中枢了", kind="ok"),
    NodeExit(key="exists", label="这个订单号来过，原样返回", kind="ok"),
    NodeExit(key="ignored", label="这个渠道没开 / 这种来源现在不收", kind="ok"),
    NodeExit(key="rejected", label="负责人核对没通过", kind="fail"),
    NodeExit(key="blocked", label="买家退款作废太多次，没发码", kind="fail"),
    NodeExit(key="text_blocked", label="发货文案过不了红线，没发", kind="fail"),
    NodeExit(key="invalid", label="表单、链接、订单号不对，或推送验签没过", kind="fail"),
    NodeExit(key="retry", label="写发货内容暂时失败，可以重试", kind="fail"),
    NodeExit(key="fail", label="建单失败、信号没接上", kind="fail"),
]


def handler(call: NodeCall, data: PlatformIn) -> NodeResult:
    req = data.root
    if req.op == "inbound":
        return service.ingest(call, PLATFORM, req)
    if req.op == "verify":
        return service.verify(call, PLATFORM, req)
    return service.signal(call, PLATFORM, req)


CARD = NodeCard(
    id="channel.xhs",
    name="小红书",
    description="小红书上卖出一单后，把激活码交到这一单上；订单「已完成」或退款时告诉订单中枢。"
                "小红书个人卖家拿不到接口，现在全靠 Edison 在后台点：要么录单后复制一句发货文案去贴（manual_paste），"
                "要么商品发货栏放一个固定链接、买家自己填订单号、Edison 核对后出码（fixed_link）。后台能切。",
    category="渠道",
    tech=["适配器 app/platforms/xhs.py：XhsManualPaste、XhsFixedLink（openapi 是 P2，没写）",
          "后台接口 /api/admin/platforms/*（录单、核对、平台信号）", "固定链接页 /x/:token + /api/platforms/claim",
          "run_node：order.create、gate.platform_text、confirm.receipt、order.signal、notify.feishu、code.lookup",
          "发货文案 app/intake/platform_texts.py（模板在订单中枢设置 delivery_templates）"],
    input_model=PlatformIn,
    output_model=PlatformOut,
    exits=EXITS,
    config=["profiles.json 的 xhs 一行（adapter：manual_paste / fixed_link，后台能改；delivery_template；allow_url；"
            "remind_after_paid_hours：付款多久后提醒去看已完成，先按 49 小时）", "platforms_products：商品对照、固定链接口令"],
    emits=["platforms.ingested", "platforms.pending_verify", "platforms.rejected", "platforms.blocked", "platforms.signal"],
    listens=["无"],
    replaceable=["manual_paste ↔ fixed_link ↔ openapi（P2），同一接口", "以后开模板店（电子资源自动发货）是第四种实现"],
    failure="按（渠道, 平台订单号）幂等：同一订单号录两次、填两次都返回同一个结果，填过的不把码给第二个人；"
            "固定链接页同一 IP 每小时最多提交 10 次；订单号核对前不出码；建单失败、文案被拦可以再录一次。",
    owner="C",
    status="要新做",
)
register(CARD, handler)
