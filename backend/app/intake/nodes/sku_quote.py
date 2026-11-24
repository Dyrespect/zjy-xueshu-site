"""sku.quote 货号与报价。"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.intake import clock, pricing, service
from app.intake.config_store import load_config
from app.intake.rules import plan_slot


class QuoteIn(BaseModel):
    minutes: int = Field(ge=1, le=600, description="汇报时长（分钟）")
    papers: int | None = Field(default=None, ge=1, le=50, description="材料篇数；没说就空，按 1 篇报并提醒问")
    pages: int | None = Field(default=None, ge=1, le=500, description="客户要求的页数（内容页）")
    rush: bool = Field(default=False, description="要不要加急")
    find_refs: bool = Field(default=False, description="要不要帮我找文献")
    extra_revisions: int = Field(default=0, ge=0, le=10, description="再改几轮（基础价含一轮）")


class QuoteOut(BaseModel):
    sku: str = ""
    sku_name: str = ""
    base_price: str = ""
    addons: list[dict] = Field(default_factory=list, description="[{key, name, price}]")
    total: str = ""
    hours: int = 0
    max_pages: int = 0
    rush_ok: bool = False
    rush_why: str = ""
    notes: list[str] = Field(default_factory=list, description="升档原因、篇数按几篇算……")
    line: str = Field(default="", description="一行报价，数字全是代码算的")
    why: str = Field(default="", description="报不了的原因")
    earliest_start: date | None = Field(default=None, description="按现在的名额和排期，最早哪天开工")
    eta_date: date | None = Field(default=None, description="预计哪天交第一版（水印版）")
    queue_full: bool = Field(default=False, description="往后几天名额都满了")


def handler(call: NodeCall, data: QuoteIn) -> NodeResult:
    cfg = load_config(call.db)
    q = pricing.quote(cfg, minutes=data.minutes, papers=data.papers, pages=data.pages, rush=data.rush,
                      find_refs=data.find_refs, extra_revisions=data.extra_revisions)
    if not q.ok:
        return NodeResult(exit="fail", output=QuoteOut(why=q.why, line=q.line(cfg)), detail=q.why)
    out = QuoteOut(
        sku=q.sku, sku_name=pricing.sku_name(cfg, q.sku), base_price=pricing.fmt_money(q.base_price),
        addons=[{"key": k, "name": n, "price": pricing.fmt_money(p)} for k, n, p in q.addons],
        total=pricing.fmt_money(q.total), hours=q.hours, max_pages=q.max_pages, rush_ok=q.rush_ok, rush_why=q.rush_why,
        notes=q.notes, line=q.line(cfg),
    )
    plan = plan_slot(clock.today(), service.booked_by_day(call.db), cfg, q.hours, rush=q.rush, now=clock.local_now())
    if plan is None:
        out.queue_full = True
    else:
        out.earliest_start, out.eta_date = plan.start_date, plan.eta_date
    return NodeResult(exit="ok", output=out)


CARD = NodeCard(
    id="sku.quote",
    name="货号与报价",
    description="按客人说的汇报时长、篇数、页数、要不要加急或帮找文献，算出货号（时长档 × 篇数档）、价格、页数上限、交付时限。"
                "时长超了升一档；页数超上限或轻量档不开 4–5 篇时自动按装得下的档报并说明。算价全用代码，不让模型算。",
    category="订单",
    tech=["Python 纯函数（app/intake/pricing.py）", "Decimal 算价", "设置 intake_kv（BizConfig schema 3）",
          "排期（rules.plan_slot + 已排的单），给最早开工、预计交付"],
    input_model=QuoteIn,
    output_model=QuoteOut,
    exits=[NodeExit(key="ok", label="报出价了", kind="ok"),
           NodeExit(key="fail", label="报不了（超过最长一档、超过 5 篇、加购不卖）", kind="fail")],
    config=["duration_tiers：时长档的时长上限、页数上限、价格、标准 / 加急时限、开不开加急", "paper_bands：篇数档",
            "addons：加急、再改一轮、帮我找文献的价", "find_refs_extra_hours：帮我找文献加几小时", "page_rule_text：页数怎么算",
            "daily_quota、queue_horizon_days、work_start_hour：排期"],
    emits=["无"],
    listens=["无"],
    replaceable=["以后自有网页下单页的报价（模块 B）也调这个节点，不另写", "压价只改设置里的价格"],
    failure="只读，没有副作用，随便重试；设置坏了（没有价目）返回 fail。最早开工按现在的名额算，不占名额（不保证）。",
    owner="A",
    status="要改",
)
register(CARD, handler)
