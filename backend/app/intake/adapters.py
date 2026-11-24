"""渠道适配器的接口和数据结构（模块 B、C 实现，放 app/platforms/<platform>.py）。

适配器只翻译，不判断：平台消息 → PaidIn / PlatformSignal；发货内容（platform_texts.delivery_text 给的那一句）→ 写进平台那一单。
要不要发码、发什么、订单怎么变，都在订单中枢的节点里（order.create、code.issue、order.void，平台信号走 orders.apply_signal）。
激活码交付方案里标「待对文档」的接口（抖音、小红书写发货内容）没核对前不许写调用。契约第四节第 4 条、第六节。
自有网页的适配器放 app/shop/adapter.py（模块 B），平台的放 app/platforms/<platform>.py（模块 C）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, Field


class PaidIn(BaseModel):
    """一笔付款（order.create 节点的输入）。"""

    platform: Literal["fk", "xy", "dy", "xhs", "web", "manual"]
    platform_order_id: str | None = Field(default=None, max_length=64, description="平台订单号；闲鱼没有时为空")
    sku: str = Field(min_length=1, max_length=48, description="基础货号（如 regular-p1）或加购货号（addon-rush）")
    addons: list[str] = Field(default_factory=list, description="同一笔买的加购 key：rush / revision / find_refs")
    buyer_id: str = Field(default="", max_length=128, description="平台给的店铺侧买家号，只用来认同一个买家")
    paid_at: datetime | None = None
    paid_amount: str = Field(default="", max_length=16, description="实付，两位小数的字符串（如 \"29.90\"；网关给的是分要换算），财务对账用")
    raw_ref: str = Field(default="", max_length=128, description="平台消息的编号，排查用")
    source: str = Field(default="", max_length=64, description="客人最早从哪来（图库、公众号、小红书……；下单页的 from 参数）")
    flow_key: str = Field(default="paid_custom", max_length=32, description="这一单走哪个流程（渠道档案给，换流程只改档案）")


class PlatformSignal(BaseModel):
    """平台消息翻译成的信号。refund_requested 申请退款（订单先暂停，等真退）；refund 真退了（作废）；
    refund_closed 申请撤了或被拒（恢复）；completed 平台已完成（来得早也先记下）。"""

    platform: Literal["fk", "xy", "dy", "xhs", "web"]
    platform_order_id: str = Field(min_length=1, max_length=64)
    kind: Literal["completed", "refund_requested", "refund", "refund_closed"]
    at: datetime | None = None
    raw_ref: str = ""


class DeliveryResult(BaseModel):
    """写发货内容的结果。manual：这个平台要人工录单（小红书第一期），text_for_edison 交给负责人去平台后台填。"""

    exit: Literal["written", "manual", "retry", "failed"]
    text_for_edison: str = ""
    detail: str = ""


class ChannelAdapter(Protocol):
    """适配器只翻译，不判断；方法都是同步的（节点 handler 是同步的，NodeCall 带同步 Session）。
    要调平台的异步接口，在适配器里自己用 httpx 的同步客户端，或 anyio.from_thread 跑。"""

    platform: str

    def verify(self, headers: dict[str, str], raw: bytes) -> bool:  # 验签；parse_* 只吃验过签的
        ...

    def parse_paid(self, payload: dict) -> PaidIn | None:  # 平台「已付款」→ order.create 的输入；不是就 None
        ...

    def parse_signal(self, payload: dict) -> PlatformSignal | None:  # 「已完成」「申请退款」「退款」「退款关闭」
        ...

    def fetch_order(self, platform_order_id: str) -> PaidIn | None:  # 收到推送后用订单号回查一次详情
        ...

    def write_delivery(self, platform_order_id: str, text: str) -> DeliveryResult:  # 把发货内容写进这一单
        ...
