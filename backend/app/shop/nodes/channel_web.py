"""channel.web 自有网页下单。"""

from __future__ import annotations

from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.shop import service
from app.shop.models_io import WebIn, WebOut


def handler(call: NodeCall, data: WebIn) -> NodeResult:
    rt = call.ctx.shop
    req = data.root
    if req.op == "checkout":
        return service.create_checkout(call, rt, req)
    if req.op == "poll":
        return service.poll(call, rt, req.view_token)
    if req.op == "notify":
        return service.handle_notify(call, rt, req)
    if req.op == "refund":
        return service.refund(call, rt, req)
    if req.op == "wx_start":
        return service.wx_start(call, rt, req)
    if req.op == "jsapi_prepare":
        return service.jsapi_prepare(call, rt, req)
    if req.op == "repay":
        return service.repay(call, rt, req)
    return service.sweep(call, rt, req.now)


CARD = NodeCard(
    id="channel.web",
    name="自有网页下单",
    description="客人在我们自己的网页上选时长档、篇数、加购，看到价格，付款；付完马上拿到激活码。"
                "也接网关的付款通知、付款页的轮询（回调丢了靠查单补）、定时关掉过期没付的单；Edison 在后台退款也走它。"
                "手机上：微信里先去服务号网页授权拿 openid 再下 JSAPI 单，手机浏览器点了「打开微信付款」才要微信 H5 链接；"
                "付没付只看验过签的通知和查单。",
    category="渠道",
    tech=["FastAPI 路由 /api/shop/*（app/shop/router.py）", "SQLAlchemy：shop_checkouts、shop_refunds、shop_notifications",
          "React 下单页 /order、付款页 /order/pay/:token（区块 order-picker、pay-panel、order-paid）",
          "服务号网页授权 /api/shop/wx/oauth → 微信 → /api/shop/wx/callback（app/shop/wxoauth.py，wechatpy 的 WeChatOAuth）",
          "run_node：sku.catalog、sku.quote、website.consent（没勾全三项不建单）、pay.*、order.create、order.void、notify.feishu",
          "适配器 app/shop/adapter.py（付款结果 → PaidIn）"],
    input_model=WebIn,
    output_model=WebOut,
    exits=[NodeExit(key="ok", label="成了（下单拿到付款指令 / 付了建单出码 / 退款成功 / 定时扫完）", kind="ok"),
           NodeExit(key="exists", label="重复通知，已经处理过", kind="ok"),
           NodeExit(key="quote_rejected", label="选的档位组合不卖、不能加急、名额排满", kind="fail"),
           NodeExit(key="pay_unavailable", label="这种付款方式没开、暂停接单", kind="fail"),
           NodeExit(key="consent_missing", label="三项确认没勾全（或记不下来），不建单", kind="fail"),
           NodeExit(key="waiting", label="还没付 / 退款在处理", kind="wait"),
           NodeExit(key="need_openid", label="微信里付款：还要先去服务号网页授权拿 openid", kind="wait"),
           NodeExit(key="closed", label="付款单过期关了", kind="fail"),
           NodeExit(key="invalid", label="通知验签、金额、商户号对不上，没建单", kind="fail"),
           NodeExit(key="blocked", label="付了，但这个付款人退款作废太多次，没发码（通知负责人退款）", kind="fail"),
           NodeExit(key="fail", label="网关出错、建单失败、退不了", kind="fail")],
    config=["SHOP_ENABLED：总开关", "SHOP_METHODS：开着的付款方式和对应支付节点（换支付只改这里）",
            "SHOP_CHECKOUT_TTL_MIN：待付款单多久过期（30 分钟）", "SHOP_IP_HOURLY_LIMIT：同一 IP 每小时最多下几单（20）",
            "SHOP_QUERY_MIN_INTERVAL_SEC：轮询时最快几秒查一次单（4）", "SHOP_REDEEM_URL：付完去哪交码",
            "WECHAT_MP_APPSECRET_FILE / WECHAT_MP_APPSECRET：服务号 AppSecret（微信里付款要；空 = 这块整个关掉）",
            "价格不在这里：全部来自订单中枢设置（sku.quote）"],
    emits=["shop.checkout_created", "shop.checkout_failed", "shop.pay_notified", "shop.pay_invalid", "shop.checkout_closed",
           "shop.refund_requested", "shop.refund_done", "shop.jsapi_prepared", "shop.h5_url_issued", "shop.wx_oauth_failed"],
    listens=["无"],
    replaceable=["付款节点换 pay.wechat / pay.alipay / pay.fake（改 SHOP_METHODS）",
                 "以后要换流程：在 flows/ 加流程，PaidIn.flow_key 换掉，本节点不改"],
    failure="回调幂等两层：shop_notifications.dedupe_key 唯一 + order.create 按（web, 商户订单号）幂等，同一笔通知十次只一单一码；"
            "改待付款单前先占锁再重读，通知和轮询并发也只建一单。金额、商户号对不上不建单、回失败让网关重发、通知负责人。"
            "回调丢了靠付款页轮询查单补；过期的单去网关关单，关单后才到的付款照样建单（钱到了算数）。"
            "退款先记「退款中」并提交，再去网关退，退成了才 order.void。",
    owner="B",
    status="要新做",
)
register(CARD, handler)
