"""sku.catalog 价目与对外说明。"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.intake import pricing
from app.intake.config_store import load_config


class CatalogIn(BaseModel):
    pass


class TierRow(BaseModel):
    key: str
    name: str
    min_minutes: int
    max_minutes: int
    max_pages: int
    prices: dict[str, Decimal | None] = Field(description="p1 / p2_3 / p4_5，None = 不开放")
    std_hours: int
    rush_hours: int | None
    rush: bool


class PriceCatalog(BaseModel):
    tiers: list[TierRow]
    bands: list[dict]
    addons: list[dict] = Field(description="[{key, name, price, note}]")
    find_refs_extra_hours: int
    revisions_included: int
    auto_confirm_days: int
    page_rule_text: str
    deliver_text: str
    notes_text: str
    materials: dict = Field(default_factory=dict, description="下单前准备好这些：各场合必须发的、有的话更好的（设置里的资料清单）")
    price_hash: str = Field(description="价目指纹；变了说明对外文案要重发")


def handler(call: NodeCall, data: CatalogIn) -> NodeResult:
    return NodeResult(exit="ok", output=PriceCatalog.model_validate(pricing.catalog(load_config(call.db))))


CARD = NodeCard(
    id="sku.catalog",
    name="价目与对外说明",
    description="出整张价目：四个时长档（时长、页数上限、各篇数档的价、标准 / 加急时限）、篇数档、加购、含几轮改、"
                "自动确认天数、交付什么和注意事项、下单前要准备的资料（按场合），外加价目指纹。下单页、公众号说明、平台商品页文案都从这里填价，不手写。",
    category="订单",
    tech=["Python 纯函数（app/intake/pricing.py 的 catalog）", "设置 intake_kv（BizConfig schema 3）"],
    input_model=CatalogIn,
    output_model=PriceCatalog,
    exits=[NodeExit(key="ok", label="出了", kind="ok")],
    config=["duration_tiers、paper_bands、addons、find_refs_extra_hours、revisions_included、auto_confirm_days、"
            "page_rule_text、deliver_text、notes_text", "occasions 的 must / nice、materials：资料清单"],
    emits=["无（改价时设置保存记 intake.config_changed）"],
    listens=["无"],
    replaceable=["暂无"],
    failure="只读，随便重试。",
    owner="A",
    status="要新做",
)
register(CARD, handler)
