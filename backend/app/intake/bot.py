"""接单助手（assistant.sales 节点的实现，业务员 + 客服）：读「现在的情况」→ 模型判断、说话 → 点名调用登记好的工具 → 回复直接发出去。

照架构第四节（小光最后定的骨架）和 11-18 的订单中枢契约：
- 两种模式：没认领（这个人没有在走的单）= 访客问答 visitor_qa，只许问价、讲交付什么、发付款方式、发负责人微信，
  不收资料、不记制作信息；有在走的单 = serve，记信息、登记材料、跟进度、转告制作方、收修改、撤单。
- 客人发来的激活码在收消息时就由代码认领（service.claim_codes_in → order.claim 节点），结果写进「现在的情况」；
  模型没有核销工具。入口模块（D）的 entry.route 做好以后接手这一步。
- 没认领的会话每天回复有上限（设置 visitor_daily_limit、visitor_global_daily_limit），超了不调模型，回一句固定话。
- 算价全用代码（sku.quote）；开不开工、排期、状态由代码和流程引擎定（rules.py、flow.py）。
- 每一趟留记录（BotRun）：给模型的情况、调了哪些工具、回复、用量。
"""

from __future__ import annotations

import logging
import random
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, RunContext, Tool
from pydantic_ai.usage import UsageLimits
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import Database, utcnow
from app.core.events import record_event
from app.core.nodes import NodeCall, run_node
from app.intake import clock, codes, flow, materials, pricing
from app.intake.config_store import BizConfig, load_config, payment_message, terms_message
from app.intake.llm import model_label
from app.intake.reception import guide as rguide
from app.intake.reception import intent as rintent
from app.intake.reception import kb as rkb
from app.intake.reception import style as rstyle
from app.intake.reception import wire as rwire
from app.intake.models import (
    MATERIAL_PURPOSES,
    STAGE_LABELS,
    BotRun,
    Customer,
    FileRecord,
    Message,
    Order,
    Outbox,
    ProductionMessage,
)
from app.intake.rules import (
    OrderFacts,
    Plan,
    effective_papers,
    fit_problems,
    latest_ok_eta,
    missing_materials,
    plan_slot,
)
from app.intake.service import (
    Ctx,
    add_need,
    add_production_message,
    asset_path,
    booked_by_day,
    cancel_order as cancel_order_db,
    collect_for,
    create_outbox,
    display_name,
    materials_list_text,
    order_facts,
    production_messages,
    refresh_status,
    revisions_left,
    submit_revision as submit_revision_db,
    unrelayed_from_maker,
    window_info,
)

log = logging.getLogger("app.intake.bot")

PROMPT_DIR = Path(__file__).parent / "prompts"
RECENT_LIMIT = 16
OWNER_REASONS = ("退款", "投诉", "价格", "范围外", "要真人", "激活码", "来不及", "档位", "其他")
ASK_KINDS = ("补充要求", "问题", "回答")
LANGUAGES = ("中文", "英文", "中英")
OWNER_QR_COOLDOWN = timedelta(hours=24)
VISITOR_TOOLS = ("quote_price", "send_terms", "send_payment", "send_owner_wechat", "send_sample", "send_materials")


def load_rules() -> str:
    return "\n\n".join(p.read_text(encoding="utf-8").strip() for p in sorted(PROMPT_DIR.glob("*.md")))


# ---------------------------------------------------------------- 这一趟的快照

@dataclass
class ToolLog:
    name: str
    args: dict[str, Any]
    result: str
    summary: str


class RevisionPoint(BaseModel):
    """改稿单的一条。"""

    page: int | None = Field(default=None, description="第几页（水印版底栏的「第 N 页」）；整体意见就空着")
    text: str = Field(description="这页改成什么，客户的原话照抄放进去")


@dataclass
class BotDeps:
    cfg: BizConfig
    today: date
    facts: OrderFacts
    booked: dict[date, int]
    stage: str
    customer_name: str
    mode: str = "visitor_qa"  # visitor_qa 没认领只问答 | serve 有在走的单
    database: Database | None = None
    ctx: Ctx | None = None
    customer_id: int = 0
    order_id: int = 0
    customer_said: str = ""  # 客户说过的话（核对称呼是不是客户自己说的）
    queued_eta: date | None = None
    due_hours: int | None = None
    started: bool = False
    delivered: bool = False
    after_delivery: bool = False  # 已交付后还能用剩下的修改
    voided: bool = False
    terms_sent_before: bool = False  # 这个会话之前就发过交付和注意事项（客户看到了）
    rush_today: int = 0
    revisions_left: int = 0
    payment_ready: bool = False
    payment_recent: bool = False
    owner_qr_ready: bool = False
    owner_qr_recent: bool = False
    maker_new: list[tuple[int, str, str]] = field(default_factory=list)
    maker_latest: str = ""
    claim_notes: list[str] = field(default_factory=list)  # 这一趟之前代码认领激活码的结果
    collect_ask: str = ""  # intake.collect：还缺什么（一句话）
    brief_line: str = ""  # 需求卡确认了没有（09 需求引导：需求卡由表单收，助手只提醒去点）
    brief_ok: bool = True
    collect_blocker: str = ""
    other_orders: list[str] = field(default_factory=list)  # 这个人还有别的单在走
    memory_brief: str = ""
    platform: str = ""
    sku_name: str = ""
    max_pages: int | None = None
    # 这一趟要落库的
    logs: list[ToolLog] = field(default_factory=list)
    changes: dict[str, Any] = field(default_factory=dict)
    quotes: list[str] = field(default_factory=list)
    nickname: str = ""
    purposes: dict[int, tuple[str, str]] = field(default_factory=dict)
    owner: list[tuple[str, str]] = field(default_factory=list)
    owner_qr: bool = False
    terms_head: str | None = None  # 这一趟要发交付和注意事项（带这一行报价；空字符串 = 不带报价）
    payment: bool = False
    to_maker: list[tuple[str, str]] = field(default_factory=list)
    revision_items: list[dict[str, Any]] = field(default_factory=list)
    cancel_why: str = ""
    facts_round: int = 0
    # 接待机器人（reception/）：知识库、这一轮的判断、说话检查改过几次
    kb: Any = None
    route: Any = None
    style_fixes: list[str] = field(default_factory=list)
    recent_bot_texts: list[str] = field(default_factory=list)
    samples_out: list[int] = field(default_factory=list)  # 这一趟要发的样张（知识库 samples 的下标）
    samples_recent: set[int] = field(default_factory=set)  # 24 小时内发过的样张
    will_disclose: bool = False  # 这一趟回复前面要加表明身份那句（会话开头）
    # 资料清单（app/intake/materials.py）：这一趟要原样发哪个场合的（空 = 不发）、这单哪几个场合发过了
    materials_out: str = ""
    materials_listed: set[str] = field(default_factory=set)

    @property
    def serving(self) -> bool:
        return self.mode == "serve"

    # ---- 给工具用的小算盘（只看快照） ----
    def quote_for(self, minutes: int | None = None, papers: int | None = None, pages: int | None = None,
                  rush: bool = False, find_refs: bool = False) -> pricing.Quote | None:
        f = self.facts
        if minutes is None:
            minutes = f.duration_min
        if papers is None and self.serving:
            papers, _ = effective_papers(f)
        if pages is None and self.serving:
            pages = f.page_count
        if minutes is None:
            return None
        return pricing.quote(self.cfg, minutes=minutes, papers=papers, pages=pages, rush=rush,
                             find_refs=find_refs or (self.serving and f.find_refs))

    def plan(self, hours: int, rush: bool) -> Plan | None:
        return plan_slot(self.today, self.booked, self.cfg, hours, rush=rush, now=clock.local_now())

    def when_line(self, q: pricing.Quote, present: date | None) -> str:
        """按现在排队算最早哪天开工、几小时交、赶不赶得上汇报日（代码算的）。"""
        plan = self.plan(q.hours, q.rush)
        if plan is None:
            return f"往后 {self.cfg.queue_horizon_days} 天名额都满了"
        start = "今天" if plan.start_date == self.today else clock.fmt_date(plan.start_date)
        line = f"现在买的话最早{start}开工，开工后 {q.hours} 小时内交第一版（{clock.fmt_date(plan.eta_date)}）"
        if present is not None:
            ok = plan.eta_date <= latest_ok_eta(present, self.cfg)
            line += "，赶得上汇报" if ok else f"，赶不上（要在 {clock.fmt_date(latest_ok_eta(present, self.cfg))}前交）"
        return line

    def still_missing(self) -> list[str]:
        f = self.facts
        out: list[str] = []
        if not f.occasion:
            out.append("场合")
        else:
            missing = missing_materials(f, self.cfg) or []
            if missing:  # 点名缺的那几样，用资料清单里对客人的叫法
                out.append("材料：" + "、".join(materials.missing_names(self.cfg, f.occasion, missing, find_refs=f.find_refs)))
            elif f.occasion == "其他" and not f.files:
                out.append("材料")
        if f.duration_min is None:
            out.append("讲几分钟")
        elif f.duration_default and not f.duration_confirmed:
            out.append(f"客户对默认 {f.duration_min} 分钟点头")
        if f.present_date is None:
            out.append("哪天汇报")
        return out

    def next_steps(self) -> str:
        """代码算的下一步（模型照着做，不用自己推）。"""
        f = self.facts
        if not self.serving:
            if self.claim_notes and any("认领上了" in n for n in self.claim_notes):
                return "刚认领上，下一步收资料。"
            step = ("客户问价 → quote_price（按客户说的时长、篇数、页数、要不要加急或帮找文献，代码算）；"
                    "客户问要准备什么资料 → 知道场合就 send_materials（这个场合要的原样发过去），不知道先问一句场合；"
                    "客户想买 → 先 send_terms 把交付什么和注意事项原样发过去，客户说可以再 send_payment；"
                    "客户发了激活码 → 系统已经在调你之前认领了，看【激活码】那一行。")
            return "还没认领激活码：只问答，不收资料、不记制作信息（客户发文件就说先把激活码发来）。" + step
        if self.voided:
            return "这单作废了，不再做。客户有疑问 → send_owner_wechat。"
        if self.stage == "delivered" and not self.after_delivery:
            return "最终版发过了。客户还要改且还有修改次数 → 问清楚哪一页改什么再 submit_revision。"
        if self.stage == "completed":
            return "客户确认收货了，最终版在发（制作方传上来就自动发）。客户问 → 告诉他马上发。"
        if self.delivered or self.after_delivery:
            left = self.revisions_left
            confirm = ("满意的话请他在交付页点「确认收货」，确认后马上发可编辑的 PPT 和讲稿"
                       if "customer" in self.cfg.delivery.sources(self._platform()) else
                       f"满意的话请他到平台订单里点「确认收货」，平台确认后发可编辑的 PPT 和讲稿")
            return (f"交了第 {self.facts_round} 版水印版。客户要改：问清楚第几页、改成什么，一次收齐再 submit_revision；"
                    f"还能改 {left} 轮。" + ("" if left else "修改轮数用完了：再改要买「再改一轮」的码（客户发码系统会认领），"
                                            "或者 send_owner_wechat。") + confirm + "。")
        if self.started:
            return "已经开工在做了。客户补充要求或问能不能做某件事 → ask_maker；问进度 → check_progress。"
        if self.collect_blocker:
            return f"货号装不下：{self.collect_blocker}。告诉客户差在哪，再 send_owner_wechat（reason=档位）。"
        fit = fit_problems(f, self.cfg)
        if fit and f.duration_min is not None:
            return f"货号装不下：{'；'.join(fit)}。告诉客户差在哪，再 send_owner_wechat（reason=档位）。"
        if f.queued and self.queued_eta:
            return f"资料齐了，排进队了，开工后 {self.due_hours or '?'} 小时内交第一版（{clock.fmt_date(self.queued_eta)}前）。客户再补充要求 → ask_maker。"
        if self.collect_ask:
            hint = ("场合能从话里或文件名看出来就直接记（「组里的要求」「组会」是组会文献），只发了论文的按组会文献记，不用问；"
                    "场合一记下，系统会把这个场合要的资料原样发一遍。"
                    if not f.occasion else "要的资料系统已经整张发过了，别再列一遍，点名要缺的那一两样。")
            return f"按清单{self.collect_ask}。{hint}一条里问完（一次一两件），客户发了就记、登记。"
        if not self.brief_ok:
            return "资料齐了，就差需求确认卡：把【需求卡】那一行的链接发给他，请他看一眼点「对，开工」，确认了才排期开工。"
        return "资料齐了，系统在排期：告诉客户收齐了，排好会告诉他哪天交。"

    def materials_due(self, occasion: str) -> bool:
        """认领后场合刚定：这单这个场合的资料清单没发过、资料还没齐、还没开工，就跟着这一趟发一遍。"""
        if not self.serving or self.started or self.facts.queued or self.stage not in ("claimed", "collecting"):
            return False
        if self.cfg.rule(occasion) is None or occasion in self.materials_listed:
            return False
        return bool(self.still_missing())

    def _platform(self) -> str:
        return self.platform or "legacy"

    def log(self, name: str, args: dict[str, Any], result: str, summary: str) -> str:
        self.logs.append(ToolLog(name, {k: v for k, v in args.items() if v not in (None, "")}, result, summary))
        return result

    def need_order(self, name: str) -> str | None:
        if not self.serving:
            return self.log(name, {}, "还没认领激活码，先不收资料、不记制作信息。让客户先把激活码发过来（PSY- 开头）。",
                            f"{name}：还没认领，没做")
        return None


# ---------------------------------------------------------------- 工具：对需求（serve）

def record_info(
    ctx: RunContext[BotDeps],
    occasion: str | None = None,
    title: str | None = None,
    duration_min: int | None = None,
    paper_count: int | None = None,
    page_count: int | None = None,
    present_date: str | None = None,
    present_date_text: str | None = None,
    school: str | None = None,
    language: str | None = None,
    structure: str | None = None,
    requirement_quote: str | None = None,
    nickname: str | None = None,
) -> str:
    """记下客户这次说清楚的信息（认领激活码以后才用）。只填这次新知道的，别的留空。

    Args:
        occasion: 场合，只能是情况里列的几种之一（组会文献、课程文献、开题、中期、答辩、会议、其他）。
        title: 论文或汇报的题目；帮找文献的单写要找的方向和关键词。
        duration_min: 客户明确说的汇报时长（分钟）。客户说「不设时间」时不要填这里，用 default_duration。
        paper_count: 要讲几篇文献 / 材料。
        page_count: 客户要求做多少页（内容页）。
        present_date: 汇报日期，YYYY-MM-DD，按情况里的「今天」换算。
        present_date_text: 客户说日期的原话，如「下周三」「14号」。
        school: 学校。
        language: 中文、英文或中英。
        structure: 一句话的页数或范围硬要求（如「只做讨论和结论」）。
        requirement_quote: 组里、老师或客户自己对 PPT 的要求，照客户原话一字不改抄过来；一大段要求、提纲、板块结构都放这里。
        nickname: 客户自己说的称呼。客户没说过就不填，不要编。
    """
    d = ctx.deps
    if (no := d.need_order("record_info")) is not None:
        return no
    f = d.facts
    done: list[str] = []
    if occasion:
        occasion = occasion.strip()
        if occasion not in d.cfg.occasions:
            raise ModelRetry(f"场合只能是：{'、'.join(d.cfg.occasions)}")
        f.occasion = occasion
        d.changes["occasion"] = occasion
        done.append(f"场合 {occasion}")
    if title:
        f.title = title.strip()[:256]
        d.changes["title"] = f.title
        done.append("题目")
    if duration_min is not None:
        if not 1 <= duration_min <= 240:
            raise ModelRetry("时长要在 1 到 240 分钟之间")
        f.duration_min, f.duration_default, f.duration_confirmed = duration_min, False, False
        d.changes.update(duration_min=duration_min, duration_default=False, duration_confirmed=False)
        done.append(f"时长 {duration_min} 分钟")
    if paper_count is not None:
        if not 1 <= paper_count <= 50:
            raise ModelRetry("篇数要在 1 到 50 之间")
        f.paper_count = paper_count
        d.changes["paper_count"] = paper_count
        done.append(f"{paper_count} 篇")
    if page_count is not None:
        if not 1 <= page_count <= 500:
            raise ModelRetry("页数要在 1 到 500 之间")
        f.page_count = page_count
        d.changes["page_count"] = page_count
        done.append(f"{page_count} 页")
    if present_date:
        try:
            pd = date.fromisoformat(present_date.strip())
        except ValueError as e:
            raise ModelRetry("present_date 要写成 YYYY-MM-DD") from e
        if pd < d.today:
            raise ModelRetry(f"{pd.isoformat()} 已经过去了（今天 {d.today.isoformat()}），重新换算或问客户")
        if pd > d.today + timedelta(days=365):
            raise ModelRetry("日期离今天超过一年，重新换算")
        f.present_date = pd
        d.changes["present_date"] = pd
        done.append(f"汇报日 {pd.isoformat()}（{clock.weekday_cn(pd)}）")
    if present_date_text:
        f.present_date_text = present_date_text.strip()[:64]
        d.changes["present_date_text"] = f.present_date_text
    if school:
        f.school = school.strip()[:64]
        d.changes["school"] = f.school
        done.append(f"学校 {f.school}")
    if language:
        language = language.strip()
        if language not in LANGUAGES:
            raise ModelRetry("language 只能是：中文、英文、中英")
        f.language = language
        d.changes["language"] = language
        done.append(f"语言 {language}")
    if structure:
        f.structure_req = (f.structure_req + "；" if f.structure_req else "") + structure.strip()
        d.changes["structure_req"] = f.structure_req
        done.append("页数/结构要求")
    if requirement_quote and requirement_quote.strip():
        q = requirement_quote.strip()
        if q not in f.requirement_quotes:
            f.requirement_quotes.append(q)
            d.quotes.append(q)
        done.append("要求原话")
    if nickname:
        name = nickname.strip()[:64]
        if name not in d.customer_said or name in ("网页客户", "微信客户", "客户", "同学"):
            raise ModelRetry("称呼要是客户自己在对话里说过的；没说过就不填 nickname")
        d.nickname = name
        done.append(f"称呼 {d.nickname}")
    if not done:
        raise ModelRetry("没有填任何信息；没有新信息就不要调 record_info")
    args = dict(occasion=occasion, title=title, duration_min=duration_min, paper_count=paper_count, page_count=page_count,
                present_date=present_date, present_date_text=present_date_text, school=school, language=language,
                structure=structure, requirement_quote=(requirement_quote or "")[:80], nickname=nickname)
    tail = ""
    if occasion and d.materials_due(occasion):
        d.materials_out = occasion
        tail = (f"{materials.name_of(d.cfg, occasion)}要的资料清单（设置里的原文）会跟在你这条回复后面原样发出去，"
                "你别再列一遍，说一句「要发的我列在下面了」这类话就行。")
    return d.log("record_info", args, "已记下。" + tail + "下一步：" + d.next_steps(), "记下：" + "、".join(done))


def register_file(ctx: RunContext[BotDeps], file_id: int, purpose: str, note: str = "") -> str:
    """给客户发来的一个文件标用途（认领激活码以后才用）。

    Args:
        file_id: 情况里文件前面的编号（#12 就填 12）。
        purpose: 用途，只能是：论文、开题报告、进展、材料、数据、模板、其他。要汇报的文献、客户自己写的论文 / 文稿 / 毕业论文都算论文；开题 PPT 也算开题报告；中期的进展文稿或 PPT 算进展；实验材料、补充材料、译文、大纲、客户自己做的旧 PPT 算材料；配色或样式参考图、学校或组里的 PPT 模板算模板。场合是会议、答辩时，客户自己写的文稿登记成论文。
        note: 一句说明（可空），如「补充材料」「组里模板」。
    """
    d = ctx.deps
    if (no := d.need_order("register_file")) is not None:
        return no
    target = next((x for x in d.facts.files if x.id == file_id), None)
    if target is None:
        ids = "、".join(f"#{x.id}" for x in d.facts.files) or "（没有文件）"
        raise ModelRetry(f"没有 #{file_id} 这个文件，现在有：{ids}")
    if purpose not in MATERIAL_PURPOSES:
        raise ModelRetry(f"purpose 只能是：{'、'.join(MATERIAL_PURPOSES)}")
    target.purpose = purpose
    d.purposes[file_id] = (purpose, note.strip()[:256])
    return d.log("register_file", {"file_id": file_id, "purpose": purpose, "note": note},
                 f"#{file_id} 记为{purpose}。下一步：" + d.next_steps(), f"登记附件：{target.filename} → {purpose}")


def default_duration(ctx: RunContext[BotDeps], customer_agreed: bool) -> str:
    """客户没给时长（「不设时间」「讲清楚就行」）时用。时长是这个场合的默认值，由系统给：
    先调一次（customer_agreed=false）拿到默认值去问客户；客户点头后再调一次（customer_agreed=true）。

    Args:
        customer_agreed: 客户是否已经同意按默认时长做。
    """
    d = ctx.deps
    if (no := d.need_order("default_duration")) is not None:
        return no
    f = d.facts
    rule = d.cfg.rule(f.occasion)
    if rule is None:
        raise ModelRetry("场合还不知道，没有默认时长：先问清楚是什么场合")
    minutes = rule.default_minutes
    f.duration_min, f.duration_default, f.duration_confirmed = minutes, True, customer_agreed
    d.changes.update(duration_min=minutes, duration_default=True, duration_confirmed=customer_agreed)
    if customer_agreed:
        return d.log("default_duration", {"customer_agreed": True},
                     f"客户同意按 {minutes} 分钟。下一步：" + d.next_steps(), f"默认时长：客户同意 {minutes} 分钟")
    return d.log("default_duration", {"customer_agreed": False},
                 f"{f.occasion}默认 {minutes} 分钟。问客户「那我按 {minutes} 分钟做，可以吗」，等他点头。",
                 f"默认时长：问客户按 {minutes} 分钟行不行")


def check_progress(ctx: RunContext[BotDeps]) -> str:
    """查这单现在到哪一步、排期和预计交付、制作方最近说了什么。客户问进度、问什么时候好时用。"""
    d = ctx.deps
    if not d.serving:
        return d.log("check_progress", {}, "这个会话还没有订单（没认领激活码）。", "查了进度：还没有订单")
    f = d.facts
    status = STAGE_LABELS.get(d.stage, d.stage)
    if d.delivered or d.after_delivery:
        text = f"状态：{status}。水印版的交付页链接发过了，客户在那个页面看、提修改、确认收货。"
    elif d.started:
        eta = f"，开工后 {d.due_hours} 小时内交第一版（{clock.fmt_date(d.queued_eta)}前）" if d.due_hours and d.queued_eta else ""
        text = f"状态：{status}，做 PPT 的同事已经在做了{eta}。"
        if d.maker_latest:
            text += f"制作方最近说：{d.maker_latest}"
    elif f.queued and d.queued_eta:
        text = f"状态：排队，排在 {clock.fmt_date(f.start_date)}开工，开工后 {d.due_hours} 小时内交第一版。"
    else:
        text = f"状态：{status}。下一步：" + d.next_steps()
    return d.log("check_progress", {}, text, "查了进度")


# ---------------------------------------------------------------- 工具：报价、条款、收钱

def quote_price(ctx: RunContext[BotDeps], minutes: int | None = None, papers: int | None = None, pages: int | None = None,
                rush: bool = False, find_refs: bool = False, present_date: str | None = None) -> str:
    """报价（代码按价目和排队算好的，照它说）：货号（时长档 × 篇数档）、价格、页数上限、开工后几小时交、最早哪天交。
    客户问多少钱、多久、能不能加急、没有文献要帮找时用。

    Args:
        minutes: 汇报时长（分钟）；认领后的单不填就用记下的。
        papers: 要讲几篇；不知道就不填（按 1 篇报，会提醒你问）。
        pages: 客户要求的页数（内容页），没提就不填。
        rush: 客户要不要加急。
        find_refs: 客户没有文献、要我们帮找。
        present_date: 客户说的汇报日期 YYYY-MM-DD（算赶不赶得上），不知道就不填。
    """
    d = ctx.deps
    q = d.quote_for(minutes, papers, pages, rush, find_refs)
    if q is None:
        table = "；".join(pricing.price_table(d.cfg))
        return d.log("quote_price", {}, f"时长还不知道，先问讲几分钟、几篇。整张价目：{table}。", "报价：时长还不知道")
    if not q.ok:
        return d.log("quote_price", {"minutes": minutes, "papers": papers}, f"报不了：{q.why}。send_owner_wechat（reason=档位）。",
                     f"报价：报不了（{q.why}）")
    present = None
    if present_date:
        try:
            present = date.fromisoformat(present_date.strip())
        except ValueError as e:
            raise ModelRetry("present_date 要写成 YYYY-MM-DD") from e
    elif d.serving:
        present = d.facts.present_date
    parts = [q.line(d.cfg), f"页数上限 {q.max_pages} 页（{d.cfg.page_rule_text}）", d.when_line(q, present)]
    if not rush and q.rush_ok:
        a = d.cfg.addon("rush")
        parts.append(f"能加急：{a.name} +{a.price} 元，开工后 {pricing.promised_hours(d.cfg, q.tier, rush=True)} 小时内交（限名额、材料齐才排加急）")
    elif rush and not q.rush:
        parts.append(f"不能加急：{q.rush_why}")
    if q.notes:
        parts.append("说明：" + "；".join(q.notes))
    text = "；".join(parts) + "。不说「肯定」「保证」，说「最早」。"
    return d.log("quote_price", {"minutes": minutes, "papers": papers, "pages": pages, "rush": rush, "find_refs": find_refs},
                 text, "报价：" + q.line(d.cfg)[:100])


def send_terms(ctx: RunContext[BotDeps], minutes: int | None = None, papers: int | None = None, pages: int | None = None,
               rush: bool = False, find_refs: bool = False) -> str:
    """把「交付什么 + 注意事项」原样发给客户（设置里的固定原文，跟这条回复一起发，你不用复述）。客户想买之前一定要发；
    客户看完说可以，再 send_payment。知道时长就带上，前面会多一行代码算的报价。

    Args:
        minutes: 汇报时长（分钟），知道就填。
        papers: 几篇，知道就填。
        pages: 客户要求的页数，提了就填。
        rush: 客户要加急。
        find_refs: 客户要我们帮找文献。
    """
    d = ctx.deps
    if d.serving:
        return d.log("send_terms", {}, "这单已经认领了（付过款），不用再发交付和注意事项。", "发交付和注意事项：已经认领了")
    head = ""
    if minutes is not None:
        q = d.quote_for(minutes, papers, pages, rush, find_refs)
        if q is not None and q.ok:
            head = pricing.terms_head(d.cfg, q)
    d.terms_head = head
    return d.log("send_terms", {"minutes": minutes, "papers": papers, "rush": rush, "find_refs": find_refs},
                 "交付和注意事项（设置里的原文" + ("，前面一行是代码算的报价" if head else "") + "）会排在你这条回复前面原样发出去。"
                 "你的回复只说「上面是做完你会拿到的东西，还有几条先说清楚的，你看下，没问题我就发你付款链接」这类话，别复述条款，"
                 "也别说「注意事项」「发卡站」这类词。",
                 "发交付和注意事项" + (f"：{head[:40]}" if head else ""))


def send_payment(ctx: RunContext[BotDeps]) -> str:
    """把购买方式（付款渠道）发过去：付完拿到激活码，发回来就能认领。认领后的单买加购（再改一轮、加急、帮我找文献）也用这个。"""
    d = ctx.deps
    if not d.serving and not d.terms_sent_before:
        return d.log("send_payment", {}, "还没把交付和注意事项发给客户（或者这一趟才发），先让客户看完说可以，再发购买方式。",
                     "发付款方式：交付和注意事项还没发过，没发")
    if d.payment_recent and d.payment_ready:
        return d.log("send_payment", {}, "购买方式上面刚发过（不重发），告诉客户就在上面那条，付完把激活码发过来。", "发付款方式：刚发过，没重发")
    if not d.payment_ready:
        d.owner.append(("其他", "客户要付款拿激活码，但付款渠道还没设置"))
        attach = _attach_owner_qr(d)
        tail = "二维码会跟这条一起发" if attach else ("二维码 24 小时内发过了，让客户加上面那个" if d.owner_qr_recent else "负责人微信二维码还没放上来，只说可以联系负责人")
        return d.log("send_payment", {},
                     f"付款渠道还没设置好，已经改成发负责人微信（{tail}）。回复里说「购买方式这边还没弄好，可以加负责人的微信」。",
                     "发付款方式：渠道还没设置，改发负责人微信")
    d.payment = True
    return d.log("send_payment", {}, "购买方式（设置里的原文）会跟在你这条回复后面发。回复里说付完拿到激活码发给我就行，别复述。",
                 "发付款方式")


def _attach_owner_qr(d: BotDeps) -> bool:
    if d.owner_qr:
        return True
    if d.owner_qr_ready and not d.owner_qr_recent:
        d.owner_qr = True
        return True
    return False


def send_owner_wechat(ctx: RunContext[BotDeps], reason: str, detail: str) -> str:
    """解决不了的事：发负责人的微信二维码（跟这条回复一起发），让客户加他。退款、投诉、要打折、范围外的活（数据分析、建模、
    写论文、问卷调查或访谈这类原始资料的汇报）、客户坚持要找真人、激活码说不清、货号装不下（时长 / 篇数 / 页数超了）、
    来不及但客户坚持要做、你判断不了的。

    Args:
        reason: 退款、投诉、价格、范围外、要真人、激活码、来不及、档位、其他 之一。
        detail: 一句话说清客户要什么（给负责人看）。
    """
    d = ctx.deps
    if reason not in OWNER_REASONS:
        raise ModelRetry(f"reason 只能是：{'、'.join(OWNER_REASONS)}")
    d.owner.append((reason, detail.strip()[:300]))
    attach = _attach_owner_qr(d)
    if attach:
        how = "二维码图片会跟在你这条回复后面发。"
    elif d.owner_qr_recent:
        how = "二维码 24 小时内已经发过了，这次不重复发图，让客户加上面那个二维码。"
    else:
        how = "负责人微信二维码还没放上来，只说会请负责人联系。"
    line = ""
    if d.kb is not None and d.kb.owner.line:
        line = f"回复里把负责人微信给他：{d.kb.owner.line}。"
        if d.kb.owner.mute_after_handoff:
            line += "这条之后你先不回这位客人，负责人接手。"
    return d.log("send_owner_wechat", {"reason": reason, "detail": detail},
                 f"已记下给负责人。{how}{line}回复里说「这个负责人直接跟你对更快」这类话，别自己答应这件事。",
                 f"发负责人微信：{reason}（{detail.strip()[:60]}）")


# ---------------------------------------------------------------- 工具：制作中、交付后（serve）

def ask_maker(ctx: RunContext[BotDeps], kind: str, text: str) -> str:
    """把客户的补充要求、问题，或者对制作方问题的回答，写给做 PPT 的同事（制作方）。
    写完回客户「我去问一下做 PPT 的同事，有结果马上告诉你」这类话（回答类的说「已经转给同事了」）。

    Args:
        kind: 补充要求、问题、回答 之一。客户回答制作方的问题用「回答」。
        text: 写给制作方的话：把客户的意思说完整，客户的原话照抄放进去。
    """
    d = ctx.deps
    if (no := d.need_order("ask_maker")) is not None:
        return no
    if kind not in ASK_KINDS:
        raise ModelRetry(f"kind 只能是：{'、'.join(ASK_KINDS)}")
    if d.voided:
        return d.log("ask_maker", {"kind": kind}, "这单作废了，不用写给制作方。", "问制作方：这单作废了")
    if not (d.started or d.delivered or d.after_delivery):
        return d.log("ask_maker", {"kind": kind}, "还没开工，补充要求用 record_info 记进要求原话就行，开工时会一起交过去。",
                     "问制作方：还没开工，没写")
    if not text.strip():
        raise ModelRetry("text 不能空")
    d.to_maker.append((kind, text.strip()[:4000]))
    return d.log("ask_maker", {"kind": kind, "text": text[:80]}, "已经写给制作方了。制作方回了会再告诉你。",
                 f"写给制作方（{kind}）：{text.strip()[:60]}")


def submit_revision(ctx: RunContext[BotDeps], items: list[RevisionPoint]) -> str:
    """客户要改：问清楚第几页、改成什么，一次收齐，整理成改稿单交给制作方（改好的那版做好了会自动发给客户）。

    Args:
        items: 逐页的修改，每条写第几页（水印版底栏的「第 N 页」，整体意见空着）和改成什么，客户的原话照抄。
    """
    d = ctx.deps
    if (no := d.need_order("submit_revision")) is not None:
        return no
    if not (d.delivered or d.after_delivery):
        return d.log("submit_revision", {}, "还没交水印版，不是改稿：在做的单补充要求用 ask_maker。", "交改稿单：还没交付")
    if d.revisions_left <= 0:
        return d.log("submit_revision", {}, "修改轮数用完了：再改要买「再改一轮」的码（客户发码系统会认领），或者 send_owner_wechat（reason=其他）。",
                     "交改稿单：轮数用完了")
    pts = [p.model_dump() for p in items if p.text.strip()]
    if not pts or sum(len(p["text"].strip()) for p in pts) < 6:
        raise ModelRetry("改稿单太短：写清楚第几页、改成什么")
    d.revision_items = pts
    d.revisions_left -= 1
    return d.log("submit_revision", {"items": len(pts)}, "改稿单交给制作方了，改好会自动发给客户。回复里告诉客户改好了还在同一个页面看。",
                 "交改稿单：" + "；".join(f"{'第' + str(p['page']) + '页' if p['page'] else '整体'} {p['text'][:20]}" for p in pts)[:80])


def cancel_order(ctx: RunContext[BotDeps], reason: str) -> str:
    """客户明确说不做了、要撤单时用。开工前撤：激活码退回去还能再用；开工后不退。

    Args:
        reason: 客户为什么不做了（一句话）。
    """
    d = ctx.deps
    if (no := d.need_order("cancel_order")) is not None:
        return no
    if d.voided:
        return d.log("cancel_order", {"reason": reason}, "这单已经作废了。", "撤单：已经作废过")
    if d.started or d.delivered or d.after_delivery:
        return d.log("cancel_order", {"reason": reason},
                     "已经开工了，按注意事项开工后不退。客户坚持要退 → send_owner_wechat（reason=退款）。",
                     "撤单：已经开工，不退")
    d.cancel_why = reason.strip()[:200] or "客户不做了"
    return d.log("cancel_order", {"reason": reason}, "这单撤了，激活码会退回去，还能再用。回复里跟客户确认一下撤好了。",
                 f"撤单：{d.cancel_why[:60]}")


def send_sample(ctx: RunContext[BotDeps], which: int = 1) -> str:
    """发一份样张（讲公开论文的免费稿，带水印的 PDF，跟这条回复一起发）。客人想看做出来什么样时用；挑跟他场合最近的那份，
    他还想看再发别的。不拿别的客人的稿子给人看。

    Args:
        which: 第几份（1–3，看情况里【样张】那几行）。
    """
    d = ctx.deps
    kb = d.kb
    ready = [i for i, s in enumerate(kb.samples if kb else []) if s.ready]
    tail = f"顺带说一句：{kb.gzh_line}" if kb is not None and kb.gzh_line else ""
    if not ready:
        return d.log("send_sample", {"which": which}, f"样张还没放上来，这次发不了。{tail}", "发样张：还没放上来")
    idx = which - 1
    if idx not in ready:
        idx = ready[0]
    if idx in d.samples_recent or idx in d.samples_out:
        others = [i for i in ready if i not in d.samples_recent and i not in d.samples_out]
        if not others:
            return d.log("send_sample", {"which": which}, f"样张 24 小时内都发过了，让他看上面那几份。{tail}", "发样张：都发过了")
        idx = others[0]
    d.samples_out.append(idx)
    s = kb.samples[idx]
    return d.log("send_sample", {"which": idx + 1},
                 f"样张《{s.title}》（{s.about}）会跟在你这条回复后面发（PDF，带水印）。回复里说一句「发你一份我们做的……，带水印的」。{tail}",
                 f"发样张：{s.title}")


def send_materials(ctx: RunContext[BotDeps], occasion: str = "") -> str:
    """把这个场合要准备的资料原样发给客户（设置里的资料清单：必须发的、有的话更好的，每样后面半句说用来干什么；跟这条回复一起发，
    你不用列）。客户问「要准备什么 / 要发什么 / 需要什么资料」时用；还没买的客户想买之前也可以发，让他买之前就知道要发什么。
    不知道场合就先别调，问一句是什么场合。

    Args:
        occasion: 场合，只能是情况里列的几种之一（组会文献、课程文献、开题、中期、答辩、会议、其他）；认领后的单不填就用记下的场合。
    """
    d = ctx.deps
    occ = (occasion or "").strip() or (d.facts.occasion if d.serving else "")
    names = "、".join(f"{materials.name_of(d.cfg, k)}（{k}）" for k in materials.shown_occasions(d.cfg))
    if not occ:
        return d.log("send_materials", {}, f"还不知道是什么场合：先问客户一句是哪种（{names}），问到了再调。",
                     "发资料清单：场合还不知道，先问")
    if occ not in d.cfg.occasions:
        raise ModelRetry(f"场合只能是：{'、'.join(d.cfg.occasions)}")
    if d.serving and occ != d.facts.occasion:
        return d.log("send_materials", {"occasion": occ}, f"这单记的场合是「{d.facts.occasion or '还不知道'}」：客户说的是{occ}的话先 record_info 记下场合（会自动发这个场合的清单）。",
                     "发资料清单：场合跟这单记的不一样，没发")
    if d.serving and occ in d.materials_listed:  # 每单每个场合只整张发一次：再问就点名说还缺的
        missing = "、".join(d.still_missing()) or "必须发的都齐了"
        return d.log("send_materials", {"occasion": occ}, f"这个场合的清单已经整张发过了（在上面），不重发。还缺：{missing}；点名说这一两样就行。",
                     "发资料清单：发过了，没重发")
    d.materials_out = occ
    who = "付款认领后发过来" if not d.serving else "直接发在这里"
    return d.log("send_materials", {"occasion": occ},
                 f"{materials.name_of(d.cfg, occ)}要的资料清单（设置里的原文）会跟在你这条回复后面原样发出去。回复只说一句"
                 f"「{materials.name_of(d.cfg, occ)}要准备这几样，我列给你」这类话，告诉他{who}，别复述清单。",
                 f"发资料清单：{occ}")


TOOLS = [record_info, register_file, default_duration, check_progress, quote_price, send_terms, send_payment,
         send_owner_wechat, ask_maker, submit_revision, cancel_order, send_sample, send_materials]


def build_agent(model: Any, mode: str = "serve") -> Agent[BotDeps, str]:
    if mode == "serve":
        tools = [t for t in TOOLS if t.__name__ != "send_terms"]
    else:  # 访客问答只许这四个（模块 D 设计第三节第 8 条）
        tools = [t for t in TOOLS if t.__name__ in VISITOR_TOOLS]
    agent = Agent(
        model,
        deps_type=BotDeps,
        output_type=str,
        instructions=load_rules(),
        tools=[Tool(t, takes_ctx=True, docstring_format="google") for t in tools],
        retries=2,
    )

    @agent.output_validator
    def _speak_like_a_person(ctx: RunContext[BotDeps], output: str) -> str:
        """去 AI 味、合规（reception/style.py）：查到禁用说法就让模型重写，最后一次还不行由代码删掉那几处。"""
        kb = ctx.deps.kb
        if kb is None or not output:
            return output
        route = ctx.deps.route
        intents = route.intents if route is not None else None
        called = {l.name for l in ctx.deps.logs}
        found = rstyle.problems(_clean_reply(output), kb, intents, ctx.deps.recent_bot_texts,
                                time_checked=bool(called & {"quote_price", "check_progress"}),
                                no_price=route is not None and route.note.startswith("超出档位"))
        if not found:
            return output
        ctx.deps.style_fixes.append("、".join(p.what for p in found[:4]))
        if ctx.retry >= ctx.max_retries:
            return rstyle.scrub(output, kb)
        raise ModelRetry(rstyle.retry_message(found))

    return agent


# ---------------------------------------------------------------- 「现在的情况」

CHANNEL_NAMES = {"web": "网页聊天", "wecom": "微信客服"}


def _msg_text(m: Message, files: dict[int, FileRecord]) -> str:
    f = files.get(m.file_id) if m.file_id else None
    if m.asset == "terms":
        return "[交付什么 + 注意事项，原文已发]"
    if m.asset == "payment":
        return "[购买方式，原文已发]"
    if m.asset == "materials":
        return "[资料清单（要发哪几样），原文已发]"
    if m.asset == "owner_qr":
        return "[负责人微信二维码]"
    if m.asset == "pay_qr":
        return "[付款二维码]"
    if m.kind == "text":
        return m.text
    if m.kind in ("file", "image"):
        label = "文件" if m.kind == "file" else "图片"
        return f"[{label} #{f.id} {f.filename}]" if f else f"[{label}]"
    if m.kind == "voice":
        return "[语音，听不了]"
    return m.text or f"[{m.kind}]"


def _who(m: Message) -> str:
    if m.direction == "in":
        return "客户"
    return {"bot": "你", "system": "系统", "edison": "负责人"}.get(m.sender, "你")


def _short_time(dt: datetime) -> str:
    t = clock.local_now(dt)
    return f"{t.month:02d}-{t.day:02d} {t.hour:02d}:{t.minute:02d}"


def build_situation(
    *,
    customer: Customer,
    order: Order | None,
    deps: BotDeps,
    recent: list[Message],
    pending: list[Outbox],
    new_msgs: list[Message],
    files: dict[int, FileRecord],
    maker_msgs: list[ProductionMessage],
    past_orders: list[Order] | None = None,
    lock_until: datetime | None = None,
) -> str:
    cfg, facts, today = deps.cfg, deps.facts, deps.today
    L: list[str] = []
    L.append(f"【今天】{today.isoformat()} {clock.weekday_cn(today)}（北京时间）")
    src = f"，从「{customer.source}」来" if customer.source else ""
    name = customer.nickname or "还不知道称呼"
    L.append(f"【客户】{name}（{CHANNEL_NAMES.get(customer.channel, customer.channel)}{src}）")
    if deps.memory_brief:
        L.append(f"【老客户记得的】{deps.memory_brief}（照这些少问已知的；模板要问一句还用不用上次那个，不自动套；记忆不代替付款）")
    if past_orders:
        L.append("【上次的单子】" + "；".join(
            f"{pricing.sku_name(cfg, o.sku) if o.sku else '货号没记'}，{o.occasion or '场合没记'}，{STAGE_LABELS.get(o.stage, o.stage)}"
            for o in past_orders[:3]))
    for n in deps.claim_notes:
        L.append(f"【激活码】{n}")
    if lock_until:
        L.append(f"【激活码】这个会话错太多次，锁到 {clock.local_now(lock_until):%H:%M}（北京时间）")

    if not deps.serving:
        L.append("【这个会话还没有订单】还没认领激活码：只问答（问价、说交付什么、发购买方式）；不收资料、不记制作信息，"
                 "客户发文件系统已经回了「先发激活码」。")
        L.append("【价目】（设置里的，报价用 quote_price 算，不自己加减）" + "；".join(pricing.price_table(cfg)))
        L.append("【收钱】交付和注意事项：" + ("这个会话发过了" if deps.terms_sent_before else "还没发")
                 + "｜付款渠道：" + ("设置好了" if deps.payment_ready else "还没设置（send_payment 会自动改发负责人微信）")
                 + "｜负责人微信二维码：" + ("24 小时内发过" if deps.owner_qr_recent else ("没发过" if deps.owner_qr_ready else "还没放上来")))
    else:
        L.append(f"【这单】#{order.id} 状态：{STAGE_LABELS.get(order.stage, order.stage)}｜货号：{deps.sku_name}"
                 + (f"，页数上限 {deps.max_pages} 页（{cfg.page_rule_text}）" if deps.max_pages else ""))
        if deps.other_orders:
            L.append("【这个人还有别的单在走】" + "；".join(deps.other_orders) + "（客户说的要是那一单，提醒他现在聊的是哪一单）")
        L.append(f"场合：{facts.occasion or '还不知道'}（可选：{'、'.join(cfg.occasions)}）")
        if facts.title:
            L.append(f"题目：{facts.title}")
        if facts.duration_min is None:
            L.append("时长：还不知道（客户说不设时间时，先调 default_duration 拿这个场合的默认时长再问）")
        elif facts.duration_default and not facts.duration_confirmed:
            L.append(f"时长：按默认 {facts.duration_min} 分钟问过了，客户还没点头")
        else:
            L.append(f"时长：{facts.duration_min} 分钟" + ("（默认值，客户同意了）" if facts.duration_default else ""))
        papers, guessed = effective_papers(facts)
        L.append(f"篇数：{papers or '还不知道'}{'（按登记成论文的文件数推的）' if papers and guessed else ''}｜要求页数：{facts.page_count or '没提'}")
        if facts.present_date:
            said = f"，客户原话「{facts.present_date_text}」" if facts.present_date_text else ""
            L.append(f"汇报日期：{facts.present_date.isoformat()} {clock.weekday_cn(facts.present_date)}{said}")
        else:
            L.append("汇报日期：还不知道")
        L.append(f"学校：{facts.school or '没说'}｜语言：{facts.language or '没说'}｜页数/结构：{facts.structure_req or '没提'}")
        if facts.requirement_quotes:
            L.append("已记下的要求原话：" + " / ".join(q.replace("\n", " ")[:60] + ("…" if len(q) > 60 else "") for q in facts.requirement_quotes))
        if facts.addons:
            L.append("已付的加购：" + "、".join(pricing.addon_names(cfg, sorted(facts.addons))))
        rule = cfg.rule(facts.occasion)
        if rule is not None:
            missing = missing_materials(facts, cfg) or []
            names = materials.missing_names(cfg, facts.occasion, missing, find_refs=facts.find_refs)
            must = "、".join(f"{m.text}（登记成{m.purpose}）" for m in materials.must_lines(cfg, facts.occasion, find_refs=facts.find_refs))
            L.append(f"【材料】这个场合必须发的：{must or '没有固定清单'}；还缺：{'、'.join(missing) if missing else '无'}"
                     + (f"（跟客人说：{'、'.join(names)}）" if missing else "")
                     + ("（买了帮我找文献，论文我们找）" if facts.find_refs else ""))
            if rule.nice:
                L.append("有的话更好（客人发了就收、登记）：" + "、".join(m.text for m in rule.nice))
            if rule.optional_hint:
                L.append(f"登记说明：{rule.optional_hint}")
            sent = facts.occasion in deps.materials_listed
            L.append(f"【资料清单】这个场合要的资料{'已经原样整张发给客户了，别再列，缺什么点名要' if sent else '还没整张发过；客户问要发什么就 send_materials'}")
        if deps.collect_ask:
            L.append(f"【清单】{deps.collect_ask}")
        if deps.brief_line:
            L.append(deps.brief_line)
        if facts.files:
            L.append("文件：" + "；".join(f"#{x.id} {x.filename}（{x.purpose or '用途还没登记'}）" for x in facts.files))
        if deps.delivered or deps.after_delivery:
            L.append(f"【交付】交过 {order.delivery_round} 版水印版；还能改 {deps.revisions_left} 轮")
        open_needs = [n for n in (order.needs_edison or []) if not n.get("resolved")]
        if open_needs:
            L.append("【已经发过负责人微信的事】" + "；".join(f"{n['type']}：{n['detail'][:40]}" for n in open_needs) + "（负责人会跟客户聊，别自己答应）")
        if maker_msgs:
            L.append("【制作方会话】（你和做 PPT 的同事之间，客户看不到；旧→新，最近几条）")
            for m in maker_msgs[-6:]:
                who = "你→制作方" if m.direction == "to_maker" else "制作方→你"
                L.append(f"{who}（{m.kind}）{_short_time(m.created_at)}：{m.text.replace(chr(10), ' ')[:120]}")
    if cfg.faq:
        from app.intake.faq_cards import cards_for  # 问答卡：只取给助手的（channels 含 bot），占位符按设置现填

        L.append("【常见问题怎么答】" + "；".join(f"{q} → {a}" + (f"（{h}）" if h else "") for q, a, h in cards_for(cfg, "bot")))

    L.append(f"【最近的对话】（旧→新，最多 {RECENT_LIMIT} 条）")
    if not recent and not pending:
        L.append("（还没有）")
    for m in recent:
        L.append(f"{_who(m)} {_short_time(m.created_at)}：{_msg_text(m, files)}")
    for ob in pending:
        if ob.kind == "text":
            L.append(f"（你写的、等后台看过才发、客户还没看到）你：{ob.text}")

    if deps.maker_new:
        L.append("【制作方新消息，要转告客户】" + "；".join(f"（{k}）{t}" for _, k, t in deps.maker_new))
        L.append("把意思用你的话转告客户；制作方问的问题要客户回答的，问客户（客户答了再用 ask_maker 的「回答」写回去）。")
    if new_msgs:
        L.append("【这次客户新说的】")
        for m in new_msgs:
            L.append(f"客户：{_msg_text(m, files)}")
    L.append("【下一步】" + deps.next_steps())
    L.append("先用工具记下新信息、做该做的事，再写给客户的一条回复。")
    return "\n".join(L)


# ---------------------------------------------------------------- 跑一趟

def _clean_reply(text: str) -> str:
    t = (text or "").replace("**", "").strip()
    t = re.sub(r"^\s*[-*•]\s+", "", t, flags=re.M)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def pick_category(deps: BotDeps, reply: str) -> str:
    names = {l.name for l in deps.logs}
    if deps.owner:
        return "负责人微信"
    if deps.claim_notes:
        return "核销"
    if deps.terms_head is not None:
        return "交付和注意事项"
    if deps.payment:
        return "付款方式"
    if deps.revision_items:
        return "改稿"
    if deps.to_maker or deps.maker_new:
        return "转告制作方"
    if "quote_price" in names:
        return "报价"
    if "register_file" in names:
        return "收到文件"
    if "check_progress" in names:
        return "进度查询"
    missing = missing_materials(deps.facts, deps.cfg) if deps.facts.occasion else None
    if missing and any(p in reply for p in missing):
        return "问缺的材料"
    return "一般回复"


@dataclass
class Snapshot:
    customer_id: int
    order_id: int
    max_msg_id: int
    situation: str
    deps: BotDeps
    # 接待机器人判断、引导要用的（reception/）
    new_texts: list[str] = field(default_factory=list)
    new_kinds: list[str] = field(default_factory=list)
    recent_pairs: list[tuple[str, str]] = field(default_factory=list)
    bot_texts: list[str] = field(default_factory=list)
    customer_texts: list[str] = field(default_factory=list)
    channel: str = "web"


def visitor_over_limit(db: Session, cfg: BizConfig, customer: Customer, today: date) -> bool:
    """没认领的会话：今天这个会话 / 全站助手回过的访客消息是不是超了（只算没挂单的客户消息）。"""
    start = datetime.combine(today, time(0), tzinfo=clock.TZ)
    mine = db.scalar(select(func.count()).select_from(Message).where(
        Message.customer_id == customer.id, Message.direction == "in", Message.order_id.is_(None), Message.created_at >= start)) or 0
    if cfg.visitor_daily_limit and mine > cfg.visitor_daily_limit:
        return True
    if cfg.visitor_global_daily_limit:
        everyone = db.scalar(select(func.count()).select_from(Message).where(
            Message.direction == "in", Message.order_id.is_(None), Message.created_at >= start)) or 0
        return everyone > cfg.visitor_global_daily_limit
    return False


def take_snapshot(db: Session, ctx: Ctx, customer: Customer, database: Database | None = None,
                  claim_notes: list[str] | None = None) -> Snapshot | None:
    """有新的客户消息、或者有没转告的制作方消息，才跑一趟。微信客服窗口关着时，制作方的消息先压着。"""
    from app.intake.orders import active_orders, current_order

    new_msgs = list(db.scalars(
        select(Message).where(Message.customer_id == customer.id, Message.direction == "in",
                              Message.id > customer.bot_seen_msg_id).order_by(Message.id)
    ))
    maker_new = unrelayed_from_maker(db, customer)
    if maker_new and not new_msgs and not window_info(db, customer)["can_send"]:
        maker_new = []
    if not new_msgs and not maker_new:
        return None
    order = current_order(db, customer)
    if order is None and maker_new:
        order = db.get(Order, maker_new[-1].order_id)
    cfg = load_config(db)
    today = clock.today()
    serving = order is not None
    facts = order_facts(db, order) if order else OrderFacts()
    booked = booked_by_day(db, exclude_order_id=order.id if order else None)
    new_ids = {m.id for m in new_msgs}
    recent = list(db.scalars(
        select(Message).where(Message.customer_id == customer.id).order_by(Message.id.desc()).limit(RECENT_LIMIT + len(new_ids))
    ))
    recent = [m for m in reversed(recent) if m.id not in new_ids][-RECENT_LIMIT:]
    pending = list(db.scalars(select(Outbox).where(Outbox.customer_id == customer.id, Outbox.status == "pending").order_by(Outbox.id)))
    file_ids = {m.file_id for m in recent + new_msgs if m.file_id} | {f.id for f in facts.files}
    files = {f.id: f for f in db.scalars(select(FileRecord).where(FileRecord.id.in_(file_ids)))} if file_ids else {}
    past = list(db.scalars(select(Order).where(Order.customer_id == customer.id, Order.id != (order.id if order else 0))
                           .order_by(Order.id.desc()).limit(3)))
    maker_all = production_messages(db, order) if order else []
    latest_from_maker = next((m for m in reversed(maker_all) if m.direction == "to_sales"), None)
    lock = codes.locked_until(db, customer.id)
    collect = collect_for(db, order, ctx) if order and order.stage in ("claimed", "collecting") else None
    others = [o for o in active_orders(db, customer) if order is None or o.id != order.id]
    tier = cfg.tier(order.tier_key) if order else None
    deps = BotDeps(
        cfg=cfg, today=today, facts=facts, booked=booked, stage=order.stage if order else "",
        customer_name=display_name(customer), mode="serve" if serving else "visitor_qa", database=database, ctx=ctx,
        customer_id=customer.id, order_id=order.id if order else 0,
        customer_said="\n".join(m.text for m in recent + new_msgs if m.direction == "in" and m.kind == "text"),
        queued_eta=order.eta_date if order and order.queued_at else None, due_hours=order.due_hours if order else None,
        started=bool(order and order.started_at), delivered=bool(order and order.stage in ("watermarked", "revising")),
        after_delivery=bool(order and order.stage == "delivered"), voided=bool(order and order.stage == "void"),
        terms_sent_before=customer.terms_sent_at is not None,
        revisions_left=revisions_left(order, cfg) if order else 0,
        payment_ready=cfg.payment.ready(),
        payment_recent=any(m.asset == "payment" for m in recent),
        owner_qr_ready=asset_path(db, ctx, "owner_qr") is not None,
        owner_qr_recent=bool(customer.owner_qr_sent_at and utcnow() - customer.owner_qr_sent_at < OWNER_QR_COOLDOWN),
        maker_new=[(m.id, m.kind, m.text) for m in maker_new],
        maker_latest=f"（{latest_from_maker.kind}）{latest_from_maker.text[:120]}" if latest_from_maker else "",
        claim_notes=list(claim_notes or []),
        collect_ask=collect.ask_text if collect else "", collect_blocker=collect.blocker_detail if collect else "",
        other_orders=[f"#{o.id} {pricing.sku_name(cfg, o.sku) if o.sku else ''} {STAGE_LABELS.get(o.stage, o.stage)}" for o in others],
        memory_brief=customer.memory_brief or "",
        sku_name=pricing.sku_name(cfg, order.sku, [a.get('key', '') for a in (order.addons or [])]) if order and order.sku else "",
        max_pages=tier.max_pages if tier else None,
    )
    if order is not None and serving:
        from app.intake import brief

        deps.materials_listed = materials.listed_occasions(db, order.id)
        deps.brief_line = brief.bot_line(db, ctx, order)
        deps.brief_ok = not deps.brief_line or brief.confirmed(db, order)
    deps.platform = order.platform if order else ""
    deps.facts_round = order.delivery_round if order else 0
    deps.kb = rkb.load(db)
    deps.recent_bot_texts = [m.text for m in recent if m.direction == "out" and m.sender == "bot" and m.kind == "text"]
    for ob in _recent_outbox(db, customer.id, utcnow() - timedelta(hours=24)):
        for r in ob.reasons or []:
            if isinstance(r, str) and r.startswith("sample:"):
                deps.samples_recent.add(int(r.split(":", 1)[1]))
    if ctx.settings.RECEPTION_DISCLOSURE and customer.channel != "web":  # 网页聊天顶上一直挂着那句，不用再说
        since = utcnow() - timedelta(days=deps.kb.disclosure.window_days)
        deps.will_disclose = not rstyle.disclosed_recently([(o.text, o.reasons or []) for o in _recent_outbox(db, customer.id, since)])
    situation = build_situation(customer=customer, order=order, deps=deps, recent=recent, pending=pending,
                                new_msgs=new_msgs, files=files, maker_msgs=maker_all, past_orders=past, lock_until=lock)
    max_id = max((m.id for m in new_msgs), default=customer.bot_seen_msg_id)
    return Snapshot(
        customer.id, order.id if order else 0, max_id, situation, deps,
        new_texts=[_msg_text(m, files) for m in new_msgs], new_kinds=[m.kind for m in new_msgs],
        recent_pairs=[(_who(m), _msg_text(m, files)) for m in recent],
        bot_texts=[m.text for m in recent if m.direction == "out" and m.sender == "bot" and m.kind == "text"],
        customer_texts=[m.text for m in recent + new_msgs if m.direction == "in" and m.kind == "text"],
        channel=customer.channel,
    )


def apply_result(db: Session, ctx: Ctx, snap: Snapshot, reply: str, run: BotRun) -> list[Outbox]:
    deps = snap.deps
    customer = db.get(Customer, snap.customer_id)
    order = db.get(Order, snap.order_id) if snap.order_id else None
    if order is not None:
        for k, v in deps.changes.items():
            setattr(order, k, v)
        if deps.quotes:
            have = list(order.requirement_quotes or [])
            order.requirement_quotes = have + [q for q in deps.quotes if q not in have]
        for fid, (purpose, note) in deps.purposes.items():
            f = db.get(FileRecord, fid)
            if f is not None and f.order_id == order.id:
                f.purpose = purpose
                if note:
                    f.note = note
        if deps.changes or deps.quotes or deps.purposes:
            order.updated_at = utcnow()
    if deps.nickname and not customer.nickname:
        customer.nickname = deps.nickname
    mute = bool(deps.owner) and deps.kb is not None and deps.kb.owner.mute_after_handoff
    for reason, detail in deps.owner:
        if order is not None:
            add_need(order, reason, detail)
        tail = "。助手先不回这位客人了，你回完在后台点「交还机器人」" if mute else ""
        ctx.notifier.send(f"{display_name(customer)} 发了你的微信二维码：{reason}。{detail}{tail}", link=f"/admin/conversations/{customer.id}", level="urgent", kind="转人工", who=f"customer:{customer.id}")
    if mute and not customer.human_takeover:
        customer.human_takeover = True  # 转了以后机器人闭嘴（Edison 11-19），负责人点「交还机器人」才恢复
        record_event(db, "intake.handoff_muted", f"customer:{customer.id}",
                     {"reasons": [r for r, _ in deps.owner], "run": run.id, "by": "bot"})
    if deps.terms_head is not None:
        customer.terms_sent_at = utcnow()
    for l in deps.logs:
        record_event(db, "intake.tool_called", f"order:{order.id}" if order else f"customer:{customer.id}",
                     {"run": run.id, "tool": l.name, "args": _jsonable(l.args), "summary": l.summary})
    customer.bot_seen_msg_id = max(customer.bot_seen_msg_id, snap.max_msg_id)
    relayed = [mid for mid, _, _ in deps.maker_new]
    if relayed:
        for m in db.scalars(select(ProductionMessage).where(ProductionMessage.id.in_(relayed))):
            m.relayed_at = utcnow()
    if order is not None:
        for kind, text in deps.to_maker:
            add_production_message(db, order, "to_maker", kind, text, author="bot")
        if deps.cancel_why and order.started_at is None and order.stage != "void":
            cancel_order_db(db, ctx, order, by="bot", why=deps.cancel_why)
        if order.stage in ("claimed", "collecting") and (deps.changes or deps.purposes or deps.quotes):
            refresh_status(db, ctx, order, announce=False)  # 记了新事实：收资料那一步再判断能不能开工
        if deps.revision_items:
            submit_revision_db(db, ctx, order, items=deps.revision_items, files=[], source="bot")

    return _queue_replies(db, ctx, snap, customer, order, reply, run)


def _recent_outbox(db: Session, customer_id: int, since: datetime) -> list[Outbox]:
    return list(db.scalars(select(Outbox).where(Outbox.customer_id == customer_id, Outbox.status != "rejected",
                                                Outbox.created_at >= since).order_by(Outbox.id.desc()).limit(80)))


def _queue_replies(db: Session, ctx: Ctx, snap: Snapshot, customer: Customer, order: Order | None, reply: str,
                   run: BotRun) -> list[Outbox]:
    """把这一趟要发的排进待发：固定原文（交付说明在前；购买方式、二维码在后）+ 助手的话（拆成几条、开头表明身份、
    要查东西时先说一句「我看下哈」），按接待机器人的节奏排好每条的发送时间（reception/，设计第六到八节）。"""
    deps = snap.deps
    kb = deps.kb
    settings = ctx.settings
    route = deps.route
    reasons = [l.summary for l in deps.logs] or ["没调工具，只回了话"]
    if route is not None:
        reasons.insert(0, "判断：" + "、".join(route.intents) + f"（{rwire.HOW.get(route.how, route.how)}）")
    if deps.style_fixes:
        reasons.append("说话检查让模型重写过：" + "；".join(deps.style_fixes)[:120])
    now = utcnow()
    win = window_info(db, customer)
    after_items: list[tuple[str, str, str]] = []  # (kind, asset, category) 跟在助手的话后面
    if deps.payment:
        after_items.append(("text", "payment", "付款方式"))
        if asset_path(db, ctx, "pay_qr") is not None:
            after_items.append(("image", "pay_qr", "付款方式"))
    if deps.owner_qr:
        after_items.append(("image", "owner_qr", "负责人微信"))
    if deps.materials_out:  # 资料清单（设置里的原文）跟在助手的话后面
        after_items.insert(0, ("text", "materials", "资料清单"))
    for idx in deps.samples_out:
        after_items.append(("file", f"sample:{idx}", "样张"))
    fixed = len(after_items) + (1 if deps.terms_head is not None else 0)
    budget = None if not win["limited"] else max(1, (win["sends_left"] or 0) - fixed)

    texts: list[str] = []
    seg_reasons: list[list[str]] = []
    if reply and kb is not None:
        parts = rwire.split_reply(kb, reply, channel=customer.channel, budget=budget)
        reasons += rstyle.soft_notes(parts, kb)
        if deps.will_disclose:  # 表明身份那条也算在条数里（微信客服默认一共 2 条：表明身份 + 回复合成一条）
            cap = kb.style.segments_for(customer.channel) if budget is None else min(kb.style.segments_for(customer.channel), budget)
            if len(parts) >= cap:
                parts = rstyle.segments("\n\n".join(parts), max_segments=max(1, cap - 1))
            texts.append(kb.disclosure.text)
            seg_reasons.append(["disclosure", "会话开头表明是 AI 助手（《人工智能生成合成内容标识办法》第四条）"])
        texts += parts
        seg_reasons += [list(reasons) for _ in parts]
    elif reply:
        if len(reply) > 120:
            reasons.append(f"回复偏长（{len(reply)} 字）")
        texts, seg_reasons = [reply], [reasons]

    filler = ""
    rhythm_on = bool(settings.RECEPTION_RHYTHM and kb is not None)
    if rhythm_on and texts and route is not None and not any("disclosure" in r for r in seg_reasons):
        recent = _recent_outbox(db, customer.id, now - timedelta(hours=max(kb.rhythm.filler_every_hours, 0.01)))
        last_filler = next((o.created_at for o in recent if "filler" in (o.reasons or [])), None)
        if rwire.filler_due(kb, route, last_filler_at=last_filler, now=now,
                            sends_left=(win["sends_left"] - fixed - len(texts)) if win["limited"] else None):
            filler = random.Random(f"{customer.id}-{run.id}-f").choice(kb.style.fillers)

    times: list[datetime | None] = [None] * (len(texts) + (1 if filler else 0))
    if rhythm_on and (texts or after_items or deps.terms_head is not None):
        chars = sum(len(t) for t in snap.new_texts)
        planned = rwire.plan_times(kb, texts=texts or ["好的，稍等"], filler=filler, last_customer_at=customer.last_customer_msg_at,
                                   now=now, local_now=clock.local_now(), customer_chars=chars, seed=f"{customer.id}-{run.id}")
        times = planned if texts else [None]
        last_t = planned[-1]
    else:
        last_t = None

    out: list[Outbox] = []
    if deps.terms_head is not None:
        first_bot = times[0] if times and times[0] is not None else None
        t_terms = max(now + timedelta(seconds=1), first_bot - timedelta(seconds=3)) if first_bot else (last_t if not texts else None)
        out.append(create_outbox(db, ctx, customer, order, text=terms_message(deps.cfg, deps.terms_head), asset="terms",
                                 category="交付和注意事项", author="system", reasons=["设置里的原文，一字不改"], run_id=run.id,
                                 send_after=t_terms))
    category = pick_category(deps, reply)
    k = 0
    if filler:
        out.append(create_outbox(db, ctx, customer, order, text=filler, category="一般回复", author="bot",
                                 reasons=["filler", "要查一下才能答：先说一句，像真人"], run_id=run.id, send_after=times[0]))
        k = 1
    for i, text in enumerate(texts):
        out.append(create_outbox(db, ctx, customer, order, text=text, category=category, author="bot",
                                 reasons=seg_reasons[i], run_id=run.id, send_after=times[k + i] if k + i < len(times) else None))
    pastes = rwire.paste_times(kb, last_t, len(after_items), f"{customer.id}-{run.id}") if kb is not None else [None] * len(after_items)
    for (kind, asset, cat), t in zip(after_items, pastes, strict=True):
        if asset == "payment":
            out.append(create_outbox(db, ctx, customer, order, text=payment_message(deps.cfg), asset="payment",
                                     category=cat, author="system", reasons=["设置里的付款渠道原文"], run_id=run.id, send_after=t))
        elif asset == "materials":
            ob = _materials_outbox(db, ctx, snap, customer, order, run, t)
            if ob is not None:
                out.append(ob)
        elif asset.startswith("sample:"):
            s = kb.samples[int(asset.split(":", 1)[1])]
            rec = FileRecord(customer_id=customer.id, order_id=None, role="sample", filename=s.filename or f"{s.title}.pdf",
                             size=s.size, content_type="application/pdf", storage_key=s.storage_key, purpose="样张",
                             note=s.title[:256], created_at=utcnow())
            db.add(rec)
            db.flush()
            out.append(create_outbox(db, ctx, customer, order, text=s.title, kind="file", file_id=rec.id, category=cat,
                                     author="system", reasons=[asset, "样张（讲公开论文的免费稿，带水印）"], run_id=run.id,
                                     send_after=t))
        elif asset == "pay_qr":
            out.append(create_outbox(db, ctx, customer, order, text="付款二维码", kind="image", asset="pay_qr",
                                     category=cat, author="system", reasons=["付款二维码"], run_id=run.id, send_after=t))
        else:
            out.append(create_outbox(db, ctx, customer, order, text="负责人微信二维码", kind="image", asset="owner_qr",
                                     category=cat, author="system", reasons=["解决不了的事，发负责人微信"], run_id=run.id,
                                     send_after=t))
            customer.owner_qr_sent_at = utcnow()
    return out


def _materials_outbox(db: Session, ctx: Ctx, snap: Snapshot, customer: Customer, order: Order | None, run: BotRun,
                      send_after: datetime | None) -> Outbox | None:
    """资料清单原文：还没买的按「X 要准备这几样」发通用的；认领后的按这单发（收到的标「收到了」），记下这个场合发过了。"""
    deps = snap.deps
    occ = deps.materials_out
    if order is not None and deps.serving:
        if materials.listed(db, order.id, occ):
            return None
        text = materials_list_text(db, order, ctx, facts=deps.facts)
        materials.mark_listed(db, order.id, occ, via="bot")
    else:
        text = materials.occasion_text(deps.cfg, occ, head="visitor")
    if not text:
        return None
    return create_outbox(db, ctx, customer, order, text=text, asset="materials", category="资料清单", author="system",
                         reasons=["设置里的资料清单原文，一字不改", f"materials:{occ}"], run_id=run.id, send_after=send_after)


def withdraw_unsent(db: Session, customer_id: int, *, now: datetime | None = None) -> int:
    """客人又说话了：上一趟排了时间、还没发出去的助手的话撤掉（这一趟连新消息一起重新回），像真人看到新消息改口。
    固定原文（交付说明、购买方式、二维码）照发：那是已经做了的事。"""
    now = now or utcnow()
    rows = list(db.scalars(select(Outbox).where(Outbox.customer_id == customer_id, Outbox.status == "approved",
                                                Outbox.author == "bot", Outbox.send_after.is_not(None),
                                                Outbox.send_after > now)))
    for ob in rows:
        ob.status = "rejected"
        ob.error = "客人又发了消息，这条还没发出去，连新消息一起重新回"
        ob.decided_at = now
    if rows:
        record_event(db, "intake.reply_withdrawn", f"customer:{customer_id}", {"outbox": [o.id for o in rows], "by": "system"})
    return len(rows)


def _jsonable(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, BaseModel):
        return v.model_dump()
    return v


# ---------------------------------------------------------------- 调模型之前：认领激活码、访客上限

def describe_codes(database: Database, ctx: Ctx, customer_id: int) -> list[str]:
    """新消息里的激活码（收消息时已经由 order.claim 节点认领过）现在什么情况，写给模型看。不再认领，不多算撞库次数。"""
    from app.intake.models import CodeAttempt
    from app.intake.orders import lookup_code, session_ids

    with database.session() as db:
        customer = db.get(Customer, customer_id)
        msgs = list(db.scalars(select(Message).where(
            Message.customer_id == customer_id, Message.direction == "in", Message.kind == "text",
            Message.id > customer.bot_seen_msg_id).order_by(Message.id)))
        found: list[str] = []
        for m in msgs:
            for piece in re.split(r"[，,。;；\n]+", m.text):
                code = codes.normalize_code(piece)
                if code and code not in found:
                    found.append(code)
        mine = set(session_ids(db, customer))
        notes: list[str] = []
        for code in found[:3]:
            lk = lookup_code(db, code)
            if lk.state == "claimed" and lk.customer_id in mine:
                addon = lk.sku.startswith("addon-")
                # 入口模块（D）的 entry.notice 已经把认领结果 + 资料清单原样发过了：别再重复，只回客户这句里的其他内容
                told = any((ob.reasons or [])[:1] in ([f"dedupe:claim:{lk.order_id}"], [f"dedupe:addon:{code}"])
                           for ob in db.scalars(select(Outbox).where(Outbox.customer_id.in_(mine), Outbox.category == "核销")))
                if told:
                    notes.append(f"{code} 认领上了（{'加购' if addon else '订单'}：{lk.sku_name}），认领结果和资料清单系统已经发给客户了。"
                                 "不要再说一遍认领、不要再列清单，只回应客户这句里的其他内容；没有别的就不用回。")
                    continue
                notes.append(f"{code} 认领上了（{'加购' if addon else '订单'}：{lk.sku_name}）。"
                             + ("告诉客户加购好了。" if addon else "告诉客户认领好了，按清单要资料（一条里问完）。"))
                continue
            att = db.scalar(select(CodeAttempt).where(CodeAttempt.customer_id == customer_id, CodeAttempt.given.contains(code[4:]))
                            .order_by(CodeAttempt.id.desc()).limit(1))
            result = att.result if att else "not_found"
            until = codes.locked_until(db, customer_id)
            if until is not None and result in ("locked", *codes.COUNTED):
                t = clock.local_now(until)
                notes.append(f"{code} 没认领：错太多次，锁到 {t:%H:%M}。告诉客户那之后再试；坚持码没问题 → send_owner_wechat（reason=激活码）。")
                continue
            detail = {"claimed": "已经在别的微信或网页里认领过了", "addon": f"这是加购码（{lk.sku_name}），要先认领基础档的码",
                      "legacy": "11-18 改价之前的旧档位码，要负责人处理", "void": "订单退款或撤单，码作废了",
                      "expired": "过期了"}.get(lk.state, "")
            if result == "wrong" and lk.state == "unused_pool":
                detail = "这个人已有在走的单，这个码现在用不上"
            reason = codes.REASON_TEXT.get(result, result)
            left = codes.fails_left(db, customer_id) if result in codes.COUNTED else None
            advice = {"not_found": "让客户核对一下再发（PSY- 开头 9 位）", "legacy": "send_owner_wechat（reason=激活码）",
                      "wrong": "照说明告诉客户；说不清 → send_owner_wechat（reason=激活码）"}.get(
                result, "告诉客户原因；客户坚持码没问题 → send_owner_wechat（reason=激活码）")
            notes.append(f"{code} 没认领：{reason}{'：' + detail if detail else ''}"
                         f"{f'（再错 {left} 次会锁 1 小时）' if left is not None else ''}。{advice}。")
    return notes


MANUAL_ACK_HOURS = 6  # 助手关着时，同一个人多久内只回一次「负责人本人回复」那句


def manual_fallback(db: Session, ctx: Ctx, customer_id: int) -> int:
    """接单助手关着（第一阶段没配模型入口）：客人的话全部转给负责人在后台人工回。返回这次转了几条。

    - 不调模型、不记「助手失败」：不然每来一句就发一条「助手回 X 没成功」、工人还重试，运维也会把模型入口记成连不上。
    - 给客人回一句固定话（设置里的 manual_ack；同一个人 MANUAL_ACK_HOURS 小时内只回一次），说清楚是负责人本人回、资料可以先发。
    - 告诉负责人一声（这几句的开头），去后台「对话」里回；客人的话本来就在库里，后台对话页按最近有动静排在最前。
    """
    from app.intake.orders import current_order

    customer = db.get(Customer, customer_id)
    if customer is None or customer.human_takeover:
        return 0
    new = list(db.scalars(select(Message).where(Message.customer_id == customer.id, Message.direction == "in",
                                                Message.id > customer.bot_seen_msg_id).order_by(Message.id)))
    if not new:
        return 0
    customer.bot_seen_msg_id = max(customer.bot_seen_msg_id, new[-1].id)
    since = utcnow() - timedelta(hours=MANUAL_ACK_HOURS)
    told = db.scalar(select(func.count()).select_from(Outbox).where(
        Outbox.customer_id == customer.id, Outbox.category == "人工接待", Outbox.created_at >= since)) or 0
    text = load_config(db).text("manual_ack")
    if not told and text.strip():
        create_outbox(db, ctx, customer, current_order(db, customer), text=text, category="人工接待", author="system",
                      reasons=["接单助手没开（没配模型入口），客人的话转给负责人人工回"])
    record_event(db, "intake.manual_pending", f"customer:{customer.id}", {"messages": len(new), "acked": not told, "by": "system"})
    preview = "；".join((m.text[:30] if m.kind == "text" else f"[{m.kind}]") for m in new[-3:])
    ctx.notifier.send(f"{display_name(customer)} 发来 {len(new)} 条消息，等你在后台「对话」里回（接单助手没开）：{preview}",
                      link=f"/admin/conversations/{customer.id}", level="urgent", kind="客人消息", who=f"customer:{customer.id}")
    db.flush()
    return len(new)


class BotRunner:
    """拿着模型跑一趟。模型在测试里换成 PydanticAI 的 FunctionModel，真跑时按配置建。

    classifier：判断意图用的模型（接待机器人第四节）；None = 只用规则（测试里注入假模型时默认这样，不打乱剧本）。
    """

    def __init__(self, model: Any, *, request_limit: int = 8, classifier: Any = None) -> None:
        self.model = model
        self.request_limit = request_limit
        self.classifier = classifier

    async def judge(self, snap: Snapshot, ctx: Ctx) -> rintent.Route:
        """判断层 + 引导：判断这几句是哪类，算这一轮最多问哪一件，拼进「现在的情况」。"""
        deps = snap.deps
        kb = deps.kb
        use_model = self.classifier if getattr(ctx.settings, "RECEPTION_CLASSIFIER", True) else None
        stage = deps.stage or ("visitor" if not deps.serving else "")
        last_bot = snap.bot_texts[-1] if snap.bot_texts else ""
        cfg = deps.cfg
        limits = (max((t.max_minutes for t in cfg.duration_tiers), default=0), max((b.max_papers for b in cfg.paper_bands), default=0))
        route = await rintent.classify(kb, use_model, texts=snap.new_texts, kinds=snap.new_kinds,
                                       stage=STAGE_LABELS.get(stage, "还没买（访客）" if stage == "visitor" else stage),
                                       recent=snap.recent_pairs, last_bot=last_bot, limits=limits)
        deps.route = route
        keys = rguide.needed_keys(serving=deps.serving, stage=deps.stage, missing=deps.still_missing() if deps.serving else [],
                                  brief_ok=deps.brief_ok, customer_texts=snap.customer_texts, main_intent=route.main)
        plan = rguide.plan(kb, keys=keys, intents=route.intents, bot_texts=snap.bot_texts, last_bot=last_bot,
                           answering=route.answering)
        lines = rwire.situation_lines(kb, route, plan, channel=snap.channel)
        if route.note.startswith("超出档位"):
            lines.append(f"【超出档位】{route.note[5:]}：不报价、不硬接，直接 send_owner_wechat（reason=档位），请他加负责人微信")
        if "ask_sample" in route.intents:
            ready = [f"{i + 1}. 《{s.title}》（{s.about}）" for i, s in enumerate(kb.samples) if s.ready]
            lines.append("【样张】" + ("；".join(ready) + "（send_sample 发一份）" if ready else "还没放上来，先说公众号那句")
                         + (f"；{kb.gzh_line}" if kb.gzh_line else ""))
        if deps.will_disclose:
            lines.append(f"【开头】系统会先替你发一句表明身份的招呼（「{kb.disclosure.text[:16]}……」），你不用再打招呼，直接说事")
        snap.situation = rwire.insert_before_next(snap.situation, lines)
        return route

    async def run_for_customer(self, database: Database, ctx: Ctx, customer_id: int) -> BotRun | None:
        with database.session() as db:
            customer = db.get(Customer, customer_id)
            if customer is None or customer.human_takeover:
                return None
        if self.model is None:  # 接单助手关着（没配模型）：客人的话全部转后台人工，不算失败、不重试
            with database.session() as db:
                manual_fallback(db, ctx, customer_id)
            return None
        # 0) 激活码收消息时已经由代码认领（不经模型）：把结果写给模型看
        notes = describe_codes(database, ctx, customer_id)

        # 1) 快照（短事务）；没认领的会话超了每天上限：不调模型，回一句固定话（当天一次）
        with database.session() as db:
            customer = db.get(Customer, customer_id)
            snap = take_snapshot(db, ctx, customer, database, claim_notes=notes)
            if snap is None:
                return None
            cfg = snap.deps.cfg
            if not snap.deps.serving and not notes and visitor_over_limit(db, cfg, customer, snap.deps.today):
                start = datetime.combine(snap.deps.today, time(0), tzinfo=clock.TZ)
                sent = db.scalar(select(func.count()).select_from(Outbox).where(
                    Outbox.customer_id == customer.id, Outbox.category == "访客上限", Outbox.created_at >= start)) or 0
                if not sent:
                    create_outbox(db, ctx, customer, None, text=cfg.text("visitor_limited"), category="访客上限",
                                  author="system", reasons=["没认领的会话今天超过上限，不调模型"])
                    record_event(db, "intake.visitor_limited", f"customer:{customer.id}", {"by": "system"})
                customer.bot_seen_msg_id = max(customer.bot_seen_msg_id, snap.max_msg_id)
                return None
            if snap.new_texts:
                withdraw_unsent(db, customer_id)  # 客人又说话了：还没发出去的上一句撤掉，这一趟一起回

        # 2) 判断这几句是哪类、这一轮问哪一件（不占库；判断用一个小调用，模型挂了用规则）
        await self.judge(snap, ctx)
        with database.session() as db:
            run = BotRun(customer_id=customer_id, order_id=snap.order_id or None, model=model_label(self.model),
                         situation=snap.situation, started_at=utcnow())
            db.add(run)
            db.flush()
            run_id = run.id

        # 3) 问模型（不占库）
        reply, error, usage = "", "", None
        try:
            agent = build_agent(self.model, snap.deps.mode)
            result = await agent.run(snap.situation, deps=snap.deps,
                                     usage_limits=UsageLimits(request_limit=self.request_limit))
            reply = _clean_reply(result.output)
            usage = result.usage
        except Exception as e:  # 模型挂了、超时、乱调工具：记下来，工人过一会儿再试一次
            log.warning("机器人这一趟失败：%s", e)
            error = f"{type(e).__name__}: {e}"[:2000]

        # 4) 落库（短事务）
        with database.session() as db:
            run = db.get(BotRun, run_id)
            run.finished_at = utcnow()
            run.tool_calls = [_jsonable({"name": l.name, "args": l.args, "result": l.result, "summary": l.summary}) for l in snap.deps.logs]
            run.reply = reply
            run.error = error
            if usage is not None:
                run.requests = usage.requests
                run.input_tokens = usage.input_tokens or 0
                run.output_tokens = usage.output_tokens or 0
            customer = db.get(Customer, customer_id)
            if error:
                record_event(db, "intake.bot_failed", f"customer:{customer_id}", {"run": run_id, "error": error[:500]})
                ctx.notifier.send(f"助手回 {display_name(customer)} 没成功：{error[:80]}", link=f"/admin/conversations/{customer_id}", level="urgent", kind="助手回复失败", who=f"customer:{customer_id}")
            else:
                apply_result(db, ctx, snap, reply, run)
                route = snap.deps.route
                record_event(db, "intake.bot_run", f"customer:{customer_id}", {
                    "run": run_id, "tools": [l.name for l in snap.deps.logs], "reply": reply[:500],
                    "requests": run.requests, "input_tokens": run.input_tokens, "output_tokens": run.output_tokens,
                    "intents": route.intents if route else [], "intent_how": route.how if route else "",
                })
            db.flush()
            db.expunge(run)
        return run
