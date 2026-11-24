"""抖音的适配器（模块 C，P2）：订阅已付款消息 → 回查订单详情 → 写发货内容；完成、售后消息 tag 待 Edison 截图。

激活码交付方案第 6 节标「待对文档」的接口没核对前不许写调用，所以这里只占位：不认任何推送、不写任何东西。
"""

from __future__ import annotations

from typing import Any

from app.intake.adapters import DeliveryResult, PaidIn, PlatformSignal


class DouyinOpenApi:
    platform = "dy"
    name = "openapi"

    def verify(self, headers: dict[str, str], raw: bytes) -> bool:
        return False

    def parse_paid(self, payload: dict[str, Any]) -> PaidIn | None:
        return None

    def parse_signal(self, payload: dict[str, Any]) -> PlatformSignal | None:
        return None

    def fetch_order(self, platform_order_id: str) -> PaidIn | None:
        return None

    def write_delivery(self, platform_order_id: str, text: str) -> DeliveryResult:
        return DeliveryResult(exit="failed", detail="接口待对文档，还没接")
