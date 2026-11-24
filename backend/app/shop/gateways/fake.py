"""假网关：账本在运行时里（ShopRuntime.fake_trades），通知用 HMAC 签（钥匙启动时随机）。只在测试和本机走查用。

simulate_pay 模拟「客人扫码付了」：账本记成已付，返回一条签好名的通知（调用方交给 channel.web 的 notify；
drop_notify 时只记账不发通知，用来测「回调丢了靠查单补」）。
"""

from __future__ import annotations

import json
import secrets
import time
from typing import Any

from app.shop.paycore import fake_sign

FAKE_MERCHANT = "fake-merchant"


def new_trade(rt: Any, out_trade_no: str, amount_fen: int, method: str) -> None:
    with rt.lock:
        rt.fake_trades.setdefault(out_trade_no, {"status": "NOTPAY", "amount_fen": amount_fen, "method": method,
                                                 "txn_id": "", "payer_ref": "", "refunded_fen": 0, "refund_mode": "ok"})


def notify_body(rt: Any, out_trade_no: str, *, amount_fen: int, txn_id: str, payer_ref: str,
                merchant: str = FAKE_MERCHANT, event: str = "pay") -> bytes:
    body = {"event": event, "out_trade_no": out_trade_no, "amount_fen": amount_fen, "txn_id": txn_id,
            "payer_ref": payer_ref, "merchant": merchant, "ts": int(time.time())}
    body["sign"] = fake_sign.sign(rt.fake_secret, body)
    return json.dumps(body, ensure_ascii=False).encode("utf-8")


def simulate_pay(rt: Any, out_trade_no: str, *, payer_ref: str = "") -> bytes:
    """客人付了：记账，返回通知原文。没有这单抛 KeyError。"""
    with rt.lock:
        t = rt.fake_trades[out_trade_no]
        if t["status"] != "SUCCESS":
            t["status"] = "SUCCESS"
            t["txn_id"] = "FAKE" + secrets.token_hex(8).upper()
            t["payer_ref"] = payer_ref or "fake:" + secrets.token_hex(4)
        amount, txn, payer = t["amount_fen"], t["txn_id"], t["payer_ref"]
    return notify_body(rt, out_trade_no, amount_fen=amount, txn_id=txn, payer_ref=payer)
