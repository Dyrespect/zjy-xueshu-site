"""支付宝开放平台客户端：电脑网站支付、手机网站支付（组好签名的跳转地址）、查单、关单、退款、查退款。

接口：alipay.trade.page.pay（FAST_INSTANT_TRADE_PAY）、alipay.trade.wap.pay（QUICK_WAP_WAY）、alipay.trade.query、
alipay.trade.close、alipay.trade.refund、alipay.trade.fastpay.refund.query。网关地址在配置里（正式 / 沙箱）。
同步跳回（return_url）不算付款凭据，只认异步通知和查单。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx

from app.shop.paycore import alipay_sign, keys
from app.shop.settings import ShopSettings

BEIJING = ZoneInfo("Asia/Shanghai")


class AlipayError(RuntimeError):
    def __init__(self, message: str, *, code: str = "", sub_code: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.sub_code = sub_code


def fen_to_yuan(fen: int) -> str:
    return f"{fen // 100}.{fen % 100:02d}"


def yuan_to_fen(yuan: str) -> int:
    whole, _, frac = str(yuan).strip().partition(".")
    return int(whole or 0) * 100 + int((frac + "00")[:2])


def beijing(dt: datetime) -> str:
    return dt.astimezone(BEIJING).strftime("%Y-%m-%d %H:%M:%S")


class AlipayClient:
    def __init__(self, s: ShopSettings, transport: httpx.BaseTransport | None = None, timeout: float = 10.0) -> None:
        self.s = s
        self.transport = transport
        self.timeout = timeout

    def _params(self, method: str, biz: dict[str, Any], *, notify: bool = False, return_url: str = "") -> dict[str, Any]:
        s = self.s
        p: dict[str, Any] = {
            "app_id": s.ALIPAY_APP_ID, "method": method, "format": "JSON", "charset": "utf-8", "sign_type": "RSA2",
            "timestamp": beijing(datetime.now(BEIJING)), "version": "1.0",
            "biz_content": json.dumps(biz, ensure_ascii=False, separators=(",", ":")),
        }
        if notify and s.ALIPAY_NOTIFY_URL:
            p["notify_url"] = s.ALIPAY_NOTIFY_URL
        if return_url:
            p["return_url"] = return_url
        return alipay_sign.sign_params(keys.read_private_key(s.ALIPAY_PRIVATE_KEY_PATH), p)

    def pay_url(self, *, method: str, out_trade_no: str, amount_fen: int, subject: str, expires_at: datetime,
                return_url: str) -> str:
        """电脑网站 / 手机网站支付：返回签好名的网关地址，前端整页跳过去。"""
        wap = method == "alipay_wap"
        biz = {"out_trade_no": out_trade_no, "total_amount": fen_to_yuan(amount_fen), "subject": subject[:256],
               "product_code": "QUICK_WAP_WAY" if wap else "FAST_INSTANT_TRADE_PAY", "time_expire": beijing(expires_at)}
        if wap and return_url:
            biz["quit_url"] = return_url
        params = self._params("alipay.trade.wap.pay" if wap else "alipay.trade.page.pay", biz, notify=True,
                              return_url=self.s.ALIPAY_RETURN_URL or return_url)
        return f"{self.s.ALIPAY_GATEWAY}?{urlencode(params)}"

    def _call(self, method: str, biz: dict[str, Any]) -> dict[str, Any]:
        params = self._params(method, biz)
        try:
            with httpx.Client(timeout=self.timeout, transport=self.transport) as c:
                resp = c.post(self.s.ALIPAY_GATEWAY, data=params,
                              headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"})
        except httpx.HTTPError as e:
            raise AlipayError(f"连不上支付宝：{e}") from e
        text = resp.text
        try:
            ok, body = alipay_sign.verify_response(keys.read_public_key(self.s.ALIPAY_PUBLIC_KEY_PATH), text, method)
        except (ValueError, KeyError) as e:
            raise AlipayError(f"支付宝的应答读不出来：{e}") from e
        if not ok:
            raise AlipayError("支付宝的应答验签没过")
        return body

    def query(self, out_trade_no: str) -> dict[str, Any]:
        return self._call("alipay.trade.query", {"out_trade_no": out_trade_no})

    def close(self, out_trade_no: str) -> dict[str, Any]:
        return self._call("alipay.trade.close", {"out_trade_no": out_trade_no})

    def refund(self, *, out_trade_no: str, out_refund_no: str, refund_fen: int, reason: str) -> dict[str, Any]:
        return self._call("alipay.trade.refund", {"out_trade_no": out_trade_no, "refund_amount": fen_to_yuan(refund_fen),
                                                  "out_request_no": out_refund_no, "refund_reason": reason[:80] or "退款"})

    def refund_query(self, *, out_trade_no: str, out_refund_no: str) -> dict[str, Any]:
        return self._call("alipay.trade.fastpay.refund.query", {"out_trade_no": out_trade_no, "out_request_no": out_refund_no})
