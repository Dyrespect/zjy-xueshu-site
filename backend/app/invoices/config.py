"""开票的设置（存在 invoice_kv 的 settings 一条，后台「发票 → 设置」改）。设计第四节。

默认值按 Edison 11-18 的话填（小规模纳税人、技术服务费、专票先关）；税率留空等财务填，不编数。
这几项在 FINANCE_FIELDS 里，后台显示「待财务确认」，财务确认一项就勾一项（confirmed_fields）。
开票金额 = 实付（含加购、含税，不另加税）是规矩不是设置（Edison：客人付多少就开多少），见 facts.py。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.events import record_event
from app.invoices.models import InvoiceKV

FIELD_KEYS = ("title", "tax_id", "email", "bank_name", "bank_account", "address", "phone")
FIELD_LABELS = {"title": "抬头（单位全称）", "tax_id": "纳税人识别号", "email": "收发票的邮箱", "bank_name": "开户行",
                "bank_account": "银行账号", "address": "单位地址", "phone": "单位电话", "remark": "发票备注"}
FILE_TYPES = ("pdf", "ofd", "xml")
PLATFORMS = ("web", "fk", "manual", "xhs", "xy", "dy", "legacy")

# 要财务拍板的几项（后台标「待财务确认」）
FINANCE_FIELDS: dict[str, str] = {
    "taxpayer_type": "纳税人类型（Edison 11-18：先按小规模纳税人）",
    "tax_rate": "税率（Edison：到时候问财务；留空，不编数）",
    "item_name": "开票项目名称（Edison 11-18：技术服务费）",
    "special_enabled": "开不开专票（没定，先关）",
    "allow_personal": "收不收个人抬头（我的建议先不收：科研经费报销多要单位抬头）",
    "apply_window_days": "订单完成后多久内能申请（0 = 不限）",
}


class InvoiceConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = True  # 客人能不能申请（关了下单页、交付页都不出发票入口）
    seller_name: str = Field(default="杭州竹涧云科技有限公司", max_length=60)
    seller_tax_id: str = Field(default="91330110MAKFUNHCXY", max_length=24)
    taxpayer_type: Literal["小规模纳税人", "一般纳税人", ""] = "小规模纳税人"
    tax_rate: str = Field(default="", max_length=16)  # 例「1%」「3%」「6%」；空 = 待财务填
    item_name: str = Field(default="技术服务费", max_length=40)
    special_enabled: bool = False
    allow_personal: bool = False
    allow_remark: bool = True
    required_normal: list[str] = Field(default_factory=lambda: ["title", "tax_id", "email"])
    required_special: list[str] = Field(default_factory=lambda: list(FIELD_KEYS))
    eligible_platforms: list[str] = Field(default_factory=lambda: ["web"])
    apply_window_days: int = Field(default=0, ge=0, le=3650)
    file_types: list[str] = Field(default_factory=lambda: list(FILE_TYPES))
    file_max_mb: int = Field(default=10, ge=1, le=50)
    customer_notice: str = Field(default="抬头和税号开出后改不了，请对着单位财务给的信息填，提交前再核对一遍。", max_length=200)
    promise_text: str = Field(default="开好后发到你填的邮箱，这个页面也能下载。", max_length=200)
    notice_issued: str = Field(default="你的发票开好了（单号 {order_no}，{amount} 元）。打开交付页就能下载：{url}", max_length=300)
    notice_rejected: str = Field(default="你的发票申请没开成（单号 {order_no}）：{reason}。改好后在交付页重新申请：{url}", max_length=300)
    notice_voided: str = Field(default="你单号 {order_no} 的发票作废了：{reason}。重开的那张开好会再通知你；也可以在交付页重新申请：{url}",
                               max_length=300)
    confirmed_fields: list[str] = Field(default_factory=list)  # 财务已确认的（FINANCE_FIELDS 里的键）

    @field_validator("required_normal", "required_special")
    @classmethod
    def _fields_known(cls, v: list[str]) -> list[str]:
        bad = [x for x in v if x not in FIELD_KEYS]
        if bad:
            raise ValueError(f"不认识的字段：{'、'.join(bad)}")
        return list(dict.fromkeys(v))

    @field_validator("eligible_platforms")
    @classmethod
    def _platforms_known(cls, v: list[str]) -> list[str]:
        bad = [x for x in v if x not in PLATFORMS]
        if bad:
            raise ValueError(f"不认识的渠道：{'、'.join(bad)}")
        return list(dict.fromkeys(v))

    @field_validator("file_types")
    @classmethod
    def _types_known(cls, v: list[str]) -> list[str]:
        bad = [x for x in v if x not in FILE_TYPES]
        if bad or not v:
            raise ValueError(f"发票文件只能是 {'、'.join(FILE_TYPES)}")
        return list(dict.fromkeys(v))

    @field_validator("confirmed_fields")
    @classmethod
    def _finance_known(cls, v: list[str]) -> list[str]:
        return [x for x in dict.fromkeys(v) if x in FINANCE_FIELDS]

    def required(self, kind: str, title_kind: str = "unit") -> list[str]:
        base = self.required_special if kind == "special" else self.required_normal
        # 抬头、邮箱总是要；单位抬头的税号总是要（报销靠它），个人抬头不要税号
        out = list(dict.fromkeys(["title", "email", *base, *(["tax_id"] if title_kind == "unit" else [])]))
        return [f for f in out if not (title_kind == "personal" and f == "tax_id")]

    def kinds(self) -> list[str]:
        return ["normal", "special"] if self.special_enabled else ["normal"]

    def pending_finance(self) -> list[str]:
        return [k for k in FINANCE_FIELDS if k not in self.confirmed_fields]


def load_config(db: Session) -> InvoiceConfig:
    row = db.get(InvoiceKV, "settings")
    return InvoiceConfig.model_validate(row.value if row is not None else {})


def save_config(db: Session, data: dict, *, by: str) -> InvoiceConfig:
    """校验后存；记 invoice.config_changed（改了哪些字段、改前改后）。调用方提交。"""
    before = load_config(db)
    cfg = InvoiceConfig.model_validate({**before.model_dump(), **data})
    changed = [k for k, v in cfg.model_dump().items() if getattr(before, k) != v]
    row = db.get(InvoiceKV, "settings")
    if row is None:
        row = InvoiceKV(key="settings")
        db.add(row)
    row.value, row.updated_at, row.by = cfg.model_dump(), utcnow(), by[:32]
    record_event(db, "invoice.config_changed", "invoice:settings", {
        "fields": changed, "before": {k: getattr(before, k) for k in changed},
        "after": {k: getattr(cfg, k) for k in changed}, "by": by})
    return cfg
