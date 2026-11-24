"""人工渠道共用的适配器底子（小红书人工录单、闲鱼人工、固定链接）。只翻译，不判断。

人工渠道没有推送：verify 一律 False（推送进来不认）；已付款来自负责人录的表单或核对过的买家订单号；
发货内容交给负责人去平台贴（DeliveryResult.exit = manual）。契约第六节 ChannelAdapter。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.intake.adapters import DeliveryResult, PaidIn, PlatformSignal


class ManualAdapter:
    platform = ""
    name = "manual"

    def verify(self, headers: dict[str, str], raw: bytes) -> bool:
        return False

    def parse_paid(self, payload: dict[str, Any]) -> PaidIn | None:
        no = str(payload.get("platform_order_id") or "").strip()
        sku = str(payload.get("sku") or "")
        if not no or not sku:
            return None
        paid_at = payload.get("paid_at")
        return PaidIn(platform=self.platform, platform_order_id=no[:64], sku=sku, addons=list(payload.get("addons") or []),
                      buyer_id=str(payload.get("buyer_id") or "")[:128],
                      paid_at=paid_at if isinstance(paid_at, datetime) else None,
                      paid_amount=str(payload.get("paid_amount") or "")[:16], raw_ref=str(payload.get("raw_ref") or "")[:128],
                      source=str(payload.get("source") or self.platform)[:64], flow_key=str(payload.get("flow_key") or "paid_custom"))

    def parse_signal(self, payload: dict[str, Any]) -> PlatformSignal | None:
        no, kind = str(payload.get("platform_order_id") or "").strip(), payload.get("kind")
        if not no or kind not in ("completed", "refund_requested", "refund", "refund_closed"):
            return None
        return PlatformSignal(platform=self.platform, platform_order_id=no[:64], kind=kind, raw_ref=str(payload.get("raw_ref") or ""))

    def fetch_order(self, platform_order_id: str) -> PaidIn | None:
        return None

    def write_delivery(self, platform_order_id: str, text: str) -> DeliveryResult:
        return DeliveryResult(exit="manual", text_for_edison=text, detail="人工渠道：复制去平台订单里发货")
