"""本模块节点的输入输出（Pydantic）。节点文件 import 这里，不 import 别的节点。设计第六节「共用的输入输出模型」。"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel

# ---------------------------------------------------------------- 支付节点（pay.*）

PayKind = Literal["qr", "redirect", "jsapi", ""]


class PayCreate(BaseModel):
    op: Literal["create"] = "create"
    out_trade_no: str = Field(min_length=6, max_length=32)
    amount_fen: int = Field(ge=1, description="应付（分），channel.web 按报价算好的")
    subject: str = Field(min_length=1, max_length=120)
    method: str = Field(description="wechat_native / wechat_jsapi / wechat_h5 / alipay_page / alipay_wap")
    client_ip: str = ""
    openid: str | None = Field(default=None, description="微信里付款（JSAPI）要的 openid")
    expires_at: datetime
    return_url: str = Field(default="", description="付完跳回哪（支付宝网页支付；只是跳回，不算付款凭据）")


class PayQuery(BaseModel):
    op: Literal["query"] = "query"
    out_trade_no: str


class PayClose(BaseModel):
    op: Literal["close"] = "close"
    out_trade_no: str


class PayNotify(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    op: Literal["notify"] = "notify"
    headers: dict[str, str] = Field(default_factory=dict)
    raw: bytes = b""


class PayRefund(BaseModel):
    op: Literal["refund"] = "refund"
    out_trade_no: str
    out_refund_no: str
    total_fen: int = Field(ge=1)
    refund_fen: int = Field(ge=1)
    reason: str = Field(default="", max_length=80)


class PayRefundQuery(BaseModel):
    op: Literal["refund_query"] = "refund_query"
    out_trade_no: str
    out_refund_no: str


class PayIn(RootModel[Annotated[PayCreate | PayQuery | PayClose | PayNotify | PayRefund | PayRefundQuery, Field(discriminator="op")]]):
    """支付节点的输入：按 op 分（create 下单、query 查单、close 关单、notify 验通知、refund 退款、refund_query 查退款）。
    调的时候直接传 PayCreate(...) 这些，run_node 会按 op 认出是哪种。"""


class PayOut(BaseModel):
    out_trade_no: str = ""
    kind: PayKind = ""
    payload: dict[str, Any] = Field(default_factory=dict, description="付款指令：qr 给 code_url；redirect 给 url；jsapi 给调起参数")
    event: Literal["pay", "refund", ""] = Field(default="", description="通知是付款的还是退款的")
    txn_id: str = ""
    amount_fen: int = 0
    payer_ref: str = ""
    merchant_ok: bool = Field(default=True, description="通知里的商户号 / AppID 跟配置的对得上")
    paid_at: datetime | None = None
    refund_id: str = ""
    out_refund_no: str = ""
    dedupe_key: str = ""
    ack: dict[str, Any] | str = ""
    ack_status: int = 200
    simulated: bool = Field(default=False, description="假网关（本机测试用）")


PAY_EXITS = (
    ("created", "下好单了，给客人付款指令", "ok"),
    ("paid", "付了（通知验过签 / 查单是已付）", "ok"),
    ("pending", "还没付", "wait"),
    ("closed", "关掉了（或已经关了）", "ok"),
    ("refund_ok", "退款成功", "ok"),
    ("refund_processing", "退款在处理，稍后再查", "wait"),
    ("refund_failed", "退款没成（关闭、异常）", "fail"),
    ("unavailable", "这种付款方式没开或缺配置", "fail"),
    ("invalid", "通知验签失败、时间戳太旧、解不开", "fail"),
    ("fail", "网关报错或连不上", "fail"),
)


# ---------------------------------------------------------------- channel.web

class WebCheckout(BaseModel):
    op: Literal["checkout"] = "checkout"
    tier: str = Field(min_length=1, max_length=16, description="时长档 key：light / regular / long / xlong")
    band: str = Field(min_length=1, max_length=8, description="篇数档 key：p1 / p2_3 / p4_5")
    rush: bool = False
    find_refs: bool = False
    extra_revisions: int = Field(default=0, ge=0, le=5)
    method: str = Field(min_length=1, max_length=24)
    session_ref: str = Field(default="", max_length=64)
    source: str = Field(default="", max_length=64)
    client_ip: str = ""
    ua: str = Field(default="", max_length=512)
    # 下单前勾的几项和页面上协议的版本：交给 website.consent 校验并留痕，没勾全不建单
    consents: list[str] = Field(default_factory=list, max_length=8)
    terms_version: str = Field(default="", max_length=32)
    privacy_version: str = Field(default="", max_length=32)


class WebNotify(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    op: Literal["notify"] = "notify"
    pay_node: str
    headers: dict[str, str] = Field(default_factory=dict)
    raw: bytes = b""


class WebPoll(BaseModel):
    op: Literal["poll"] = "poll"
    view_token: str = Field(min_length=8, max_length=64)


class WebRefund(BaseModel):
    op: Literal["refund"] = "refund"
    order_id: int
    amount_fen: int = Field(ge=1)
    scope: str = Field(default="full", max_length=32)
    reason: str = Field(default="", max_length=200)


class WebSweep(BaseModel):
    op: Literal["sweep"] = "sweep"
    now: datetime | None = None


class WebWxStart(BaseModel):
    """微信里付款：要不要先去服务号网页授权拿 openid（设计 11 第五节）。"""

    op: Literal["wx_start"] = "wx_start"
    view_token: str = Field(min_length=8, max_length=64)


class WebJsapiPrepare(BaseModel):
    """网页授权回来了：拿 openid 去微信 JSAPI 下单，把调起支付的参数记在这张待付款单上。openid 不落库、不进日志。"""

    op: Literal["jsapi_prepare"] = "jsapi_prepare"
    view_token: str = Field(min_length=8, max_length=64)
    openid: str = Field(min_length=6, max_length=128, repr=False)


class WebRepay(BaseModel):
    """手机浏览器（微信 H5）：点「打开微信付款」时要一个新鲜的 h5_url（官方：有效期 5 分钟，过了用原参数重新下单）。"""

    op: Literal["repay"] = "repay"
    view_token: str = Field(min_length=8, max_length=64)
    client_ip: str = ""


class WebIn(RootModel[Annotated[WebCheckout | WebNotify | WebPoll | WebRefund | WebSweep | WebWxStart | WebJsapiPrepare
                                | WebRepay, Field(discriminator="op")]]):
    """channel.web 的输入：checkout 下单 / notify 网关通知 / poll 付款页轮询 / refund 后台退款 / sweep 定时关过期单、查退款 /
    wx_start 微信里付款要不要先授权 / jsapi_prepare 授权回来下 JSAPI 单 / repay 手机浏览器要新的微信付款链接。"""


class WebOut(BaseModel):
    """channel.web 的统一输出（设计里的 ChannelOut + 付款指令）。"""

    order_id: int | None = None
    code: str = ""
    view_token: str = ""
    status: str = ""
    total_fen: int = 0
    expires_at: datetime | None = None
    paid_at: datetime | None = None
    pay: dict[str, Any] = Field(default_factory=dict, description="{kind, payload, method, simulated}；kind：qr 扫码 / redirect 跳转 / "
                                "jsapi 微信里调起 / oauth 先去网页授权 / h5 点了再要微信付款链接")
    ack: dict[str, Any] | str = ""
    ack_status: int = 200
    dedupe_key: str = ""
    refund_id: int | None = None
    swept: dict[str, int] = Field(default_factory=dict)
    why: str = ""


# ---------------------------------------------------------------- trigger.confirm_timeout

class TickIn(BaseModel):
    now: datetime | None = Field(default=None, description="现在（测试里用假时钟）；空 = 真的现在")


class TickOut(BaseModel):
    checked: int = 0
    completed: list[int] = Field(default_factory=list)
    skipped: list[int] = Field(default_factory=list, description="确认收货节点没认的（来源表不认 auto、状态变了）")
    reminded: list[int] = Field(default_factory=list, description="这一轮发了到期前提醒的单（同一版只发一次）")
    hours: int = 0
