"""小红书的适配器（模块 C）。小红书个人卖家拿不到接口（设计第五节第 4 条），两种人工实现，看 Edison 的截图选（后台能切）：

- manual_paste：发货栏能填一段文字 → 负责人在后台录单，复制出来的那句贴到小红书发货栏。
- fixed_link：发货栏只能放一个固定链接 → 链接填 /x/<商品口令>；买家打开填小红书订单号 → 负责人核对 → 建单出码，
  码只在我们的页面上给，不写进小红书。
openapi（企业店 + 开放平台）是 P2，接口待对文档，没写。
"""

from __future__ import annotations

from app.intake.adapters import DeliveryResult
from app.platforms.manual import ManualAdapter


class XhsManualPaste(ManualAdapter):
    platform = "xhs"
    name = "manual_paste"


class XhsFixedLink(ManualAdapter):
    platform = "xhs"
    name = "fixed_link"

    def write_delivery(self, platform_order_id: str, text: str) -> DeliveryResult:
        return DeliveryResult(exit="written", detail="码在固定链接页上给买家，不写进平台")
