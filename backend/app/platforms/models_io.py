"""平台渠道节点的输入输出（Pydantic）。节点文件 import 这里，不 import 别的节点。

注意：本目录的 .py 里的字符串会被 check.py 规矩 11 按红线词表扫（平台名、联系方式、导流词都不许出现），
给人看的渠道名在 profiles.json 的 label 里，前端也有一份。
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, RootModel


class ManualForm(BaseModel):
    """负责人在后台录一单：平台订单号 + 卖的是哪个商品（或直接选货号）。"""

    platform_order_id: str = Field(min_length=3, max_length=64)
    product_id: int | None = None
    sku: str = Field(default="", max_length=48)
    addons: list[str] = Field(default_factory=list)
    paid_amount: str = Field(default="", max_length=16, description="实付（两位小数）；空 = 按商品标价")
    buyer_hint: str = Field(default="", max_length=64)


class PlatformInbound(BaseModel):
    op: Literal["inbound"] = "inbound"
    source: Literal["manual", "buyer_claim", "push", "tool"]
    form: dict[str, Any] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    raw: bytes = b""
    client_ip: str = ""


class PlatformVerify(BaseModel):
    op: Literal["verify"] = "verify"
    inbox_id: int
    ok: bool
    buyer_hint: str = Field(default="", max_length=64)
    note: str = Field(default="", max_length=200)


class PlatformSignalIn(BaseModel):
    op: Literal["signal"] = "signal"
    platform_order_id: str = Field(min_length=1, max_length=64)
    kind: Literal["completed", "refund_requested", "refund", "refund_closed"]


class PlatformIn(RootModel[Annotated[PlatformInbound | PlatformVerify | PlatformSignalIn, Field(discriminator="op")]]):
    """平台渠道节点的输入：inbound 进来一单（录单、买家填订单号、推送）/ verify 负责人核对 / signal 负责人点平台信号。"""


class PlatformOut(BaseModel):
    """平台渠道节点的统一输出（设计里的 ChannelOut）。"""

    inbox_id: int | None = None
    order_id: int | None = None
    code: str = ""
    text_for_edison: str = Field(default="", description="出口 manual 时：要贴到平台的发货文案")
    claim_token: str = ""
    verify_status: str = ""
    redeem_url: str = ""
    stage: str = ""
    ack: dict[str, Any] | str = ""
    dedupe_key: str = ""
    why: str = ""


class TextIn(BaseModel):
    platform: str = Field(min_length=1, max_length=8)
    text: str = Field(max_length=2000)
    allow: list[str] = Field(default_factory=list, max_length=10,
                             description="文案里我们自己生成的字（激活码），查红线前先去掉；码是随机的，会碰巧拼出词表里的两个字母")


class TextOut(BaseModel):
    hits: list[str] = Field(default_factory=list)
