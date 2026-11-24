"""价目和货号（不调模型）：每格价格、升档、轻量不开 4–5 篇、加急只对轻量常规、找文献不能加急、超档报不了；
货号的名字和价、整张价目、价目指纹、交付和注意事项前面那一行。价格出处：学术汇报/docs/方案/2026-11-18_定价/方案.md。"""

from decimal import Decimal

import pytest

from app.intake import pricing
from app.intake.config_store import DEFAULT_CONFIG, BizConfig

CFG = BizConfig.model_validate(DEFAULT_CONFIG)

# 定价方案「下单页」那张表（Edison 11-18 定的现价）
TABLE = {
    ("light", "p1"): "24.9", ("light", "p2_3"): "34.9",
    ("regular", "p1"): "29.9", ("regular", "p2_3"): "39.9", ("regular", "p4_5"): "49.9",
    ("long", "p1"): "44.9", ("long", "p2_3"): "54.9", ("long", "p4_5"): "64.9",
    ("xlong", "p1"): "59.9", ("xlong", "p2_3"): "69.9", ("xlong", "p4_5"): "79.9",
}


def test_default_table_matches_pricing_plan():
    for (t, b), price in TABLE.items():
        assert pricing.sku_price(CFG, f"{t}-{b}") == Decimal(price)
    assert pricing.sku_price(CFG, "light-p4_5") is None  # 轻量不开放 4–5 篇
    assert len(pricing.base_skus(CFG)) == 11
    tiers = {t.key: (t.max_minutes, t.max_pages, t.std_hours, t.rush_hours, t.rush, t.later_price) for t in CFG.duration_tiers}
    assert tiers == {"light": (15, 20, 4, 2, True, "19.9"), "regular": (25, 30, 5, 3, True, "24.9"),
                     "long": (40, 45, 8, 5, False, ""), "xlong": (60, 60, 12, 7, False, "")}
    assert {a.key: a.price for a in CFG.addons} == {"rush": "9.9", "revision": "9.9", "find_refs": "9.9"}  # Edison 11-21 改 9.9
    assert CFG.find_refs_extra_hours == 2 and CFG.auto_confirm_days == 3


@pytest.mark.parametrize(
    "minutes,papers,sku,price,hours",
    [
        # 时限是对客承诺：正常用时 + 余量 2 小时（12 设计第十五节）
        (10, 1, "light-p1", "24.9", 4 + 2),
        (15, 1, "light-p1", "24.9", 4 + 2),  # 档名写上限：15 分钟就是轻量
        (16, 1, "regular-p1", "29.9", 5 + 2),  # 超出升一档
        (25, 3, "regular-p2_3", "39.9", 5 + 2),
        (30, 2, "long-p2_3", "54.9", 8 + 2),
        (60, 5, "xlong-p4_5", "79.9", 12 + 2),
    ],
)
def test_quote_tier_by_minutes(minutes, papers, sku, price, hours):
    q = pricing.quote(CFG, minutes=minutes, papers=papers)
    assert (q.ok, q.sku, pricing.fmt_money(q.total), q.hours) == (True, sku, price, hours)


def test_quote_upgrades_and_explains():
    q = pricing.quote(CFG, minutes=12, papers=4)  # 轻量不开 4–5 篇 → 常规
    assert q.sku == "regular-p4_5" and any("不开放4–5 篇" in n for n in q.notes)
    q = pricing.quote(CFG, minutes=20, papers=1, pages=35)  # 常规 30 页上限 → 长档
    assert q.sku == "long-p1" and q.max_pages == 45 and any("35 页" in n and "内容页" in "".join(q.notes) for n in q.notes)
    q = pricing.quote(CFG, minutes=20)  # 篇数没说按 1 篇报，提醒问
    assert q.sku == "regular-p1" and any("按 1 篇" in n for n in q.notes)


def test_quote_cannot():
    assert not pricing.quote(CFG, minutes=61, papers=1).ok
    assert not pricing.quote(CFG, minutes=20, papers=6).ok
    assert not pricing.quote(CFG, minutes=20, papers=1, pages=200).ok


def test_rush_and_find_refs_rules():
    q = pricing.quote(CFG, minutes=20, papers=1, rush=True)
    assert q.rush and pricing.fmt_money(q.total) == "39.8" and q.hours == 3 + 2  # 29.9 + 9.9，合计照加不凑 .9；时限含余量
    q = pricing.quote(CFG, minutes=30, papers=1, rush=True)  # 长档不开加急
    assert not q.rush and q.hours == 8 + 2 and any("不开放加急" in n for n in q.notes)
    q = pricing.quote(CFG, minutes=10, papers=1, rush=True, find_refs=True)  # 找文献不能加急
    assert not q.rush and q.hours == 4 + 2 + 2 and pricing.fmt_money(q.total) == "34.8"
    q = pricing.quote(CFG, minutes=20, papers=3, find_refs=True)  # 找文献按 1 篇算，不叠多篇（Edison 11-21）
    assert q.sku == "regular-p1" and pricing.fmt_money(q.total) == "39.8" and any("按 1 篇" in n for n in q.notes)
    q = pricing.quote(CFG, minutes=20, papers=1, extra_revisions=2)
    assert pricing.fmt_money(q.total) == "49.7"


def test_sku_names_and_parse():
    assert pricing.sku_name(CFG, "regular-p1") == "常规 · 1 篇"
    assert pricing.sku_name(CFG, "regular-p1", ["rush"]) == "常规 · 1 篇 + 加急"
    assert pricing.sku_name(CFG, "addon-revision") == "加购：再改一轮"
    assert pricing.sku_name(CFG, "legacy-lit") == "旧档：文献·标准"
    assert pricing.parse_sku("addon-nope") is None and pricing.parse_sku("garbage") is None
    assert pricing.sku_price(CFG, "regular-p1", ["rush"]) == Decimal("39.8")
    assert "addon-find_refs" in pricing.sellable_skus(CFG)


def test_later_price_is_only_a_note():
    cfg = CFG.model_copy(deep=True)
    cfg.duration_tiers[0].later_price = "9.9"
    assert pricing.quote(cfg, minutes=10, papers=1).total == Decimal("24.9")


def test_catalog_hash_and_terms_head():
    cat = pricing.catalog(CFG)
    assert [t["min_minutes"] for t in cat["tiers"]] == [1, 16, 26, 41]
    assert cat["tiers"][0]["prices"]["p4_5"] is None and cat["tiers"][2]["rush_hours"] is None
    h = pricing.price_hash(CFG)
    cfg = CFG.model_copy(deep=True)
    cfg.duration_tiers[1].prices["p1"] = "28.9"
    assert pricing.price_hash(cfg) != h
    cfg2 = CFG.model_copy(deep=True)
    cfg2.welcome_text = "换个欢迎语"
    assert pricing.price_hash(cfg2) == h  # 只有价目相关的变了才变
    head = pricing.terms_head(CFG, pricing.quote(CFG, minutes=20, papers=1, rush=True))
    assert head == "常规·1 篇：29.9 元，开工后 7 小时内交水印版。加急 +9.9 元，开工后 5 小时内交。"  # 对客承诺 = 正常用时 + 余量 2 小时（12 设计第十五节）
