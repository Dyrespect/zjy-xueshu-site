"""pay.wechat 微信支付。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import quote

from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.shop.gateways.wechat import WechatPayClient, WechatPayError
from app.shop.models_io import PAY_EXITS, PayIn, PayOut
from app.shop.paycore import keys, qr, wechat_sign

OK_ACK = ""  # 微信：收到通知回 200 / 204，不用应答体


def _fail_ack(why: str, status: int = 401) -> tuple[dict, int]:
    return {"code": "FAIL", "message": why[:120]}, status


def _ts(s: str) -> datetime | None:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None
    except ValueError:
        return None


def h5_payload(h5_url: str, return_url: str) -> dict:
    """h5_url 原样用，只在最后拼 redirect_url（要 urlencode；域名必须是商户平台配的 H5 支付域名）。
    出处：H5调起支付 https://pay.weixin.qq.com/doc/v3/merchant/4012791835「支付后返回指定页面」；H5下单 4012791834 h5_url 一栏。
    issued_at：h5_url 只有 5 分钟有效，付款页点按钮时按它判断要不要重新要一个（channel.web 的 repay）。"""
    url = h5_url
    if return_url:
        url += ("&" if "?" in h5_url else "?") + "redirect_url=" + quote(return_url, safe="")
    return {"url": url, "h5": True, "issued_at": datetime.now(timezone.utc).isoformat()}


def _paid_out(no: str, tx: dict, s) -> PayOut:
    openid = str((tx.get("payer") or {}).get("openid") or "")
    return PayOut(out_trade_no=no, event="pay", txn_id=str(tx.get("transaction_id") or ""),
                  amount_fen=int((tx.get("amount") or {}).get("total") or 0), payer_ref=f"wx:{openid}" if openid else "",
                  merchant_ok=tx.get("mchid") == s.WECHATPAY_MCHID and tx.get("appid") == s.WECHATPAY_APPID,
                  paid_at=_ts(str(tx.get("success_time") or "")), dedupe_key=f"pay.wechat:pay:{tx.get('transaction_id')}")


def handler(call: NodeCall, data: PayIn) -> NodeResult:
    rt = call.ctx.shop
    s = rt.settings
    req = data.root
    missing = s.wechat_missing()
    if missing:
        return NodeResult(exit="unavailable", output=PayOut(ack=_fail_ack("没配好")[0], ack_status=503),
                          detail="微信支付缺配置：" + "、".join(missing))
    client = WechatPayClient(s, rt.transports.get("wechat"))
    try:
        if req.op == "create":
            if req.method == "wechat_native":
                url = client.native(out_trade_no=req.out_trade_no, amount_fen=req.amount_fen, description=req.subject,
                                    expires_at=req.expires_at)
                return NodeResult(exit="created", output=PayOut(out_trade_no=req.out_trade_no, kind="qr",
                                                                payload={"code_url": url, "qr": qr.rows(url)}))
            if req.method == "wechat_jsapi":
                if not req.openid:
                    return NodeResult(exit="unavailable", output=PayOut(), detail="微信里付款要先拿到 openid（服务号网页授权还没开）")
                params = client.jsapi(out_trade_no=req.out_trade_no, amount_fen=req.amount_fen, description=req.subject,
                                      expires_at=req.expires_at, openid=req.openid)
                return NodeResult(exit="created", output=PayOut(out_trade_no=req.out_trade_no, kind="jsapi", payload=params))
            if req.method == "wechat_h5":
                url = client.h5(out_trade_no=req.out_trade_no, amount_fen=req.amount_fen, description=req.subject,
                                expires_at=req.expires_at, client_ip=req.client_ip)
                return NodeResult(exit="created", output=PayOut(out_trade_no=req.out_trade_no, kind="redirect",
                                                                payload=h5_payload(url, req.return_url)))
            return NodeResult(exit="unavailable", output=PayOut(), detail=f"微信支付不支持 {req.method}")
        if req.op == "query":
            tx = client.query(req.out_trade_no)
            state = tx.get("trade_state")
            if state == "SUCCESS":
                return NodeResult(exit="paid", output=_paid_out(req.out_trade_no, tx, s))
            if state in ("CLOSED", "REVOKED", "PAYERROR"):
                return NodeResult(exit="closed", output=PayOut(out_trade_no=req.out_trade_no), detail=str(state))
            return NodeResult(exit="pending", output=PayOut(out_trade_no=req.out_trade_no), detail=str(state or ""))
        if req.op == "close":
            client.close(req.out_trade_no)
            return NodeResult(exit="closed", output=PayOut(out_trade_no=req.out_trade_no))
        if req.op == "refund" or req.op == "refund_query":
            r = (client.refund(out_trade_no=req.out_trade_no, out_refund_no=req.out_refund_no, total_fen=req.total_fen,
                               refund_fen=req.refund_fen, reason=req.reason)
                 if req.op == "refund" else client.refund_query(req.out_refund_no))
            out = PayOut(out_trade_no=req.out_trade_no, event="refund", refund_id=str(r.get("refund_id") or ""),
                         out_refund_no=req.out_refund_no)
            status = r.get("status")
            if status == "SUCCESS":
                return NodeResult(exit="refund_ok", output=out)
            if status == "PROCESSING":
                return NodeResult(exit="refund_processing", output=out)
            return NodeResult(exit="refund_failed", output=out, detail=f"微信退款状态 {status}")
    except WechatPayError as e:
        return NodeResult(exit="fail", output=PayOut(out_trade_no=getattr(req, "out_trade_no", "")), detail=str(e))
    except keys.KeyError_ as e:
        return NodeResult(exit="unavailable", output=PayOut(), detail=f"微信支付的密钥文件：{e}")

    # notify：先验签，再解密；验不过不处理（微信会重发，坏的永远过不了）
    try:
        pub = keys.read_public_key(s.WECHATPAY_PUBLIC_KEY_PATH)
    except keys.KeyError_ as e:
        ack, st = _fail_ack("公钥没配好", 503)
        return NodeResult(exit="unavailable", output=PayOut(ack=ack, ack_status=st), detail=str(e))
    ok, why = wechat_sign.verify_signature(pub, req.headers, req.raw, expect_serial=s.WECHATPAY_PUBLIC_KEY_ID)
    if not ok:
        ack, st = _fail_ack("验签失败")
        return NodeResult(exit="invalid", output=PayOut(ack=ack, ack_status=st), detail=why)
    try:
        body = json.loads(req.raw)
        res = body["resource"]
        plain = wechat_sign.decrypt_resource(s.WECHATPAY_APIV3_KEY.get_secret_value(), nonce_str=res["nonce"],
                                             ciphertext=res["ciphertext"], associated_data=res.get("associated_data", ""))
        tx = json.loads(plain)
    except (ValueError, KeyError, TypeError) as e:
        ack, st = _fail_ack("解不开")
        return NodeResult(exit="invalid", output=PayOut(ack=ack, ack_status=st), detail=f"通知解不开：{e}")
    event = str(body.get("event_type") or "")
    if event.startswith("REFUND."):
        out = PayOut(out_trade_no=str(tx.get("out_trade_no") or ""), event="refund", refund_id=str(tx.get("refund_id") or ""),
                     out_refund_no=str(tx.get("out_refund_no") or ""), merchant_ok=tx.get("mchid") == s.WECHATPAY_MCHID,
                     dedupe_key=f"pay.wechat:refund:{tx.get('refund_id')}:{tx.get('refund_status')}", ack=OK_ACK, ack_status=204)
        return NodeResult(exit="refund_ok" if tx.get("refund_status") == "SUCCESS" else "refund_failed", output=out,
                          detail=str(tx.get("refund_status") or ""))
    if event == "TRANSACTION.SUCCESS" and tx.get("trade_state") == "SUCCESS":
        out = _paid_out(str(tx.get("out_trade_no") or ""), tx, s)
        out.ack, out.ack_status = OK_ACK, 204
        return NodeResult(exit="paid", output=out)
    return NodeResult(exit="pending", output=PayOut(out_trade_no=str(tx.get("out_trade_no") or ""), ack=OK_ACK, ack_status=204),
                      detail=f"不处理的通知 {event}")


CARD = NodeCard(
    id="pay.wechat",
    name="微信支付",
    description="用竹涧云的微信支付商户号收钱：电脑上出二维码给客人扫（Native）；微信里直接付（JSAPI，openid 来自服务号网页授权）；"
                "手机浏览器里跳去微信付（H5，要商户平台另开 H5 产品）。也负责查单、关单、退款、验证微信发来的付款和退款通知。",
    category="财务",
    tech=["微信支付 APIv3：/v3/pay/transactions/native、/jsapi、/h5、查单、关单、/v3/refund/domestic/refunds",
          "JSAPI 调起支付签名（appId、时间戳、随机串、prepay_id 四行，SHA256 with RSA）：paycore/wechat_sign.jsapi_pay_sign",
          "httpx 同步客户端（app/shop/gateways/wechat.py）", "cryptography：SHA256-RSA 签名、微信支付公钥验签、AES-256-GCM 解密",
          "照净界AI server/wxpay.mjs 移植", "二维码：app/shop/paycore/qr.py（不加依赖）"],
    input_model=PayIn,
    output_model=PayOut,
    exits=[NodeExit(key=k, label=lb, kind=kd) for k, lb, kd in PAY_EXITS],
    config=["WECHATPAY_MCHID、WECHATPAY_APPID、WECHATPAY_CERT_SERIAL、WECHATPAY_PRIVATE_KEY_PATH、WECHATPAY_APIV3_KEY、"
            "WECHATPAY_PUBLIC_KEY_ID、WECHATPAY_PUBLIC_KEY_PATH、WECHATPAY_NOTIFY_URL（只在 .env；缺哪项后台显示缺哪项，出口 unavailable）",
            "WECHATPAY_API_BASE：接口地址"],
    emits=["无（结果交给 channel.web 记 shop.* 事件）"],
    listens=["无"],
    replaceable=["pay.alipay", "pay.fake（测试、本机走查）"],
    failure="下单、查单、关单、退款网络出错出口 fail，调用方可以用同一个商户订单号 / 退款单号重试（微信按单号幂等）；"
            "通知验签失败、时间戳差超过 5 分钟、解不开出口 invalid，不处理（微信会重发）；应答也验签，验不过算 fail。",
    owner="B",
    status="要新做",
)
register(CARD, handler)
