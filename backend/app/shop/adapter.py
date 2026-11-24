"""自有网页的渠道适配器（契约第六节：网页适配器放 app/shop/adapter.py）。只翻译，不判断。

自有网页的「平台消息」就是支付节点验过签的付款结果：parse_paid 把待付款单 + 付款结果翻成 order.create 的 PaidIn。
码只在我们自己的结果页上显示，不写进任何平台，所以 write_delivery 直接算「写了」。
"""

from __future__ import annotations

from datetime import datetime

from app.intake.adapters import DeliveryResult, PaidIn, PlatformSignal


def fen_to_amount(fen: int) -> str:
    """分 → 契约要的两位小数字符串（2990 → "29.90"）。"""
    return f"{fen // 100}.{fen % 100:02d}"


class WebAdapter:
    platform = "web"

    def verify(self, headers: dict[str, str], raw: bytes) -> bool:  # 验签在支付节点（pay.*）里做过了
        return True

    def parse_paid(self, payload: dict) -> PaidIn | None:
        if not payload.get("out_trade_no") or not payload.get("sku"):
            return None
        paid_at = payload.get("paid_at")
        return PaidIn(platform="web", platform_order_id=payload["out_trade_no"], sku=payload["sku"],
                      addons=list(payload.get("addons") or []), buyer_id=str(payload.get("payer_ref") or "")[:128],
                      paid_at=paid_at if isinstance(paid_at, datetime) else None,
                      paid_amount=fen_to_amount(int(payload.get("amount_fen") or 0)),
                      raw_ref=str(payload.get("txn_id") or "")[:128], source=str(payload.get("source") or "")[:64],
                      flow_key=str(payload.get("flow_key") or "paid_custom"))

    def parse_signal(self, payload: dict) -> PlatformSignal | None:  # 自有网页没有平台信号：确认收货靠按钮和超时
        return None

    def fetch_order(self, platform_order_id: str) -> PaidIn | None:  # 回查走支付节点的 query
        return None

    def write_delivery(self, platform_order_id: str, text: str) -> DeliveryResult:
        return DeliveryResult(exit="written", detail="码在自有网页的结果页上显示")
