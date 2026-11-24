"""开票节点的输入输出（Pydantic）。节点文件只 import 这里和 service，不互相 import。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Source = Literal["checkout", "pay_page", "delivery", "admin"]


class InvoiceFields(BaseModel):
    """客人填的发票信息（字段校验在 checks.clean_fields；这里只限长度，防超长）。"""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    kind: Literal["normal", "special"] = Field(default="normal", description="normal 电子普通发票 / special 增值税专用发票（设置里开了才收）")
    title_kind: Literal["unit", "personal"] = Field(default="unit", description="unit 单位 / personal 个人（设置里开了才收）")
    title: str = Field(default="", max_length=200, description="抬头：单位全称")
    tax_id: str = Field(default="", max_length=40, description="纳税人识别号（统一社会信用代码）")
    email: str = Field(default="", max_length=200, description="收发票的邮箱")
    bank_name: str = Field(default="", max_length=120, description="开户行（专票）")
    bank_account: str = Field(default="", max_length=60, description="银行账号（专票）")
    address: str = Field(default="", max_length=200, description="单位地址（专票）")
    phone: str = Field(default="", max_length=40, description="单位电话（专票）")
    remark: str = Field(default="", max_length=200, description="发票备注（选填）")


class RequestIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source: Source = Field(description="checkout 下单页预填（还没订单）/ pay_page 付款页 / delivery 交付页 / admin 后台录入")
    order_id: int | None = Field(default=None, description="挂哪一单；下单页预填时为空")
    checkout_token: str = Field(default="", max_length=64, description="付款页令牌（下单页预填、付款页申请时给）")
    fields: InvoiceFields
    confirmed: bool = Field(default=False, description="客人在核对弹窗里点了「核对无误」；没点不收")
    by: str = Field(default="customer", max_length=32)


class RequestOut(BaseModel):
    invoice_id: int | None = None
    step: str = ""
    stage: str = ""
    note: str = ""
    field: str = Field(default="", description="出口 invalid 时：哪个字段不对")


class GateIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    invoice_id: int | None = Field(default=None, description="流程里调时给（引擎带上）")
    order_id: int | None = Field(default=None, description="别的模块直接问「这单能不能开」时给")
    admin: bool = Field(default=False, description="后台手工录的：不看渠道名单和申请期限")
    via: str = "call"
    event: str = ""


class GateOut(BaseModel):
    order_id: int | None = None
    paid: str = ""
    refunded: str = ""
    max_amount: str = Field(default="", description="最多能开多少（实付 − 已退）")
    reason: str = ""
    warnings: list[str] = Field(default_factory=list)


class IssueFileIn(BaseModel):
    filename: str = Field(min_length=1, max_length=200)
    data: bytes


class IssueIn(BaseModel):
    invoice_id: int
    files: list[IssueFileIn] = Field(default_factory=list)
    amount: str = Field(default="", max_length=16, description="开票金额；空 = 实付 − 已退")
    invoice_no: str = Field(default="", max_length=32)
    note: str = Field(default="", max_length=200)
    by: str = Field(default="edison", max_length=32)


class IssueOut(BaseModel):
    invoice_id: int
    amount: str = ""
    file_ids: list[int] = Field(default_factory=list)


class CloseIn(BaseModel):
    invoice_id: int
    reason: str = Field(default="", max_length=300)
    by: str = Field(default="edison", max_length=32)


class VoidIn(CloseIn):
    reopen: bool = Field(default=False, description="作废后照原信息（或 fields 改过的）新建一张待开票")
    fields: InvoiceFields | None = None


class CloseOut(BaseModel):
    invoice_id: int
    step: str = ""
    new_invoice_id: int | None = None
    note: str = ""


class NotifyIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    invoice_id: int
    via: str = "call"
    event: str = ""


class NotifyOut(BaseModel):
    invoice_id: int
    kind: str = ""
    email: str = Field(default="", description="sent 发了 / pending 待发（还没有发邮件的服务）/ skipped")
    chat: str = Field(default="", description="sent / queued 进了订单中枢的待发 / pending / skipped")


class SweepIn(BaseModel):
    now: datetime | None = None
    prefill_ttl_days: int = Field(default=7, ge=1, le=90, description="下单页预填留几天（INVOICE_PREFILL_TTL_DAYS）")


class SweepOut(BaseModel):
    promoted: int = 0
    still_waiting: int = 0
    refund_after_issue: list[int] = Field(default_factory=list)
    prefills_dropped: int = 0
