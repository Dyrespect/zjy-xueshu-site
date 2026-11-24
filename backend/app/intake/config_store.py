"""业务参数：价目（时长档 × 篇数档 + 加购）、页数和时限、名额、各场合要的资料（资料清单）、交付什么和注意事项、付款渠道、
哪几类回复先给后台看、访客每天条数上限、欢迎语、问答卡。

这些是「配置和库里的数」，不写进提示词、不写进代码（AGENTS.md 硬规矩；scripts/check.py 拦价格数字）。
默认值在这里，后台「设置」页改了存 `intake_kv`（key = "config"），读的时候用库里的覆盖默认值。

价目出处：学术汇报/docs/方案/2026-11-18_定价/方案.md（Edison 11-18 定的现价、页数上限、时限）；
帮我找文献 +20 是 Edison 定的（生态顶层设计 派活共同说明 第二节）；页数按内容页算（同上）。
标「我的假设」的数是模块 A 定的，设置页可改。契约：docs/任务单/06_订单中枢契约.md 第二节第 6 条。
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.intake.faq_cards import DEFAULT_FAQ
from app.intake.models import KV, MATERIAL_PURPOSES
from app.intake.platform_texts import DEFAULT_TEMPLATES

CONFIG_KEY = "config"
SCHEMA = 3  # 2 = 场合 × 加急四档（11-15）；3 = 时长档 × 篇数档 + 加购（11-18）

# 回复的类别（后台「要不要先给你看」按类别一类一类开；默认都直接发）
REPLY_CATEGORIES = (
    "一般回复",
    "收到文件",
    "问缺的材料",
    "资料清单",
    "进度查询",
    "报价",
    "交付和注意事项",
    "付款方式",
    "核销",
    "负责人微信",
    "转告制作方",
    "改稿",
    "排期通知",
    "交付",
    "语音提示",
    "欢迎语",
    "访客上限",
    "样张",
)

DEFAULT_PAYMENT_TEXT = "点下面的链接付款，付完页面上会给你一个激活码，复制发我就行"
DEFAULT_DELIVER_TEXT = (
    "你会拿到：① 可编辑的 PPT，按你说的时长做；② 每页的讲稿（Word），照着能讲；③ 学校校徽和配色，或者套你发来的模板；"
    "④ 原文的图照用，原文没有、讲不清的我们按心理学好刊的画法画出来；⑤ 内容标出处，APA 格式；⑥ 含一轮修改。"
)
DEFAULT_NOTES_TEXT = (
    "1. 内容以开工时你发来的材料为准，开工后再加新的内容算新的一单；\n"
    "2. 页数按内容页算（不含封面、目录、过渡页、参考文献、致谢），上限看你买的档；\n"
    "3. 做好先给你看水印版，含一轮修改，意见请一次给齐；你确认收货后发可编辑的 PPT 和讲稿；\n"
    "4. 你的材料、数据和草稿不公开，也不会拿去当示例；\n"
    "5. 我们不代写论文、不编数据；问卷调查、访谈这类原始资料的汇报不接；\n"
    "6. 激活码认领后开工；开工前想撤单，码退回给你还能用；开工后不退；\n"
    "7. 上台前请自己过一遍，按老师的要求微调。"
)
DEFAULT_PAGE_RULE = "页数按内容页算，不含封面、目录、过渡页、参考文献、致谢"
DEFAULT_VISITOR_LIMIT_TEXT = "今天先聊到这儿啦。买好之后把激活码发我（PSY- 开头），或者打开订单里的兑换网址，我接着帮你。"

_MONEY = re.compile(r"^(\d{1,5}(\.\d{1,2})?)?$")


def _money_ok(v: str) -> str:
    v = (v or "").strip()
    if not _MONEY.fullmatch(v):
        raise ValueError(f"价格「{v}」要写成数字，如 29.9；不开放就留空")
    return v


class MaterialLine(BaseModel):
    """资料清单的一样（对客人说的字）：东西 + 半句用来干什么（Edison 11-19：「要跟他讲清楚，我们要拿到一些什么资料」）。

    - 各场合「必须发的」每样要写 purpose（登记成哪种用途）：代码按它核对齐没齐，场合的 required 由它算出来，不另写一份。
    - 「有的话更好的」purpose 可空：写了的话客人发了这类文件，清单上标「收到了」。
    - 每个场合都要说的几样（materials.common）写 key：对上资料清单（checklists）里的一项，必需不必需、说没说过看那一项。
    """

    text: str = Field(min_length=1, max_length=60)
    use: str = Field(default="", max_length=60)
    purpose: str = ""
    key: str = Field(default="", max_length=32)

    @field_validator("purpose")
    @classmethod
    def _purpose(cls, v: str) -> str:
        v = (v or "").strip()
        if v and v not in MATERIAL_PURPOSES:
            raise ValueError(f"不认识的材料用途：{v}（只能是 {'、'.join(MATERIAL_PURPOSES)}）")
        return v


class OccasionRule(BaseModel):
    """场合管：对客人怎么叫、要哪些资料（必须发的 / 有的话更好的）、客户说「不设时间」时的默认时长（11-18 起档位跟场合脱钩）。

    required（核对用途）由 must 算出来：必须发的每样登记成哪种用途，这些用途都收到了才算主材料齐（gate.ready 照旧挡）。
    """

    name: str = Field(default="", max_length=16)  # 对客叫法（组会读文献）；空就用场合名
    must: list[MaterialLine] = Field(default_factory=list)  # 必须发的
    nice: list[MaterialLine] = Field(default_factory=list)  # 有的话更好的
    required: list[str] = Field(default_factory=list)  # 核对用途（由 must 算，旧设置没有 must 时由它补出 must）
    optional_hint: str = ""  # 给模型看的登记说明（什么文件登记成什么），不对客
    default_minutes: int = 15

    @field_validator("required")
    @classmethod
    def _purposes(cls, v: list[str]) -> list[str]:
        bad = [p for p in v if p not in MATERIAL_PURPOSES]
        if bad:
            raise ValueError(f"不认识的材料用途：{bad}（只能是 {'、'.join(MATERIAL_PURPOSES)}）")
        return v

    @model_validator(mode="after")
    def _one_source(self) -> OccasionRule:
        if not self.must and self.required:  # 旧设置只有核对用途：补成「必须发的」，字先用用途名
            self.must = [MaterialLine(text=p, purpose=p) for p in self.required]
        blank = [m.text for m in self.must if not m.purpose]
        if blank:
            raise ValueError(f"必须发的「{'、'.join(blank)}」要选登记成哪种用途（代码按它核对齐没齐）")
        self.required = list(dict.fromkeys(m.purpose for m in self.must))
        return self

    def label(self, key: str) -> str:
        return self.name.strip() or key


class MaterialsGuide(BaseModel):
    """资料清单对客的几句（一个数据源）：官网价目页和下单页、小鱼售前（send_materials）、认领那句话（claim_ok 的 {materials}）、
    场合定了发的那条、追缺的，都从这里和各场合的 must / nice 拼（app/intake/materials.py），不各写一份。{name} = 场合的对客叫法。"""

    site_title: str = "下单前准备好这些"
    site_lead: str = ""
    order_head: str = "{name}要发这几样，直接发在这里，一次发齐最快："
    visitor_head: str = "{name}要准备这几样，付款认领后发我就行："
    overview_head: str = "资料直接发在这里，要发的主材料看场合："
    overview_tail: str = "告诉我是哪种场合，我把这个场合要的完整列给你。"
    must_title: str = "必须发的："
    nice_title: str = "有的话更好："
    common_title: str = "每个场合都要说一声"
    received_mark: str = "（收到了）"
    start_rule: str = "资料齐了才开工，时限从开工那会儿算，不是从付款算。"
    other_text: str = ""
    common: list[MaterialLine] = Field(default_factory=list)  # 每个场合都要说的（key 对上资料清单里的一项）
    find_refs_line: MaterialLine | None = None  # 买了「帮我找文献」：替掉登记成论文的那几样
    order: list[str] = Field(default_factory=list)  # 官网和总览按这个顺序列场合（不在里面的不列，比如「其他」）


class DurationTier(BaseModel):
    """一个时长档：汇报时长上限、页数上限（内容页）、每个篇数档的价、标准 / 加急时限、开不开加急。"""

    key: str = Field(min_length=1, max_length=16, pattern=r"^[a-z0-9_]+$")
    name: str = Field(min_length=1, max_length=16)
    max_minutes: int = Field(ge=1, le=600)
    max_pages: int = Field(ge=1, le=500)
    prices: dict[str, str] = Field(default_factory=dict)  # 篇数档 key → 价；空 = 不开放
    std_hours: int = Field(ge=1, le=240)
    rush_hours: int = Field(ge=1, le=240)
    rush: bool = False  # 开不开放加急
    later_price: str = ""  # 以后压到（1 篇）：专用号到位、月单量稳定 60 单以上再压。只是备注，不参与报价

    @field_validator("prices")
    @classmethod
    def _prices(cls, v: dict[str, str]) -> dict[str, str]:
        return {k: _money_ok(p) for k, p in v.items()}

    @field_validator("later_price")
    @classmethod
    def _later(cls, v: str) -> str:
        return _money_ok(v)


class PaperBand(BaseModel):
    key: str = Field(min_length=1, max_length=8, pattern=r"^p[0-9_]+$")
    name: str = Field(min_length=1, max_length=16)
    max_papers: int = Field(ge=1, le=50)


class Addon(BaseModel):
    """加购。key 固定三种（代码按 key 判断规则）；价格、名字、说明可改；价格空 = 不卖。"""

    key: Literal["rush", "revision", "find_refs"]
    name: str = Field(min_length=1, max_length=16)
    price: str = ""
    note: str = ""

    @field_validator("price")
    @classmethod
    def _price(cls, v: str) -> str:
        return _money_ok(v)


class ChecklistItem(BaseModel):
    """资料清单的一项（模块 D 定的格式，见 docs/任务单/07_入口_设计.md 附录 B）。"""

    key: str = Field(min_length=1, max_length=32)
    label: str = Field(min_length=1)
    kind: Literal["fact", "files"]
    required: bool = False
    purposes_from: str = ""  # "occasions.required"：主材料要哪种看场合
    purposes: list[str] = Field(default_factory=list)
    count_from: str = ""  # "band"：份数看篇数档
    within: str = ""  # "tier"：不超过时长档上限


class Checklist(BaseModel):
    items: list[ChecklistItem] = Field(default_factory=list)
    deliver: dict[str, Any] = Field(default_factory=dict)


class Checklists(BaseModel):
    """每个货号一张资料清单：默认一张，加购可以替换某几项，个别货号可以覆盖。intake.collect 节点照它算缺什么。"""

    default: Checklist = Field(default_factory=Checklist)
    addons: dict[str, dict[str, Any]] = Field(default_factory=dict)  # {"find_refs": {"replace": {"main_files": {...}}}}
    overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)  # {"xlong-p4_5": {"deliver": {...}}}

    def for_order(self, sku: str, addons: list[str] | set[str]) -> Checklist:
        items = [i.model_copy() for i in self.default.items]
        deliver = dict(self.default.deliver)
        for key in addons:
            rep = (self.addons.get(key) or {}).get("replace") or {}
            items = [ChecklistItem.model_validate(rep[i.key]) if i.key in rep else i for i in items]
        over = self.overrides.get(sku) or {}
        if "items" in over:
            items = [ChecklistItem.model_validate(x) for x in over["items"]]
        deliver.update(over.get("deliver") or {})
        return Checklist(items=items, deliver=deliver)


class DeliverySettings(BaseModel):
    """交付（模块 E 的设计第八节需求 8）：确认收货的规矩只有这一张表，模块 B 的计时器、E 的交付页都读这里。"""

    remind_before_hours: int = Field(default=24, ge=0)  # 自动确认前几小时提醒一次
    revision_hours: int = Field(default=3, ge=1)  # 改稿多久交下一版（待定）
    confirm_sources_by_platform: dict[str, list[str]] = Field(default_factory=dict)  # 每个渠道认哪几种确认来源
    texts: dict[str, str] = Field(default_factory=dict)  # 发布、提醒、放出最终版的几句话（按渠道分）
    # 水印浓淡（水印字不透明度）：Edison 看样张（0.16 / 0.20 / 0.22）定，先用 0.20（模块 E 设计 4.8 节）
    watermark_alpha: float = Field(default=0.20, ge=0.08, le=0.40)

    def sources(self, platform: str) -> list[str]:
        return self.confirm_sources_by_platform.get(platform or "legacy", ["edison"])


class Payment(BaseModel):
    """付款渠道：客户没有激活码时发这些（付完拿到激活码再发回来认领）。

    说明文字（text）跟链接 / 二维码一起发；只有说明、没有链接也没有二维码，客户没地方付，算「还没设置」。
    """

    text: str = DEFAULT_PAYMENT_TEXT
    link: str = ""  # 发卡站（卖码平台）链接
    qr_image: str = ""  # 付款二维码图片路径（服务器上的本机路径）

    def ready(self) -> bool:
        has_qr = bool(self.qr_image) and Path(self.qr_image).is_file()
        return bool(self.link.strip()) or has_qr


class FaqCard(BaseModel):
    """问答卡（模块 G 文案草稿 10_助手问答卡.md）：a 里价格、时限写占位符，放进助手的情况前现填（app/intake/faq_cards.py）。"""

    q: str
    a: str
    hint: str = ""  # 只给助手看：该调哪个工具、什么时候转负责人
    channels: list[str] = Field(default_factory=lambda: ["bot"])  # bot 助手 / site 网页介绍 / gzh 公众号 / platform 平台


class BizConfig(BaseModel):
    schema_version: int = SCHEMA
    occasions: dict[str, OccasionRule]
    daily_quota: int = 3  # 每天能开工几单
    buffer_days: int = 1  # 交付至少比汇报日早几天（留时间熟悉）。我的假设
    queue_horizon_days: int = 14  # 排期最远往后看几天，再往后算「名额满了」。我的假设
    duration_tiers: list[DurationTier] = Field(default_factory=list)
    paper_bands: list[PaperBand] = Field(default_factory=list)
    addons: list[Addon] = Field(default_factory=list)
    find_refs_extra_hours: int = Field(default=4, ge=0, le=240)
    # 对客承诺比正常用时多说几小时（Edison 11-19：「我们可以正常时间往后面多说两个小时」）。std_hours / rush_hours 是正常用时，
    # 对客人说的、排期算的、交付时限看门都用「正常用时 + 这几小时」（pricing.promised_hours）
    promise_buffer_hours: int = Field(default=2, ge=0, le=48)
    page_rule_text: str = DEFAULT_PAGE_RULE
    rush_daily_quota: int = Field(default=1, ge=0)  # 每天最多做几单加急（「限名额」）。我的假设
    work_start_hour: int = Field(default=9, ge=0, le=23)  # 排到以后某天开工的，从几点算时限。我的假设
    visitor_daily_limit: int = Field(default=20, ge=0)  # 没认领的会话每天助手最多回几条（待定）
    visitor_global_daily_limit: int = Field(default=500, ge=0)  # 全站没认领的会话每天助手一共最多回几条（待定，模块 D 的建议）
    refund_block_after: int = Field(default=2, ge=0)  # 同一平台买家退款作废满几次不再发码（0 = 不拦）
    revise_after_days: int = Field(default=7, ge=0)  # 已交付后几天内还能用剩下的修改（算「在走的单」）。我的建议
    auto_confirm_days: int = Field(default=3, ge=1)  # 自有渠道每交一版水印版，几天没回应视为确认（Edison 定 3 天；计时器归模块 B）
    delivery: DeliverySettings = Field(default_factory=lambda: DeliverySettings())
    checklists: Checklists = Field(default_factory=Checklists)
    materials: MaterialsGuide = Field(default_factory=MaterialsGuide)  # 资料清单对客的几句（各场合要什么在 occasions）
    entry_texts: dict[str, str] = Field(default_factory=dict)  # 入口的固定话术（模块 D 用；不写价格）
    delivery_templates: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_TEMPLATES))  # 平台发货内容的模板（过红线词表）
    deliver_text: str = DEFAULT_DELIVER_TEXT  # 交付什么（原样发给客户，不让模型改写）
    notes_text: str = DEFAULT_NOTES_TEXT  # 注意事项（原样发）
    payment: Payment = Field(default_factory=Payment)
    revisions_included: int = 1  # 含几轮修改
    approval: dict[str, bool] = Field(default_factory=dict)  # 哪几类回复先给后台看再发（默认都不批）
    welcome_text: str = ""
    faq: list[FaqCard] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistent(self) -> BizConfig:
        tkeys = [t.key for t in self.duration_tiers]
        if len(tkeys) != len(set(tkeys)):
            raise ValueError("时长档的代号不能重复")
        bkeys = [b.key for b in self.paper_bands]
        if len(bkeys) != len(set(bkeys)):
            raise ValueError("篇数档的代号不能重复")
        for t in self.duration_tiers:
            bad = [k for k in t.prices if k not in bkeys]
            if bad:
                raise ValueError(f"时长档「{t.name}」的价格里有不存在的篇数档：{'、'.join(bad)}")
        akeys = [a.key for a in self.addons]
        if len(akeys) != len(set(akeys)):
            raise ValueError("加购不能重复")
        bad = [k for k in self.materials.order if k not in self.occasions]
        if bad:
            raise ValueError(f"资料清单的场合顺序里有不存在的场合：{'、'.join(bad)}")
        return self

    # ---- 查 ----
    def rule(self, occasion: str) -> OccasionRule | None:
        return self.occasions.get(occasion)

    def needs_approval(self, category: str) -> bool:
        return bool(self.approval.get(category, False))

    @property
    def auto_confirm_hours(self) -> int:
        return self.auto_confirm_days * 24

    def tier(self, key: str) -> DurationTier | None:
        return next((t for t in self.duration_tiers if t.key == key), None)

    def band(self, key: str) -> PaperBand | None:
        return next((b for b in self.paper_bands if b.key == key), None)

    def text(self, key: str, **kw: Any) -> str:
        """入口话术（entry_texts），没有就回空；占位符缺了不报错。"""
        t = self.entry_texts.get(key) or DEFAULT_CONFIG["entry_texts"].get(key, "")
        try:
            return t.format(**kw) if kw else t
        except (KeyError, IndexError):
            return t

    def addon(self, key: str) -> Addon | None:
        return next((a for a in self.addons if a.key == key), None)

    def tiers_sorted(self) -> list[DurationTier]:
        return sorted(self.duration_tiers, key=lambda t: t.max_minutes)

    def bands_sorted(self) -> list[PaperBand]:
        return sorted(self.paper_bands, key=lambda b: b.max_papers)


def dec(v: str) -> Decimal | None:
    try:
        return Decimal(v) if v and v.strip() else None
    except InvalidOperation:
        return None


def _ml(text: str, use: str = "", purpose: str = "", *, key: str = "") -> dict[str, str]:
    return {"text": text, "use": use, "purpose": purpose, "key": key}


DEFAULT_CONFIG: dict[str, Any] = {
    "schema_version": SCHEMA,
    "occasions": {
        # 资料清单（Edison 11-19「要跟他讲清楚，我们要拿到一些什么资料」）：哪几样必须、哪几样有更好是主窗口 11-19 的初稿，
        # 每样后面「用来干什么」那半句是 Claude 写的草稿，Edison 审了在后台「设置 → 各场合要什么」改。
        # 核对用途（required）由 must 的 purpose 算；optional_hint 只给模型看（什么文件登记成什么）。默认时长：我的假设
        "组会文献": {
            "name": "组会读文献",
            "must": [_ml("要讲的论文 PDF（几篇发几篇）", "PPT 的内容全从它来", "论文")],
            "nice": [_ml("组里或学校的 PPT 模板", "有就照它做，没有就用学校配色", "模板"),
                     _ml("老师或组里的要求（固定结构、页数）", "照着排结构、定页数"),
                     _ml("以前被老师问过的问题", "讲稿里提前备好怎么答"),
                     _ml("补充材料", "正文没写透的方法和结果从这里补", "材料")],
            "optional_hint": "补充材料、组里要求或自己的思路、组里模板、以前被老师问过的问题", "default_minutes": 15},
        "课程文献": {
            "name": "课程汇报",
            "must": [_ml("要讲的论文 PDF（几篇发几篇）", "PPT 的内容全从它来", "论文")],
            "nice": [_ml("老师布置的要求", "照着定结构和重点"),
                     _ml("PPT 模板", "有就照它做，没有就用学校配色", "模板")],
            "optional_hint": "补充材料、老师要求、模板", "default_minutes": 10},
        "开题": {
            "name": "开题",
            "must": [_ml("开题报告（或开题 PPT 初稿）", "研究问题、方法、预期都从这里出", "开题报告")],
            "nice": [_ml("学校模板", "有就照它做，没有就用学校配色", "模板"),
                     _ml("老师意见", "老师提过的地方在 PPT 里改到位"),
                     _ml("实验材料", "照着画实验流程，讲清怎么测", "材料")],
            "optional_hint": "开题报告也可以是开题 PPT；实验材料、学校模板、老师意见", "default_minutes": 10},
        "中期": {
            "name": "中期",
            "must": [_ml("开题报告（或开题 PPT）", "交代研究问题和当初的计划", "开题报告"),
                     _ml("现在的进展（文稿、PPT、跑出来的结果图都行）", "讲做了什么、结果怎样、接下来做什么", "进展")],
            "nice": [_ml("学校模板", "有就照它做，没有就用学校配色", "模板"),
                     _ml("实验材料", "照着画实验流程", "材料"),
                     _ml("分析好的结果图", "结果页直接照它讲", "数据")],
            "optional_hint": "开题报告或开题 PPT + 现在的进展（文稿或 PPT）；实验材料；数据（分析过的发结果图）", "default_minutes": 10},
        "答辩": {
            "name": "答辩",
            "must": [_ml("毕业论文全文（Word 也行）", "PPT 的内容全从它来", "论文")],
            "nice": [_ml("学校模板", "有就照它做，没有就用学校配色", "模板"),
                     _ml("预答辩意见", "评委提过的地方重点讲清，讲稿里备好怎么答")],
            "optional_hint": "必需的论文就是客户自己的毕业论文（docx 也算）；选填：学校模板、预答辩意见", "default_minutes": 15},
        "会议": {
            "name": "会议报告",
            "must": [_ml("论文稿或摘要", "PPT 的内容全从它来", "论文")],
            "nice": [_ml("结果图", "结果页直接照它讲", "数据"),
                     _ml("会议对报告的要求（时长、页数、模板）", "照着卡时长和版式")],
            "optional_hint": "必需的论文就是客户自己的论文稿或现有稿（docx、名字不像论文的也算，登记成论文）；选填：结果图、实验材料、会议要求（页数、字号）", "default_minutes": 12},
        "其他": {"name": "其他", "must": [], "nice": [], "optional_hint": "先问清楚是什么场合", "default_minutes": 15},
    },
    "materials": {
        "site_title": "下单前准备好这些",
        "site_lead": "按你的场合准备。必须发的齐了才开工；有的话更好的几样，能让 PPT 更贴你们组和老师的要求。",
        "order_head": "{name}要发这几样，直接发在这里，一次发齐最快：",
        "visitor_head": "{name}要准备这几样，付款认领后发我就行：",
        "overview_head": "资料直接发在这里，要发的主材料看场合：",
        "overview_tail": "告诉我是哪种场合，我把这个场合要的完整列给你。",
        "must_title": "必须发的：",
        "nice_title": "有的话更好：",
        "common_title": "每个场合都要说一声",
        "received_mark": "（收到了）",
        "start_rule": "资料齐了才开工，时限从开工那会儿算，不是从付款算。",
        "other_text": "这个场合没有固定清单：要讲的东西直接发我，我看了告诉你还缺什么。",
        "common": [_ml("讲几分钟", "定页数和详略", key="duration_min"),
                   _ml("哪天汇报", "排期，看赶不赶得上", key="present_date"),
                   _ml("学校名", "放校徽和配色", key="school")],
        "find_refs_line": _ml("要我们找的文献方向和关键词", "我们照它找文献，论文不用你发", key="topic"),
        "order": ["组会文献", "课程文献", "开题", "中期", "答辩", "会议"],
    },
    "daily_quota": 3,
    "buffer_days": 1,
    "queue_horizon_days": 14,
    # 定价方案（Edison 11-18）：现在的价；later_price 是「以后压到」，只是备注
    "duration_tiers": [
        {"key": "light", "name": "轻量", "max_minutes": 15, "max_pages": 20,
         "prices": {"p1": "24.9", "p2_3": "34.9", "p4_5": ""}, "std_hours": 4, "rush_hours": 2, "rush": True, "later_price": "19.9"},
        {"key": "regular", "name": "常规", "max_minutes": 25, "max_pages": 30,
         "prices": {"p1": "29.9", "p2_3": "39.9", "p4_5": "49.9"}, "std_hours": 5, "rush_hours": 3, "rush": True, "later_price": "24.9"},
        {"key": "long", "name": "长", "max_minutes": 40, "max_pages": 45,
         "prices": {"p1": "44.9", "p2_3": "54.9", "p4_5": "64.9"}, "std_hours": 8, "rush_hours": 5, "rush": False, "later_price": ""},
        {"key": "xlong", "name": "超长", "max_minutes": 60, "max_pages": 60,
         "prices": {"p1": "59.9", "p2_3": "69.9", "p4_5": "79.9"}, "std_hours": 12, "rush_hours": 7, "rush": False, "later_price": ""},
    ],
    "paper_bands": [
        {"key": "p1", "name": "1 篇", "max_papers": 1},
        {"key": "p2_3", "name": "2–3 篇", "max_papers": 3},
        {"key": "p4_5", "name": "4–5 篇", "max_papers": 5},
    ],
    "addons": [
        {"key": "rush", "name": "加急", "price": "9.9", "note": "只对轻量、常规、材料齐的单，限名额；做不到退加急费"},
        {"key": "revision", "name": "再改一轮", "price": "9.9", "note": "基础价含一轮，可以买多次"},
        {"key": "find_refs", "name": "帮我找文献", "price": "9.9", "note": "按 1 篇的价算，找到几篇都含在里面；不开放加急"},
    ],
    "find_refs_extra_hours": 2,
    "page_rule_text": DEFAULT_PAGE_RULE,
    "rush_daily_quota": 1,
    "work_start_hour": 9,
    "visitor_daily_limit": 20,
    "visitor_global_daily_limit": 500,
    "refund_block_after": 2,
    "delivery_templates": dict(DEFAULT_TEMPLATES),
    "revise_after_days": 7,
    "auto_confirm_days": 3,
    "delivery": {
        "remind_before_hours": 24,
        "revision_hours": 3,
        "watermark_alpha": 0.20,
        # 模块 E 设计 4.5：自有渠道认客人按钮、超时、后台；小红书第一期人工录单、闲鱼只认后台；抖音认平台信号和后台
        "confirm_sources_by_platform": {
            "web": ["customer", "auto", "edison"], "fk": ["customer", "auto", "edison"],
            "manual": ["customer", "auto", "edison"], "legacy": ["customer", "auto", "edison"],
            "xhs": ["edison", "platform"], "xy": ["edison"], "dy": ["platform", "edison"],
        },
        "texts": {
            "publish_self": "第 {round} 版做好了，先给你看水印版：{url} 要改的在页面里提，哪一页、改成什么，一次写全。没问题就点「确认收货」，确认后马上发可编辑 PPT 和讲稿。",
            "publish_platform": "第 {round} 版做好了，先给你看预览：{url} 要改的在页面里提，一次写全；没问题的话到{platform_name}订单里点确认收货，确认后这个页面会放出可编辑 PPT 和讲稿。",
            "final": "确认收货啦，可编辑的 PPT 和讲稿在这个页面下载：{url}",
        },
    },
    # 资料清单、入口话术：模块 D 的设计（docs/任务单/07_入口_设计.md 附录 A、B）
    "checklists": {
        "default": {
            "items": [
                {"key": "occasion", "label": "什么场合（组会、开题、中期、答辩、会议）", "kind": "fact", "required": True},
                {"key": "main_files", "label": "主材料", "kind": "files", "required": True,
                 "purposes_from": "occasions.required", "count_from": "band"},
                {"key": "duration_min", "label": "讲几分钟", "kind": "fact", "required": True, "within": "tier"},
                {"key": "present_date", "label": "哪天汇报", "kind": "fact", "required": True},
                {"key": "school", "label": "学校（放校徽、配色）", "kind": "fact", "required": False},
                {"key": "template", "label": "学校或组里的模板", "kind": "files", "purposes": ["模板"], "required": False},
                {"key": "requirements", "label": "老师或组里的要求", "kind": "fact", "required": False},
            ],
            "deliver": {"watermark": "link", "final": "file_or_link", "file_max_mb": 20},
        },
        "addons": {"find_refs": {"replace": {"main_files": {"key": "topic", "label": "要我们找的文献方向和关键词", "kind": "fact", "required": True}}}},
        "overrides": {},
    },
    "entry_texts": {
        # {materials}：资料清单（app/intake/materials.py 按场合拼，分行写；场合还不知道就按场合列主材料，再问场合）
        "claim_ok": "已对上你的订单：{sku_name}（激活码尾号 {last4}）。\n\n{materials}\n\n资料齐了才开工。开工后 {hours} 小时内先发你一版带水印的看效果（时限从开工那会儿算，不是从付款算），哪里要改一次说完。",
        "claim_yours": "这单已经在你这里了：{sku_name}，现在{progress}。{next_step}",
        "claim_taken": "这枚激活码已经在别的微信或网页里认领过了。是你本人的话，回到当时那个微信或网页接着聊；有问题发「找负责人」。",
        "claim_not_found": "这枚激活码对不上。核对一下订单发货内容里的码（PSY- 开头，后面 9 位），或者直接打开那条兑换网址。",
        "claim_void": "这枚激活码已经作废了（订单退款或撤单）。有疑问可以问我。",
        "claim_locked": "试错次数有点多，{until} 以后再试吧。",
        "claim_legacy": "这是旧版档位的码，我转给负责人处理。",
        "claim_addon_no_order": "这是加购码（{sku_name}），要挂在一单上用：先发那单的激活码，或者在那单的聊天里发它。",
        "welcome_plain": "同学你好呀，这里是 PsyEngine，我是 AI 助手小鱼，下面的回复由 AI 生成，负责人随时看记录与接手。拿到激活码的话直接发我（PSY- 开头）；还没买的可以问我能做什么、要多久。",
        "file_refused": "资料先别发哦：先把订单里的激活码发我（PSY- 开头），认领上了我才能收资料。",
        "visitor_limited": DEFAULT_VISITOR_LIMIT_TEXT,
        "collect_done": "资料齐了，排在 {start}，预计 {eta} 前先交一版带水印的。成品也会放在这个网页：{delivery_url}",
        "confirm_on_platform": "满意的话去订单里点「确认收货」，平台那边确认后我马上把可编辑的 PPT 和讲稿发你。",
        # 接单助手关着（没配模型入口）时客人发消息回的那句（intake/bot.py manual_fallback；同一个人 6 小时内只回一次）
        "manual_ack": "消息收到了。现在是负责人本人在回复，看到会尽快回你；资料可以先直接发在这里。",
    },
    "deliver_text": DEFAULT_DELIVER_TEXT,
    "notes_text": DEFAULT_NOTES_TEXT,
    "payment": {"text": DEFAULT_PAYMENT_TEXT, "link": "", "qr_image": ""},
    "revisions_included": 1,
    "approval": {c: False for c in REPLY_CATEGORIES},
    "welcome_text": "同学你好呀，这里是 PsyEngine，我是 AI 助手小鱼，下面的回复由 AI 生成，负责人随时看记录与接手。拿到激活码的话直接发我（PSY- 开头）；还没买的可以问我能做什么、多少钱、要多久。",
    "faq": [dict(c) for c in DEFAULT_FAQ],  # 问答卡默认值在 app/intake/faq_cards.py（入口模块 D 接的模块 G 草稿）
}

# 旧设置（schema 1、2）里还能接着用的；档位、价格、待批旧开关都丢掉换新默认
_OLD_KEEP = (
    "occasions", "daily_quota", "buffer_days", "queue_horizon_days", "rush_daily_quota", "deliver_text",
    "notes_text", "payment", "revisions_included", "approval", "welcome_text",
)


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in over.items():
        if k in ("occasions", "duration_tiers", "paper_bands", "addons", "faq", "checklists"):
            out[k] = v  # 整张替换（后台可以删行）
        elif isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = {**out[k], **v}
        else:
            out[k] = v
    return out


# 存过的设置里还是旧默认原文的话，换成新默认（后台改过的不动）。后台存一次设置会把当时所有默认话术一起存进库
OLD_ENTRY_TEXTS: dict[str, tuple[str, ...]] = {
    # 11-19 前的认领话术：必需、选填挤在一行（资料清单改成分行、按场合列）
    "claim_ok": ("已对上你的订单：{sku_name}（激活码尾号 {last4}）。直接在这里发资料，一次发齐最快：\n必需：{required_list}\n"
                 "有的话也发：{optional_list}\n资料齐了就排期开工，开工后 {hours} 小时内先发你一版带水印的看效果，哪里要改一次说完。",),
}


def _upgrade_stored(stored: dict[str, Any]) -> dict[str, Any]:
    """旧设置补新东西：场合没有 must / nice（11-19 资料清单之前存的）就照默认补上（核对用途跟默认一样时）；旧默认话术换新。"""
    out = dict(stored)
    occ = out.get("occasions")
    if isinstance(occ, dict):
        fixed: dict[str, Any] = {}
        for name, rule in occ.items():
            dflt = DEFAULT_CONFIG["occasions"].get(name)
            if isinstance(rule, dict) and "must" not in rule and dflt is not None:
                want = sorted(dict.fromkeys(m["purpose"] for m in dflt["must"]))
                if sorted(rule.get("required") or []) == want:
                    rule = {**rule, "name": rule.get("name") or dflt["name"], "must": dflt["must"], "nice": dflt["nice"]}
            fixed[name] = rule
        out["occasions"] = fixed
    texts = out.get("entry_texts")
    if isinstance(texts, dict):
        out["entry_texts"] = {k: v for k, v in texts.items() if v not in OLD_ENTRY_TEXTS.get(k, ())}
    return out


def load_config(db: Session) -> BizConfig:
    row = db.get(KV, CONFIG_KEY)
    stored = row.value if row and isinstance(row.value, dict) else {}
    if stored and stored.get("schema_version") != SCHEMA:
        stored = {k: v for k, v in stored.items() if k in _OLD_KEEP}
        if stored.get("schema_version", 1) == 1:  # v1 的待批开关、问答卡带着旧说法
            stored.pop("approval", None)
    data = _merge(DEFAULT_CONFIG, _upgrade_stored(stored))
    return BizConfig.model_validate(data)


def save_config(db: Session, cfg: BizConfig) -> BizConfig:
    row = db.get(KV, CONFIG_KEY)
    cfg.schema_version = SCHEMA
    value = cfg.model_dump()
    if row is None:
        db.add(KV(key=CONFIG_KEY, value=value, updated_at=utcnow()))
    else:
        row.value = value
        row.updated_at = utcnow()
    db.flush()
    return cfg


def terms_message(cfg: BizConfig, head: str = "") -> str:
    """「交付什么 + 注意事项」原文（设置里的字，一字不改），前面一行是报价（pricing.terms_head，代码算的）。"""
    parts = [p for p in (head.strip(), cfg.deliver_text.strip(),
                         "先说清楚的几条：\n" + cfg.notes_text.strip() if cfg.notes_text.strip() else "") if p]
    return "\n\n".join(parts)


def payment_message(cfg: BizConfig) -> str:
    """付款渠道原文（设置里的说明 + 链接，一字不改）；说明删空了就补一句「付完拿到激活码发给我」。"""
    p = cfg.payment
    lines = [p.text.strip() or "付完会拿到激活码，复制发给我就行。"]
    if p.link.strip():
        lines.append(p.link.strip())
    return "\n".join(lines)
