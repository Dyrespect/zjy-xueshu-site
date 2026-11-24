"""pay.alipay 支付宝。"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import parse_qsl
from zoneinfo import ZoneInfo

from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.shop.gateways.alipay import AlipayClient, AlipayError, yuan_to_fen
from app.shop.models_io import PAY_EXITS, PayIn, PayOut
from app.shop.paycore import alipay_sign, keys

OK_ACK = "success"  # 支付宝：收到通知回纯文本 success，别的都算没收到（会重发）
FAIL_ACK = "fail"


def _bj(s: str) -> datetime | None:
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=ZoneInfo("Asia/Shanghai")) if s else None
    except ValueError:
        return None


def _paid_out(d: dict, s, no: str) -> PayOut:
    buyer = str(d.get("buyer_open_id") or d.get("buyer_id") or d.get("buyer_user_id") or "")
    seller_ok = not s.ALIPAY_SELLER_ID or str(d.get("seller_id") or s.ALIPAY_SELLER_ID) == s.ALIPAY_SELLER_ID
    app_ok = str(d.get("app_id") or d.get("auth_app_id") or s.ALIPAY_APP_ID) == s.ALIPAY_APP_ID
    return PayOut(out_trade_no=no, event="pay", txn_id=str(d.get("trade_no") or ""),
                  amount_fen=yuan_to_fen(str(d.get("total_amount") or "0")), payer_ref=f"ali:{buyer}" if buyer else "",
                  merchant_ok=seller_ok and app_ok, paid_at=_bj(str(d.get("gmt_payment") or d.get("send_pay_date") or "")),
                  dedupe_key=f"pay.alipay:pay:{d.get('trade_no')}")


def handler(call: NodeCall, data: PayIn) -> NodeResult:
    rt = call.ctx.shop
    s = rt.settings
    req = data.root
    missing = s.alipay_missing()
    if missing:
        return NodeResult(exit="unavailable", output=PayOut(ack=FAIL_ACK, ack_status=503), detail="支付宝缺配置：" + "、".join(missing))
    client = AlipayClient(s, rt.transports.get("alipay"))
    try:
        if req.op == "create":
            if req.method not in ("alipay_page", "alipay_wap"):
                return NodeResult(exit="unavailable", output=PayOut(), detail=f"支付宝不支持 {req.method}")
            url = client.pay_url(method=req.method, out_trade_no=req.out_trade_no, amount_fen=req.amount_fen,
                                 subject=req.subject, expires_at=req.expires_at, return_url=req.return_url)
            return NodeResult(exit="created", output=PayOut(out_trade_no=req.out_trade_no, kind="redirect", payload={"url": url}))
        if req.op == "query":
            d = client.query(req.out_trade_no)
            if d.get("code") != "10000":
                if d.get("sub_code") == "ACQ.TRADE_NOT_EXIST":  # 客人还没打开支付宝付款页，支付宝那边还没有这单
                    return NodeResult(exit="pending", output=PayOut(out_trade_no=req.out_trade_no), detail="支付宝还没有这单")
                return NodeResult(exit="fail", output=PayOut(out_trade_no=req.out_trade_no), detail=str(d.get("sub_msg") or d.get("msg")))
            status = d.get("trade_status")
            if status in ("TRADE_SUCCESS", "TRADE_FINISHED"):
                return NodeResult(exit="paid", output=_paid_out(d, s, req.out_trade_no))
            if status == "TRADE_CLOSED":
                return NodeResult(exit="closed", output=PayOut(out_trade_no=req.out_trade_no))
            return NodeResult(exit="pending", output=PayOut(out_trade_no=req.out_trade_no), detail=str(status or ""))
        if req.op == "close":
            d = client.close(req.out_trade_no)
            if d.get("code") == "10000" or d.get("sub_code") == "ACQ.TRADE_NOT_EXIST":
                return NodeResult(exit="closed", output=PayOut(out_trade_no=req.out_trade_no))
            return NodeResult(exit="fail", output=PayOut(out_trade_no=req.out_trade_no), detail=str(d.get("sub_msg") or d.get("msg")))
        if req.op == "refund":
            d = client.refund(out_trade_no=req.out_trade_no, out_refund_no=req.out_refund_no, refund_fen=req.refund_fen,
                              reason=req.reason)
            out = PayOut(out_trade_no=req.out_trade_no, event="refund", refund_id=str(d.get("trade_no") or ""),
                         out_refund_no=req.out_refund_no)
            if d.get("code") == "10000" and d.get("fund_change", "Y") == "Y":
                return NodeResult(exit="refund_ok", output=out)
            if d.get("code") == "10000":
                return NodeResult(exit="refund_processing", output=out, detail="支付宝说资金没变动，稍后查退款")
            return NodeResult(exit="refund_failed", output=out, detail=str(d.get("sub_msg") or d.get("msg")))
        if req.op == "refund_query":
            d = client.refund_query(out_trade_no=req.out_trade_no, out_refund_no=req.out_refund_no)
            out = PayOut(out_trade_no=req.out_trade_no, event="refund", out_refund_no=req.out_refund_no)
            if d.get("code") == "10000" and d.get("refund_status", "REFUND_SUCCESS") == "REFUND_SUCCESS" and d.get("refund_amount"):
                return NodeResult(exit="refund_ok", output=out)
            return NodeResult(exit="refund_processing", output=out, detail=str(d.get("sub_msg") or "还没退成"))
    except AlipayError as e:
        return NodeResult(exit="fail", output=PayOut(out_trade_no=getattr(req, "out_trade_no", "")), detail=str(e))
    except keys.KeyError_ as e:
        return NodeResult(exit="unavailable", output=PayOut(), detail=f"支付宝的密钥文件：{e}")

    # notify：表单 → 验签（去掉 sign、sign_type）→ 只认 TRADE_SUCCESS / TRADE_FINISHED
    try:
        params = dict(parse_qsl(req.raw.decode("utf-8"), keep_blank_values=True))
        pub = keys.read_public_key(s.ALIPAY_PUBLIC_KEY_PATH)
    except (UnicodeDecodeError, keys.KeyError_) as e:
        return NodeResult(exit="invalid", output=PayOut(ack=FAIL_ACK, ack_status=400), detail=f"通知读不出来：{e}")
    if not alipay_sign.verify_notify(pub, params):
        return NodeResult(exit="invalid", output=PayOut(ack=FAIL_ACK, ack_status=400), detail="签名不对")
    no = params.get("out_trade_no", "")
    status = params.get("trade_status", "")
    if status in ("TRADE_SUCCESS", "TRADE_FINISHED"):
        out = _paid_out(params, s, no)
        out.ack = OK_ACK
        return NodeResult(exit="paid", output=out)
    if status == "TRADE_CLOSED":
        return NodeResult(exit="closed", output=PayOut(out_trade_no=no, ack=OK_ACK), detail="交易关闭（没付或全额退了）")
    return NodeResult(exit="pending", output=PayOut(out_trade_no=no, ack=OK_ACK), detail=f"不处理的通知 {status}")


CARD = NodeCard(
    id="pay.alipay",
    name="支付宝",
    description="用竹涧云的支付宝收钱：电脑网站支付（跳到支付宝收银台）、手机网站支付；也负责查单、关单、退款、验证支付宝的异步通知。"
                "微信里打开下单页时不出（微信会拦支付宝）。",
    category="财务",
    tech=["支付宝开放平台网关：alipay.trade.page.pay、alipay.trade.wap.pay、alipay.trade.query、alipay.trade.close、"
          "alipay.trade.refund、alipay.trade.fastpay.refund.query", "httpx 同步客户端（app/shop/gateways/alipay.py）",
          "cryptography 手写 RSA2（SHA256WithRSA）签名验签，不装支付宝 SDK"],
    input_model=PayIn,
    output_model=PayOut,
    exits=[NodeExit(key=k, label=lb, kind=kd) for k, lb, kd in PAY_EXITS],
    config=["ALIPAY_APP_ID、ALIPAY_PRIVATE_KEY_PATH、ALIPAY_PUBLIC_KEY_PATH、ALIPAY_NOTIFY_URL（只在 .env）",
            "ALIPAY_RETURN_URL：付完跳回哪", "ALIPAY_GATEWAY：正式 / 沙箱网关", "ALIPAY_SELLER_ID：填了就核对收款账号"],
    emits=["无（结果交给 channel.web 记 shop.* 事件）"],
    listens=["无"],
    replaceable=["pay.wechat", "pay.fake（测试、本机走查）"],
    failure="同步跳回不算付款凭据，只认异步通知和查单；通知验签失败不回 success（支付宝会重发），出口 invalid；"
            "退款按 out_request_no 幂等，资金没变动时出口 refund_processing，定时任务再查；网络出错出口 fail，可以重试。",
    owner="B",
    status="要新做",
)
register(CARD, handler)
