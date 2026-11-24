"""价目和货号（sku.quote 节点的实现）：只读设置，全是纯函数，算价不经模型。

货号：基础 `{时长档}-{篇数档}`（如 regular-p2_3）；加购 `addon-rush` / `addon-revision` / `addon-find_refs`；
四档时期的旧码 `legacy-lit` 这类。契约第三节。

报价规则（定价方案 + 主窗口 11-18 批的做法）：
- 时长档按「档名写上限」取：客户报的时长超出就升一档；超过最大一档 → 报不了（转负责人）。
- 篇数没说：调用方按登记成论文的文件数传；一个都没有按 1 篇报，并提醒问一句。
- 页数超这一档的上限、或这一档不开放这个篇数（轻量不开 4–5 篇）：自动按装得下的档报，并说明为什么升。
- 加急只对开了加急的档，不跟帮我找文献一起；帮我找文献时限加 find_refs_extra_hours。
- 帮我找文献按 1 篇的价算，不再叠多篇（Edison 11-21：「找文献肯定包含在多篇内了」）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.intake.config_store import BizConfig, DurationTier, PaperBand, dec
from app.intake.materials import site_view as materials_view

ADDON_KEYS = ("rush", "revision", "find_refs")
LEGACY_NAMES = {"lit": "文献·标准", "lit_rush": "文献·加急", "res": "研究·标准", "res_rush": "研究·加急"}


@dataclass
class Sku:
    kind: str  # base | addon | legacy
    tier: str = ""
    band: str = ""
    addon: str = ""
    legacy: str = ""


def parse_sku(sku: str) -> Sku | None:
    s = (sku or "").strip()
    if s.startswith("addon-"):
        key = s.removeprefix("addon-")
        return Sku("addon", addon=key) if key in ADDON_KEYS else None
    if s.startswith("legacy-"):
        return Sku("legacy", legacy=s.removeprefix("legacy-"))
    if "-" not in s:
        return None
    tier, band = s.split("-", 1)
    if not tier or not band:
        return None
    return Sku("base", tier=tier, band=band)


def base_sku(tier_key: str, band_key: str) -> str:
    return f"{tier_key}-{band_key}"


def fmt_money(d: Decimal | None) -> str:
    if d is None:
        return ""
    s = format(d.normalize(), "f")
    return s


def addon_names(cfg: BizConfig, addons: list[str] | tuple[str, ...]) -> list[str]:
    out = []
    for k in addons:
        a = cfg.addon(k)
        out.append(a.name if a else k)
    return out


def sku_name(cfg: BizConfig, sku: str, addons: list[str] | tuple[str, ...] = ()) -> str:
    """「常规 · 1 篇」「常规 · 1 篇 + 加急」「加购：再改一轮」「旧档：文献·标准」。"""
    p = parse_sku(sku)
    if p is None:
        return sku or "货号没定"
    if p.kind == "addon":
        a = cfg.addon(p.addon)
        return f"加购：{a.name if a else p.addon}"
    if p.kind == "legacy":
        return f"旧档：{LEGACY_NAMES.get(p.legacy, p.legacy)}"
    t, b = cfg.tier(p.tier), cfg.band(p.band)
    name = f"{t.name if t else p.tier} · {b.name if b else p.band}"
    if addons:
        name += " + " + "、".join(addon_names(cfg, addons))
    return name


def sku_price(cfg: BizConfig, sku: str, addons: list[str] | tuple[str, ...] = ()) -> Decimal | None:
    """货号价 + 同笔加购的价；不开放（价格空、档位不存在）返回 None。"""
    p = parse_sku(sku)
    if p is None or p.kind == "legacy":
        return None
    if p.kind == "addon":
        a = cfg.addon(p.addon)
        return dec(a.price) if a else None
    t = cfg.tier(p.tier)
    if t is None or cfg.band(p.band) is None:
        return None
    base = dec(t.prices.get(p.band, ""))
    if base is None:
        return None
    total = base
    for k in addons:
        a = cfg.addon(k)
        price = dec(a.price) if a else None
        if price is None:
            return None
        total += price
    return total


def sku_open(cfg: BizConfig, sku: str, addons: list[str] | tuple[str, ...] = ()) -> bool:
    return sku_price(cfg, sku, addons) is not None


def base_skus(cfg: BizConfig) -> list[str]:
    """开放的基础货号（价格不空的格子），按时长档、篇数档排。"""
    return [base_sku(t.key, b.key) for t in cfg.tiers_sorted() for b in cfg.bands_sorted() if dec(t.prices.get(b.key, ""))]


def sellable_skus(cfg: BizConfig) -> list[str]:
    """能生成激活码的全部货号：开放的基础货号 + 有价的加购。"""
    return base_skus(cfg) + [f"addon-{a.key}" for a in cfg.addons if dec(a.price) is not None]


def tier_for_minutes(cfg: BizConfig, minutes: int) -> DurationTier | None:
    return next((t for t in cfg.tiers_sorted() if t.max_minutes >= minutes), None)


def band_for_papers(cfg: BizConfig, papers: int) -> PaperBand | None:
    return next((b for b in cfg.bands_sorted() if b.max_papers >= papers), None)


def tier_rank(cfg: BizConfig, key: str) -> int:
    keys = [t.key for t in cfg.tiers_sorted()]
    return keys.index(key) if key in keys else -1


def band_rank(cfg: BizConfig, key: str) -> int:
    keys = [b.key for b in cfg.bands_sorted()]
    return keys.index(key) if key in keys else -1


def rush_allowed(cfg: BizConfig, tier: DurationTier | None, *, find_refs: bool) -> tuple[bool, str]:
    """这一档能不能加急（不看名额和材料；那两条开工时 gate.ready 再看）。"""
    a = cfg.addon("rush")
    if a is None or dec(a.price) is None:
        return False, "加急现在不卖"
    if tier is None:
        return False, "档位还不知道"
    if not tier.rush:
        return False, f"{tier.name}档不开放加急"
    if find_refs:
        return False, "帮我找文献的单不开放加急"
    return True, ""


@dataclass
class Quote:
    ok: bool
    why: str = ""  # 报不了的原因
    sku: str = ""
    tier: DurationTier | None = None
    band: PaperBand | None = None
    papers: int = 1
    base_price: Decimal | None = None
    addons: list[tuple[str, str, Decimal]] = field(default_factory=list)  # (key, 名字, 价)
    total: Decimal | None = None
    hours: int = 0
    rush: bool = False  # 报的价含加急
    rush_ok: bool = False
    rush_why: str = ""
    notes: list[str] = field(default_factory=list)  # 升档、篇数按几篇算……

    @property
    def max_pages(self) -> int:
        return self.tier.max_pages if self.tier else 0

    def line(self, cfg: BizConfig) -> str:
        """一行给客户 / 模型看的报价（数字全是代码算的）。"""
        if not self.ok:
            return f"报不了：{self.why}"
        t, b = self.tier, self.band
        parts = [f"{t.name}档（{t.max_minutes} 分钟以内，{t.max_pages} 页以内）· {b.name}：{fmt_money(self.base_price)} 元"]
        for _, name, price in self.addons:
            parts.append(f"{name} +{fmt_money(price)} 元")
        if self.addons:
            parts.append(f"合计 {fmt_money(self.total)} 元")
        parts.append(f"开工后 {self.hours} 小时内交第一版")
        return "，".join(parts)


def quote(cfg: BizConfig, *, minutes: int, papers: int | None = None, pages: int | None = None,
          rush: bool = False, find_refs: bool = False, extra_revisions: int = 0) -> Quote:
    notes: list[str] = []
    tiers = cfg.tiers_sorted()
    if not tiers or not cfg.paper_bands:
        return Quote(False, "设置里没有价目")
    t = tier_for_minutes(cfg, minutes)
    if t is None:
        return Quote(False, f"讲 {minutes} 分钟超过最长一档（{tiers[-1].max_minutes} 分钟），没有现成的档")
    if find_refs:
        if papers and papers > 1:
            notes.append("帮我找文献按 1 篇的价算，找到几篇都含在里面")
        papers = 1
    elif papers is None or papers < 1:
        notes.append("篇数没说，按 1 篇算，问一下要讲几篇")
        papers = 1
    b = band_for_papers(cfg, papers)
    if b is None:
        top = cfg.bands_sorted()[-1]
        return Quote(False, f"{papers} 篇超过最多一档（{top.name}），没有现成的档")
    idx = tiers.index(t)
    if pages and pages > t.max_pages:
        up = next((x for x in tiers[idx:] if x.max_pages >= pages), None)
        if up is None:
            return Quote(False, f"要 {pages} 页，超过最大一档的 {tiers[-1].max_pages} 页上限")
        notes.append(f"要 {pages} 页，{t.name}档最多 {t.max_pages} 页（{cfg.page_rule_text}），升到{up.name}档")
        t, idx = up, tiers.index(up)
    if dec(t.prices.get(b.key, "")) is None:
        up = next((x for x in tiers[idx + 1:] if dec(x.prices.get(b.key, "")) is not None), None)
        if up is None:
            return Quote(False, f"{t.name}档不开放{b.name}，更长的档也没有")
        notes.append(f"{t.name}档不开放{b.name}，升到{up.name}档")
        t = up
    base = dec(t.prices[b.key])
    rush_ok, rush_why = rush_allowed(cfg, t, find_refs=find_refs)
    addons: list[tuple[str, str, Decimal]] = []
    rush_applied = False
    if rush:
        if rush_ok:
            a = cfg.addon("rush")
            addons.append(("rush", a.name, dec(a.price)))
            rush_applied = True
        else:
            notes.append(f"不能加急：{rush_why}")
    if find_refs:
        a = cfg.addon("find_refs")
        price = dec(a.price) if a else None
        if price is None:
            return Quote(False, "帮我找文献现在不卖")
        addons.append(("find_refs", a.name, price))
    if extra_revisions > 0:
        a = cfg.addon("revision")
        price = dec(a.price) if a else None
        if price is None:
            return Quote(False, "再改一轮现在不卖")
        addons.append(("revision", f"{a.name} × {extra_revisions}", price * extra_revisions))
    hours = promised_hours(cfg, t, rush=rush_applied, find_refs=find_refs)
    total = base + sum((p for _, _, p in addons), Decimal(0))
    return Quote(True, "", base_sku(t.key, b.key), t, b, papers, base, addons, total, hours, rush_applied,
                 rush_ok, rush_why, notes)


def promised_hours(cfg: BizConfig, t: DurationTier, *, rush: bool = False, find_refs: bool = False) -> int:
    """对客承诺的时限：正常用时（标准或加急）+ 帮我找文献加的 + 余量 promise_buffer_hours（Edison 11-19：正常时间往后多说两个小时）。
    对客人说的「开工后 X 小时内交水印版」、排期、交付时限看门、不加急单最早什么时候发，全用它；直接读 std_hours / rush_hours
    只许在这里和设置里（check.py 规矩 23）。"""
    base = t.rush_hours if rush else t.std_hours
    return base + (cfg.find_refs_extra_hours if find_refs else 0) + cfg.promise_buffer_hours


def price_table(cfg: BizConfig) -> list[str]:
    """整张价目（给模型的「现在的情况」用，数字从设置来）。"""
    rows = []
    for t in cfg.tiers_sorted():
        cells = [f"{b.name} {t.prices[b.key]}" for b in cfg.bands_sorted() if dec(t.prices.get(b.key, ""))]
        closed = [b.name for b in cfg.bands_sorted() if not dec(t.prices.get(b.key, ""))]
        tail = f"，{'、'.join(closed)}不开放" if closed else ""
        rush = f"，加急 {promised_hours(cfg, t, rush=True)} 小时" if t.rush else "，不开放加急"
        rows.append(f"{t.name}（{t.max_minutes} 分钟以内，{t.max_pages} 页以内）{'、'.join(cells)}{tail}；"
                    f"标准 {promised_hours(cfg, t)} 小时{rush}（开工后交水印版，已含余量）")
    adds = [f"{a.name} +{a.price}" for a in cfg.addons if a.price]
    if adds:
        rows.append("加购：" + "、".join(adds))
    return rows


def terms_head(cfg: BizConfig, q: Quote) -> str:
    """机器人发「交付什么 + 注意事项」前面那一行（模块 G 定的格式，文案草稿 08）：
    「{档名}·{篇数档}：{价} 元，开工后 {标准} 小时内交水印版。{加购行}」，数字全是代码按货号算的。"""
    if not q.ok or q.tier is None or q.band is None:
        return ""
    std = promised_hours(cfg, q.tier, find_refs=any(k == "find_refs" for k, _, _ in q.addons))
    head = f"{q.tier.name}·{q.band.name}：{fmt_money(q.base_price)} 元，开工后 {std} 小时内交水印版。"
    for key, name, price in q.addons:
        if key == "rush":
            head += f"{name} +{fmt_money(price)} 元，开工后 {promised_hours(cfg, q.tier, rush=True)} 小时内交。"
        elif key == "find_refs":
            head += f"{name} +{fmt_money(price)} 元，时限加 {cfg.find_refs_extra_hours} 小时。"
        else:
            head += f"{name} +{fmt_money(price)} 元。"
    return head


def price_hash(cfg: BizConfig) -> str:
    """价目的指纹：价格、页数、时限、加购、含几轮改……变了它就变（模块 G 用来判断对外文案要不要重发）。"""
    import hashlib
    import json

    snap = {
        "tiers": [t.model_dump() for t in cfg.tiers_sorted()],
        "bands": [b.model_dump() for b in cfg.bands_sorted()],
        "addons": [a.model_dump() for a in cfg.addons],
        "find_refs_extra_hours": cfg.find_refs_extra_hours,
        "promise_buffer_hours": cfg.promise_buffer_hours,
        "revisions_included": cfg.revisions_included,
        "auto_confirm_days": cfg.auto_confirm_days,
        "page_rule_text": cfg.page_rule_text,
    }
    return hashlib.sha256(json.dumps(snap, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def catalog(cfg: BizConfig) -> dict:
    """整张价目和对外说明（sku.catalog 节点的实现；模块 G 的文案、模块 B 的下单页从这里填价，不手写）。"""
    tiers, low = [], 1
    for t in cfg.tiers_sorted():
        tiers.append({"key": t.key, "name": t.name, "min_minutes": low, "max_minutes": t.max_minutes,
                      "max_pages": t.max_pages, "prices": {b.key: dec(t.prices.get(b.key, "")) for b in cfg.bands_sorted()},
                      # 对外说明：给客人看的时限，已含余量（promised_hours）
                      "std_hours": promised_hours(cfg, t), "rush_hours": promised_hours(cfg, t, rush=True) if t.rush else None,
                      "rush": t.rush})
        low = t.max_minutes + 1
    return {
        "tiers": tiers,
        "bands": [{"key": b.key, "name": b.name, "max_papers": b.max_papers} for b in cfg.bands_sorted()],
        "addons": [{"key": a.key, "name": a.name, "price": dec(a.price), "note": a.note} for a in cfg.addons],
        "find_refs_extra_hours": cfg.find_refs_extra_hours,
        "revisions_included": cfg.revisions_included,
        "auto_confirm_days": cfg.auto_confirm_days,
        "page_rule_text": cfg.page_rule_text,
        "deliver_text": cfg.deliver_text,
        "notes_text": cfg.notes_text,
        "materials": materials_view(cfg),  # 下单前准备好这些（资料清单，不进价目指纹）
        "price_hash": price_hash(cfg),
    }

