"""微信支付 APIv3 客户端（照净界AI server/wxpay.mjs：Native 下单、查单、关单、退款、查退款；11-19 补 JSAPI 调起、H5）。

接口：POST /v3/pay/transactions/native、/jsapi、/h5；GET /v3/pay/transactions/out-trade-no/{单号}?mchid=；
POST /v3/pay/transactions/out-trade-no/{单号}/close；POST /v3/refund/domestic/refunds；GET /v3/refund/domestic/refunds/{退款单号}。
每个应答都用微信支付公钥验签（配了公钥才验；没配不让用，见 ShopSettings.wechat_missing）。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from urllib.parse import quote

import httpx

from app.shop.paycore import keys, wechat_sign
from app.shop.settings import ShopSettings


class WechatPayError(RuntimeError):
    def __init__(self, message: str, *, status: int = 0, code: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.code = code


def rfc3339(dt: datetime) -> str:
    """微信要的过期时间格式：2026-11-18T20:30:00+08:00（这里按 UTC 写 +00:00，同一个时刻）。"""
    return dt.replace(microsecond=0).isoformat()


class WechatPayClient:
    def __init__(self, s: ShopSettings, transport: httpx.BaseTransport | None = None, timeout: float = 10.0) -> None:
        self.s = s
        self.transport = transport
        self.timeout = timeout

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
        s = self.s
        text = json.dumps(body, ensure_ascii=False, separators=(",", ":")) if body is not None else ""
        auth = wechat_sign.authorization(mchid=s.WECHATPAY_MCHID, serial_no=s.WECHATPAY_CERT_SERIAL,
                                         private_key=keys.read_private_key(s.WECHATPAY_PRIVATE_KEY_PATH),
                                         method=method, url_path=path, body=text)
        headers = {"Authorization": auth, "Accept": "application/json", "User-Agent": "psyppt-shop/1.0"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        try:
            with httpx.Client(base_url=s.WECHATPAY_API_BASE, timeout=self.timeout, transport=self.transport) as c:
                resp = c.request(method, path, content=text.encode("utf-8") if body is not None else None, headers=headers)
        except httpx.HTTPError as e:
            raise WechatPayError(f"连不上微信支付：{e}") from e
        raw = resp.content
        if raw:
            ok, why = wechat_sign.verify_signature(keys.read_public_key(s.WECHATPAY_PUBLIC_KEY_PATH), dict(resp.headers),
                                                   raw, expect_serial=s.WECHATPAY_PUBLIC_KEY_ID)
            if not ok:
                raise WechatPayError(f"微信支付的应答验签没过：{why}", status=resp.status_code)
        data = json.loads(raw) if raw else {}
        if resp.status_code >= 400:
            raise WechatPayError(str(data.get("message") or f"微信支付返回 {resp.status_code}"), status=resp.status_code,
                                 code=str(data.get("code") or ""))
        return resp.status_code, data

    def native(self, *, out_trade_no: str, amount_fen: int, description: str, expires_at: datetime) -> str:
        """Native 下单，返回 code_url（画成二维码给客人扫）。"""
        s = self.s
        _, data = self._request("POST", "/v3/pay/transactions/native", {
            "appid": s.WECHATPAY_APPID, "mchid": s.WECHATPAY_MCHID, "description": description[:127],
            "out_trade_no": out_trade_no, "time_expire": rfc3339(expires_at), "notify_url": s.WECHATPAY_NOTIFY_URL,
            "amount": {"total": amount_fen, "currency": "CNY"},
        })
        if not data.get("code_url"):
            raise WechatPayError("微信支付没给 code_url")
        return str(data["code_url"])

    def jsapi(self, *, out_trade_no: str, amount_fen: int, description: str, expires_at: datetime, openid: str) -> dict[str, str]:
        """JSAPI 下单 + 算好调起支付的参数（微信里付款；openid 来自服务号网页授权，见 shop/wxoauth.py）。
        官方 https://pay.weixin.qq.com/doc/v3/merchant/4012791856：payer.openid 必填，「获取OpenID的appid 须与下单及调起支付时
        所使用的appid保持一致」；prepay_id 有效期 2 小时。调起参数驼峰 appId/timeStamp/nonceStr/package/signType/paySign，
        package 是「prepay_id=」+ 值（4012791857、易错点 4054250943 第七节）。"""
        s = self.s
        _, data = self._request("POST", "/v3/pay/transactions/jsapi", {
            "appid": s.WECHATPAY_APPID, "mchid": s.WECHATPAY_MCHID, "description": description[:127],
            "out_trade_no": out_trade_no, "time_expire": rfc3339(expires_at), "notify_url": s.WECHATPAY_NOTIFY_URL,
            "amount": {"total": amount_fen, "currency": "CNY"}, "payer": {"openid": openid},
        })
        prepay = str(data.get("prepay_id") or "")
        if not prepay:
            raise WechatPayError("微信支付没给 prepay_id")
        ts, nc = str(int(datetime.now().timestamp())), wechat_sign.nonce()
        sign = wechat_sign.jsapi_pay_sign(keys.read_private_key(s.WECHATPAY_PRIVATE_KEY_PATH), appid=s.WECHATPAY_APPID,
                                          timestamp=ts, nonce_str=nc, prepay_id=prepay)
        return {"appId": s.WECHATPAY_APPID, "timeStamp": ts, "nonceStr": nc, "package": f"prepay_id={prepay}",
                "signType": "RSA", "paySign": sign}

    def h5(self, *, out_trade_no: str, amount_fen: int, description: str, expires_at: datetime, client_ip: str) -> str:
        """H5 下单（手机浏览器，不在微信里），返回 h5_url。官方 https://pay.weixin.qq.com/doc/v3/merchant/4012791834：
        scene_info.payer_client_ip 必填、填客人真实 IP；h5_info.type 填 Wap；h5_url 有效期 5 分钟，严禁篡改、拆分、截断，
        只许在后面拼 redirect_url（拼在调用方）。"""
        s = self.s
        _, data = self._request("POST", "/v3/pay/transactions/h5", {
            "appid": s.WECHATPAY_APPID, "mchid": s.WECHATPAY_MCHID, "description": description[:127],
            "out_trade_no": out_trade_no, "time_expire": rfc3339(expires_at), "notify_url": s.WECHATPAY_NOTIFY_URL,
            "amount": {"total": amount_fen, "currency": "CNY"},
            "scene_info": {"payer_client_ip": client_ip, "h5_info": {"type": "Wap"}},
        })
        if not data.get("h5_url"):
            raise WechatPayError("微信支付没给 h5_url")
        return str(data["h5_url"])

    def query(self, out_trade_no: str) -> dict[str, Any]:
        _, data = self._request("GET", f"/v3/pay/transactions/out-trade-no/{quote(out_trade_no)}?mchid={self.s.WECHATPAY_MCHID}")
        return data

    def close(self, out_trade_no: str) -> None:
        self._request("POST", f"/v3/pay/transactions/out-trade-no/{quote(out_trade_no)}/close", {"mchid": self.s.WECHATPAY_MCHID})

    def refund(self, *, out_trade_no: str, out_refund_no: str, total_fen: int, refund_fen: int, reason: str) -> dict[str, Any]:
        body: dict[str, Any] = {"out_trade_no": out_trade_no, "out_refund_no": out_refund_no, "reason": reason[:80] or "退款",
                                "amount": {"refund": refund_fen, "total": total_fen, "currency": "CNY"}}
        if self.s.WECHATPAY_NOTIFY_URL:
            body["notify_url"] = self.s.WECHATPAY_NOTIFY_URL
        _, data = self._request("POST", "/v3/refund/domestic/refunds", body)
        return data

    def refund_query(self, out_refund_no: str) -> dict[str, Any]:
        _, data = self._request("GET", f"/v3/refund/domestic/refunds/{quote(out_refund_no)}")
        return data
