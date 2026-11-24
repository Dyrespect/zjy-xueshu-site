"""channel.xianyu 闲鱼。"""

from __future__ import annotations

from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.platforms import service
from app.platforms.models_io import PlatformIn, PlatformOut

PLATFORM = "xy"


def handler(call: NodeCall, data: PlatformIn) -> NodeResult:
    req = data.root
    if req.op == "inbound":
        return service.ingest(call, PLATFORM, req)
    if req.op == "verify":
        return NodeResult(exit="invalid", output=PlatformOut(), detail="这个渠道没有买家填订单号这一步")
    return service.signal(call, PLATFORM, req)


CARD = NodeCard(
    id="channel.xianyu",
    name="闲鱼",
    description="闲鱼上卖出一单后，把激活码交到这一单上；交易成功或退款时告诉订单中枢。"
                "现在靠 Edison：在闲鱼 App 看到订单 → 后台录单 → 复制发货文案贴进闲鱼聊天、点发货 → 交易成功或退款时在后台点一下。"
                "闲管家自动发货要 Edison 点头后再接。",
    category="渠道",
    tech=["适配器 app/platforms/xianyu.py：XianyuManual（xgj_supply、pool 没写）", "后台接口 /api/admin/platforms/*",
          "run_node：order.create、gate.platform_text、confirm.receipt、order.signal、notify.feishu、code.lookup"],
    input_model=PlatformIn,
    output_model=PlatformOut,
    exits=[NodeExit(key="delivered", label="码交出去了", kind="ok"),
           NodeExit(key="manual", label="发货文案交给负责人去贴", kind="wait"),
           NodeExit(key="signal_applied", label="平台信号交给订单中枢了", kind="ok"),
           NodeExit(key="exists", label="这个订单号来过，原样返回", kind="ok"),
           NodeExit(key="ignored", label="这个渠道没开 / 这种来源现在不收", kind="ok"),
           NodeExit(key="blocked", label="买家退款作废太多次，没发码", kind="fail"),
           NodeExit(key="text_blocked", label="发货文案过不了红线，没发", kind="fail"),
           NodeExit(key="invalid", label="表单不对、推送验签没过", kind="fail"),
           NodeExit(key="retry", label="写发货内容暂时失败，可以重试", kind="fail"),
           NodeExit(key="fail", label="建单失败、信号没接上", kind="fail")],
    config=["profiles.json 的 xy 一行（adapter：manual；remind_after_paid_hours：录单多久后提醒去看交易成功，先按 240 小时）",
            "platforms_products：商品对照"],
    emits=["platforms.ingested", "platforms.blocked", "platforms.signal"],
    listens=["无"],
    replaceable=["manual ↔ xgj_supply（闲管家虚拟货源接口，要 Edison 点头）↔ pool（码池，备选）"],
    failure="按（渠道, 平台订单号）幂等：同一订单号录两次返回同一枚码；建单失败、文案被拦可以再录一次。"
            "买家号拿不到，退款太多次的买家拦不住（设计第八节冲突 3）。",
    owner="C",
    status="要新做",
)
register(CARD, handler)
