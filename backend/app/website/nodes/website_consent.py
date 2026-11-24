"""website.consent 记下单前（或开工前）的同意。"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, model_validator

from app.core.events import record_event
from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.website.consent import REQUIRED_CONSENTS, VERSION_PATTERN


class ConsentIn(BaseModel):
    checkout_token: str = Field(default="", max_length=64, pattern=r"^[A-Za-z0-9_\-]*$",
                                description="付款单令牌（自有网页下单：建单时拿到的 view_token）")
    order_id: int | None = Field(default=None, ge=1,
                                 description="订单号（小红书、闲鱼这类平台单：客人在需求确认卡上点「对，开工」前勾的）")
    items: list[str] = Field(description="勾了哪几项：terms_privacy / ai_processing / custom_no_refund")
    terms_version: str = Field(default="", max_length=32, description="页面上用户协议的版本（日期，如 2026-11-18）")
    privacy_version: str = Field(default="", max_length=32, description="页面上隐私政策的版本（日期）")
    ip: str = Field(default="", max_length=64)
    ua: str = Field(default="", max_length=300)

    @model_validator(mode="after")
    def _one_subject(self) -> "ConsentIn":
        for v in (self.terms_version, self.privacy_version):
            if v and not re.fullmatch(VERSION_PATTERN, v):
                raise ValueError("协议版本号的格式不对")
        if bool(self.checkout_token) == (self.order_id is not None):
            raise ValueError("付款单令牌和订单号要给且只给一个")
        if self.checkout_token and len(self.checkout_token) < 8:
            raise ValueError("付款单令牌太短")
        return self


class ConsentOut(BaseModel):
    ok: bool
    missing: list[str] = Field(default_factory=list, description="没勾的项")


def handler(call: NodeCall, data: ConsentIn) -> NodeResult:
    missing = [k for k in REQUIRED_CONSENTS if k not in data.items]
    if missing:
        return NodeResult(exit="missing", output=ConsentOut(ok=False, missing=missing),
                          detail="没勾全：" + "、".join(REQUIRED_CONSENTS[k] for k in missing))
    if not (data.terms_version and data.privacy_version):  # 勾了但没带协议版本：记下来也说不清同意的是哪一版
        return NodeResult(exit="missing", output=ConsentOut(ok=False), detail="没带上协议的版本号，刷新页面再勾一次")
    subject = f"checkout:{data.checkout_token}" if data.checkout_token else f"order:{data.order_id}"
    record_event(call.db, "website.consent", subject, {
        "items": sorted(set(data.items) & set(REQUIRED_CONSENTS)),
        "terms_version": data.terms_version, "privacy_version": data.privacy_version,
        "ip": data.ip, "ua": data.ua[:300], "by": call.by, "where": "checkout" if data.checkout_token else "brief"})
    return NodeResult(exit="ok", output=ConsentOut(ok=True))


CARD = NodeCard(
    id="website.consent",
    name="记下单前的同意",
    description="客人勾了「同意用户协议和隐私政策」「同意材料交给第三方 AI 处理（含境外）」「定制服务开工后不支持仅退款」"
                "三项，把勾了什么、看的是哪一版协议、什么时候、从哪个 IP，记成一条事件。自有网页单在建付款单时记（挂在付款单上，"
                "付款建单后抄一份到订单上）；小红书、闲鱼的单在需求确认卡点「对，开工」前记（挂在订单上）。以后有争议能拿出来。",
    category="关口",
    tech=["Python 纯函数", "事件表 events（core.events.record_event）",
          "channel.web 建单时调（app/shop/service.py record_consent）、需求卡确认时调（app/channels/brief_web.py）"],
    input_model=ConsentIn,
    output_model=ConsentOut,
    exits=[NodeExit(key="ok", label="记下了", kind="ok"), NodeExit(key="missing", label="没勾全", kind="fail")],
    config=["无（要勾哪几项写在 app/website/consent.py 的 REQUIRED_CONSENTS）"],
    emits=["website.consent"],
    listens=["无"],
    replaceable=["暂无"],
    failure="只写一条事件，同一张付款单 / 同一单重复记也无害（以最后一条为准）；没勾全返回 missing，不写，"
            "调它的 channel.web 不建单、需求卡不让点「对，开工」。",
    owner="官网（站点整合）",
    status="已有",
)
register(CARD, handler)
