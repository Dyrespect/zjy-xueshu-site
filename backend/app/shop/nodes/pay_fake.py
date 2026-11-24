"""pay.fake 假网关。"""

from __future__ import annotations

import json

from app.core.db import utcnow
from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.shop.gateways import fake
from app.shop.models_io import PAY_EXITS, PayIn, PayOut
from app.shop.paycore import fake_sign, qr


def handler(call: NodeCall, data: PayIn) -> NodeResult:
    rt = call.ctx.shop
    req = data.root
    if not rt.settings.SHOP_FAKE_PAY:
        return NodeResult(exit="unavailable", output=PayOut(ack="fail", ack_status=404), detail="假网关只在测试和本机开（SHOP_FAKE_PAY）")
    if req.op == "create":
        if req.method == "wechat_jsapi" and not req.openid:  # 跟真的一样：微信里付款没有 openid 下不了单
            return NodeResult(exit="unavailable", output=PayOut(), detail="微信里付款要先拿到 openid")
        fake.new_trade(rt, req.out_trade_no, req.amount_fen, req.method)
        if req.method == "wechat_jsapi":  # 假的调起参数：本机走查时页面上的「模拟付款」按钮代替微信收银台
            return NodeResult(exit="created", output=PayOut(out_trade_no=req.out_trade_no, kind="jsapi", simulated=True, payload={
                "appId": "wxfakeappid", "timeStamp": str(int(utcnow().timestamp())), "nonceStr": "fake" + req.out_trade_no[-8:],
                "package": "prepay_id=fake" + req.out_trade_no, "signType": "RSA", "paySign": "fake"}))
        if req.method == "wechat_h5":  # 假的微信付款链接：点了直接回付款页（真的会先去微信收银台，再按 redirect_url 回来）
            return NodeResult(exit="created", output=PayOut(out_trade_no=req.out_trade_no, kind="redirect", simulated=True, payload={
                "url": req.return_url or "/order", "h5": True, "issued_at": utcnow().isoformat()}))
        url = f"fakepay://trade/{req.out_trade_no}"
        return NodeResult(exit="created", output=PayOut(out_trade_no=req.out_trade_no, kind="qr", simulated=True,
                                                        payload={"code_url": url, "qr": qr.rows(url)}))
    if req.op in ("query", "close", "refund", "refund_query"):
        t = rt.fake_trades.get(req.out_trade_no)
        if req.op == "query":
            if t is not None and t["status"] == "SUCCESS":
                return NodeResult(exit="paid", output=PayOut(
                    out_trade_no=req.out_trade_no, event="pay", txn_id=t["txn_id"], amount_fen=t["amount_fen"],
                    payer_ref=t["payer_ref"], paid_at=utcnow(), dedupe_key=f"pay.fake:pay:{t['txn_id']}", simulated=True))
            if t is not None and t["status"] == "CLOSED":
                return NodeResult(exit="closed", output=PayOut(out_trade_no=req.out_trade_no))
            return NodeResult(exit="pending", output=PayOut(out_trade_no=req.out_trade_no))
        if req.op == "close":
            if t is not None and t["status"] == "NOTPAY":
                t["status"] = "CLOSED"
            return NodeResult(exit="closed", output=PayOut(out_trade_no=req.out_trade_no))
        out = PayOut(out_trade_no=req.out_trade_no, event="refund", out_refund_no=req.out_refund_no,
                     refund_id="FAKERF" + req.out_refund_no[-8:], simulated=True)
        if t is None:
            return NodeResult(exit="refund_failed", output=out, detail="假网关没有这单")
        if req.op == "refund":
            t["refunded_fen"] += req.refund_fen
        mode = t.get("refund_mode", "ok")
        if mode == "processing" and req.op == "refund":
            return NodeResult(exit="refund_processing", output=out)
        if mode == "fail":
            return NodeResult(exit="refund_failed", output=out, detail="假网关按指令退款失败")
        return NodeResult(exit="refund_ok", output=out)
    # notify
    try:
        body = json.loads(req.raw)
    except ValueError:
        return NodeResult(exit="invalid", output=PayOut(ack="fail", ack_status=400), detail="通知不是 JSON")
    if not isinstance(body, dict) or not fake_sign.verify(rt.fake_secret, body):
        return NodeResult(exit="invalid", output=PayOut(ack="fail", ack_status=400), detail="签名不对")
    out = PayOut(out_trade_no=str(body.get("out_trade_no") or ""), event="pay", txn_id=str(body.get("txn_id") or ""),
                 amount_fen=int(body.get("amount_fen") or 0), payer_ref=str(body.get("payer_ref") or ""),
                 merchant_ok=body.get("merchant") == fake.FAKE_MERCHANT, paid_at=utcnow(),
                 dedupe_key=f"pay.fake:pay:{body.get('txn_id')}", ack="success", simulated=True)
    return NodeResult(exit="paid", output=out)


CARD = NodeCard(
    id="pay.fake",
    name="假网关",
    description="测试和本机走查用的假支付：下单给一个假二维码，点「模拟付款」就算付了，通知用随机钥匙签名；"
                "能模拟已付、未付、验签失败、金额不对、商户号不对、通知丢了、退款处理中。生产上不许开。",
    category="财务",
    tech=["纯 Python（app/shop/gateways/fake.py 账本 + paycore/fake_sign.py 的 HMAC-SHA256）", "二维码 paycore/qr.py"],
    input_model=PayIn,
    output_model=PayOut,
    exits=[NodeExit(key=k, label=lb, kind=kd) for k, lb, kd in PAY_EXITS],
    config=["SHOP_FAKE_PAY：只在测试和本机为真；APP_ENV=prod 时为真，服务拒绝启动", "SHOP_FAKE_SECRET：签通知的钥匙，空 = 启动时随机"],
    emits=["无"],
    listens=["无"],
    replaceable=["pay.wechat", "pay.alipay"],
    failure="没有外部调用；账本在内存里，重启就没了（只给本机用）。签名不对出口 invalid。",
    owner="B",
    status="要新做",
)
register(CARD, handler)
