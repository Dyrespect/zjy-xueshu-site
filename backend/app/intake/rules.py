"""开工判断、排期：全是纯函数，只看事实，不经模型（架构第四节第 4 条；gate.ready 节点的实现）。

开工的条件（订单已经认领 = 已付款；11-18 起付款在认领之前）：
1. 材料齐：这个场合的必需材料都收到了（按附件的用途算）；买了「帮我找文献」的不用客户给论文。
2. 时长定了：客户说了几分钟；或者按场合给了默认值、客户点了头。
3. 档位对得上：时长没超这单货号的时长档、篇数没超篇数档、要求的页数没超页数上限（内容页）。
4. 截止时间可行：汇报日期定了，预计交付日 ≤ 汇报日 − buffer_days（留时间熟悉）。
5. 有名额：从今天往后 queue_horizon_days 天里，有一天开工的单还没满 daily_quota。加急不占名额。

时限按小时（定价方案的时限表）：排到的开工日开工，开工后 N 小时内交第一版（水印版）。今天开工从现在算；
以后某天开工从 work_start_hour 点算。加急：今天开工，用加急时限；帮我找文献加 find_refs_extra_hours。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from app.intake.config_store import BizConfig, DurationTier
from app.intake import pricing


def md(d: date) -> str:
    """11月16日（给 Edison 和模型看的日期都用这个写法）"""
    return f"{d.month}月{d.day}日"


@dataclass
class FileFact:
    id: int
    filename: str
    purpose: str = ""


@dataclass
class OrderFacts:
    stage: str = ""
    sku: str = ""
    tier_key: str = ""
    band_key: str = ""
    addons: set[str] = field(default_factory=set)  # 已付的加购 key
    rush_by_edison: bool = False  # 后台给的加急（不看名额、材料）
    occasion: str = ""
    title: str = ""
    duration_min: int | None = None
    duration_default: bool = False
    duration_confirmed: bool = False
    present_date: date | None = None
    present_date_text: str = ""
    paper_count: int | None = None
    page_count: int | None = None
    school: str = ""
    language: str = ""
    structure_req: str = ""
    requirement_quotes: list[str] = field(default_factory=list)
    claimed: bool = False
    rush: bool = False
    queued: bool = False
    start_date: date | None = None
    eta_date: date | None = None
    started: bool = False
    files: list[FileFact] = field(default_factory=list)

    @property
    def find_refs(self) -> bool:
        return "find_refs" in self.addons


@dataclass
class Condition:
    key: str
    name: str
    ok: bool
    detail: str


@dataclass
class Plan:
    start_date: date
    eta_date: date
    load: int  # 开工那天已经排了几单（不含这单）
    hours: int = 0


# ---------------- 材料 ----------------

def received_purposes(facts: OrderFacts) -> set[str]:
    return {f.purpose for f in facts.files if f.purpose}


def required_materials(facts: OrderFacts, cfg: BizConfig) -> list[str] | None:
    rule = cfg.rule(facts.occasion)
    if rule is None:
        return None
    req = list(rule.required)
    if facts.find_refs:
        req = [p for p in req if p != "论文"]  # 买了「帮我找文献」：论文我们找
    return req


def missing_materials(facts: OrderFacts, cfg: BizConfig) -> list[str] | None:
    """还缺的必需材料；场合还不知道时返回 None（不知道该要什么）。"""
    req = required_materials(facts, cfg)
    if req is None:
        return None
    have = received_purposes(facts)
    return [p for p in req if p not in have]


def materials_ok(facts: OrderFacts, cfg: BizConfig) -> bool:
    missing = missing_materials(facts, cfg)
    if missing is None:
        return False
    if facts.occasion == "其他":
        return bool(facts.files)  # 「其他」场合没有固定清单：至少收到了东西
    return not missing


def duration_ok(facts: OrderFacts) -> bool:
    return facts.duration_min is not None and (not facts.duration_default or facts.duration_confirmed)


def effective_papers(facts: OrderFacts) -> tuple[int | None, bool]:
    """篇数：客户说了用客户的；没说按登记成论文的文件数；都没有返回 None（报价按 1 篇并问一句）。第二个值：是不是推的。"""
    if facts.paper_count:
        return facts.paper_count, False
    n = sum(1 for f in facts.files if f.purpose == "论文")
    return (n, True) if n else (None, True)


def info_complete(facts: OrderFacts, cfg: BizConfig) -> bool:
    return materials_ok(facts, cfg) and duration_ok(facts) and facts.present_date is not None


def fit_problems(facts: OrderFacts, cfg: BizConfig) -> list[str]:
    """这单货号装不装得下客户说的时长、篇数、页数。"""
    t, b = cfg.tier(facts.tier_key), cfg.band(facts.band_key)
    if t is None or b is None:
        return [f"货号「{facts.sku or '没有'}」不是现在的时长档 × 篇数档"]
    out = []
    if facts.duration_min is not None and facts.duration_min > t.max_minutes:
        need = pricing.tier_for_minutes(cfg, facts.duration_min)
        out.append(f"买的是{t.name}档（{t.max_minutes} 分钟以内），这单讲 {facts.duration_min} 分钟"
                   + (f"，要{need.name}档" if need else "，超过最长一档"))
    papers, _ = effective_papers(facts)
    if papers and papers > b.max_papers:
        out.append(f"买的是{b.name}，这单要讲 {papers} 篇")
    if facts.page_count and facts.page_count > t.max_pages:
        out.append(f"{t.name}档最多 {t.max_pages} 页（{cfg.page_rule_text}），客户要 {facts.page_count} 页")
    return out


# ---------------- 时限、加急 ----------------

def due_hours(facts: OrderFacts, cfg: BizConfig, *, rush: bool) -> int:
    t: DurationTier | None = cfg.tier(facts.tier_key)
    if t is None:
        t = cfg.tiers_sorted()[0] if cfg.duration_tiers else None
    if t is None:
        return 24 + (cfg.find_refs_extra_hours if facts.find_refs else 0) + cfg.promise_buffer_hours
    return pricing.promised_hours(cfg, t, rush=rush, find_refs=facts.find_refs)  # 对客承诺（正常用时 + 余量）


def rush_decision(facts: OrderFacts, cfg: BizConfig, rush_today: int) -> tuple[bool, str]:
    """付了加急的单能不能按加急做：档位开了加急、材料齐、不是找文献、今天加急名额还有。后台给的加急不看这些。"""
    if facts.rush_by_edison:
        return True, ""
    if "rush" not in facts.addons:
        return False, ""
    ok, why = pricing.rush_allowed(cfg, cfg.tier(facts.tier_key), find_refs=facts.find_refs)
    if not ok:
        return False, why
    if not materials_ok(facts, cfg):
        return False, "材料还没齐（加急只对材料齐的单）"
    if rush_today >= cfg.rush_daily_quota:
        return False, "今天加急名额满了"
    return True, ""


# ---------------- 排期 ----------------

def _eta(start: date, today: date, now: datetime | None, hours: int, cfg: BizConfig) -> date:
    if start == today and now is not None:
        return (now + timedelta(hours=hours)).date()
    begin = datetime.combine(start, time(cfg.work_start_hour))
    return (begin + timedelta(hours=hours)).date()


def plan_slot(today: date, booked: dict[date, int], cfg: BizConfig, hours: int, *, rush: bool = False,
              now: datetime | None = None) -> Plan | None:
    """从今天起找第一天还有名额的开工日（加急：今天，不看名额）。找不到返回 None。

    booked：每天已经排了几单开工。now：北京时间的现在（算今天开工的交付时间）；不给就按 work_start_hour 算。
    """
    if rush:
        return Plan(today, _eta(today, today, now, hours, cfg), booked.get(today, 0), hours)
    for i in range(cfg.queue_horizon_days + 1):
        d = today + timedelta(days=i)
        n = booked.get(d, 0)
        if n < cfg.daily_quota:
            return Plan(d, _eta(d, today, now, hours, cfg), n, hours)
    return None


def latest_ok_eta(present: date, cfg: BizConfig) -> date:
    return present - timedelta(days=cfg.buffer_days)


def start_conditions(facts: OrderFacts, cfg: BizConfig, plan: Plan | None, today: date, *,
                     collect: object | None = None) -> list[Condition]:
    """collect：intake.collect 节点的结果（有就用它判断「资料齐」，清单只有一份来源；纯函数测试里可以不给）。"""
    out: list[Condition] = []

    # 1 材料
    missing = missing_materials(facts, cfg)
    if collect is not None:
        ok = bool(getattr(collect, "complete", False))
        detail = getattr(collect, "blocker_detail", "") or getattr(collect, "ask_text", "") or "清单上的都齐了"
        out.append(Condition("materials", "资料齐（按清单）", ok, detail + ("（论文我们找）" if ok and facts.find_refs else "")))
    elif missing is None:
        out.append(Condition("materials", "材料齐", False, "还不知道是什么场合，不知道该要哪些材料"))
    elif facts.occasion == "其他":
        ok = bool(facts.files)
        out.append(Condition("materials", "材料齐", ok, "其他场合：收到了材料，要你看一下够不够" if ok else "还没收到材料"))
    elif missing:
        out.append(Condition("materials", "材料齐", False, "还缺：" + "、".join(missing)))
    else:
        tail = "（论文我们找）" if facts.find_refs else ""
        out.append(Condition("materials", "材料齐", True, "必需的都收到了" + tail))

    # 2 时长
    if facts.duration_min is None:
        out.append(Condition("duration", "时长定了", False, "还不知道讲几分钟"))
    elif facts.duration_default and not facts.duration_confirmed:
        out.append(Condition("duration", "时长定了", False, f"按默认 {facts.duration_min} 分钟问了，客户还没点头"))
    else:
        tail = "（默认值，客户同意了）" if facts.duration_default else ""
        out.append(Condition("duration", "时长定了", True, f"{facts.duration_min} 分钟{tail}"))

    # 3 档位
    probs = fit_problems(facts, cfg)
    if probs:
        out.append(Condition("fit", "档位对得上", False, "；".join(probs)))
    else:
        t = cfg.tier(facts.tier_key)
        out.append(Condition("fit", "档位对得上", True, f"{pricing.sku_name(cfg, facts.sku)}，{t.max_pages} 页以内"))

    # 4 截止时间
    if facts.present_date is None:
        out.append(Condition("deadline", "截止时间可行", False, "还不知道哪天汇报"))
    elif facts.present_date < today:
        out.append(Condition("deadline", "截止时间可行", False, f"汇报日 {md(facts.present_date)} 已经过了"))
    else:
        eta = facts.eta_date if facts.queued and facts.eta_date else (plan.eta_date if plan else None)
        latest = latest_ok_eta(facts.present_date, cfg)
        tag = "加急，" if facts.rush else ""
        if eta is None:
            out.append(Condition("deadline", "截止时间可行", False, "名额排满了，算不出交付日"))
        elif eta <= latest:
            out.append(Condition("deadline", "截止时间可行", True, f"{tag}预计 {md(eta)} 交第一版，{md(facts.present_date)} 汇报"))
        else:
            out.append(Condition("deadline", "截止时间可行", False, f"{tag}最早 {md(eta)} 交，要在 {md(latest)} 前交才来得及"))

    # 5 名额
    if facts.rush:
        out.append(Condition("quota", "有名额", True, "加急，不占排队"))
    elif facts.queued and facts.start_date:
        out.append(Condition("quota", "有名额", True, f"排在 {md(facts.start_date)} 开工"))
    elif plan is None:
        out.append(Condition("quota", "有名额", False, f"往后 {cfg.queue_horizon_days} 天名额都满了"))
    else:
        out.append(Condition("quota", "有名额", True, f"最早 {md(plan.start_date)} 开工（那天已排 {plan.load}/{cfg.daily_quota}）"))
    return out


def can_start(conds: list[Condition]) -> bool:
    return all(c.ok for c in conds)
