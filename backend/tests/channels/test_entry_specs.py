"""入口可换（C12）、认领话术一条装得下且不写价格（C6）、D 的节点说明卡都在、问答卡（模块 G 草稿 F1–F4、F6、F8）。"""

from __future__ import annotations

import itertools
import re

from fastapi.testclient import TestClient

from app.channels import entries
from app.channels.entry_types import EntryCaps, EntrySpec
from app.core.nodes import NodeCall, all_cards, run_node
from app.intake import flow, pricing, service
from app.intake.config_store import DEFAULT_CONFIG, BizConfig, load_config
from app.intake.faq_cards import cards_for
from app.intake.runtime import get_runtime
from tests.channels.entry_helpers import entry_app, pool_code, set_entry
from tests.intake.helpers import claimed

# 跟 scripts/check.py 规矩 10 同一个价格正则
PRICE = re.compile(r"(?<![\d.])[1-9]\d{0,2}\.9(?![\d.%])|(?<![\d.])\d{1,4}(?:\.\d{1,2})?\s*元")


def test_new_entry_adds_button(tmp_path, notifier, settings):
    app = entry_app(settings, notifier, tmp_path)
    fake = EntrySpec(node_id="entry.fakemini", channel="mini", label="用小程序继续", caps=EntryCaps(), resume="link",
                     available=lambda db, rt: (True, ""), resume_link=lambda db, code: f"https://mini.example/r?c={code}", order=30)
    entries.register_entry(fake)
    try:
        set_entry(app, redeem_entries=["entry.webchat", "entry.wecom", "entry.fakemini"])
        with TestClient(app) as c:
            with get_runtime(app).database.session() as db:
                code = pool_code(db)
            acts = c.get(f"/api/channels/redeem/{code}").json()["actions"]
            assert [a["entry"] for a in acts] == ["entry.webchat", "entry.fakemini"]  # 微信客服没开不出现；假入口多一个按钮
            assert acts[1]["url"] == f"https://mini.example/r?c={code}" and acts[1]["label"] == "用小程序继续"
    finally:
        entries.unregister_entry("entry.fakemini")


def test_claim_text_fits_and_has_no_price(tmp_path, notifier, settings):
    app = entry_app(settings, notifier, tmp_path)
    with TestClient(app):
        rt = get_runtime(app)
        with rt.database.session() as db:
            cfg = load_config(db)
            addon_sets = [(), ("rush",), ("find_refs",), ("revision",), ("rush", "revision")]
            n = 0
            for i, (sku, addons) in enumerate(itertools.product(
                    [k for k in pricing.sellable_skus(cfg) if pricing.parse_sku(k).kind == "base"], addon_sets)):
                c, o = claimed(db, rt.ctx, name=f"c{i}", channel="wecom", sku=sku, addons=addons)
                for occ in [*cfg.occasions, ""]:
                    o.occasion = occ
                    out = run_node("entry.notice", NodeCall(db, rt.ctx, "system"), {
                        "session_id": c.id, "template": "claim_ok", "order_id": o.id, "code": "PSY-ABCDEFGHJ"}).output
                    text = out.message.text
                    assert len(text.encode("utf-8")) <= 2048, (sku, addons, occ)
                    assert not out.shortened
                    assert not PRICE.search(text), (sku, addons, occ, text)
                    assert "{" not in text and ("必须发的" in text or "要发的主材料看场合" in text) and "资料齐了才开工" in text
                    n += 1
            assert n > 50


def test_d_node_cards_registered():
    flow.ensure_nodes()
    ids = {c.id for c in all_cards() if c.owner == "D"}
    assert {"entry.route", "entry.notice", "entry.webchat", "entry.wecom", "entry.redeem_page", "customer.memory",
            "notify.email"} <= ids
    assert {s.node_id for s in entries.all_specs()} >= {"entry.webchat", "entry.wecom"}


TOPICS = ["价格", "多久", "改几次", "问卷", "写论文", "英文", "确认收货", "退款", "篇数", "加急", "找文献", "外泄", "AI",
          "样例", "校徽", "超过", "怎么买"]


def test_faq_cards_fill_and_follow_settings():
    cfg = BizConfig.model_validate(DEFAULT_CONFIG)
    raw = [c for c in cfg.faq if "bot" in c.channels]
    for t in TOPICS:  # F1：话题都有卡
        assert any(t in c.q for c in raw), t
    for c in cfg.faq:  # F3：没填之前不手写价
        assert not PRICE.search(c.a) and not PRICE.search(c.hint), c.q
    bot = cards_for(cfg, "bot")
    joined = "；".join(f"{q} → {a}（{h}）" for q, a, h in bot)
    assert "{" not in joined  # F2：填得完
    assert len(joined) <= 2000 and all(len(a) <= 120 for _, a, _ in bot)  # F6：长度（a 填完价后略长于 100 字）
    tools = set(re.findall(r"\b([a-z]+_[a-z_]+)\b", " ".join(h for _, _, h in bot)))
    assert tools <= {"quote_price", "send_terms", "send_payment", "send_owner_wechat", "send_sample"}  # F8：只点访客问答能用的工具
    # F4：跟着设置变
    data = dict(DEFAULT_CONFIG)
    data["revisions_included"] = 2
    tiers = [dict(t) for t in DEFAULT_CONFIG["duration_tiers"]]
    tiers[1]["std_hours"] = 6
    data["duration_tiers"] = tiers
    cfg2 = BizConfig.model_validate(data)
    joined2 = "；".join(a for _, a, _ in cards_for(cfg2, "bot"))
    assert "含 2 轮" in joined2 and "常规 8 小时" in joined2 and "含 1 轮" not in joined2 and "常规 7 小时" not in joined2  # 6 + 余量 2


def test_situation_has_faq_and_visitor_mode(tmp_path, notifier, settings):
    """访客问答的情况里有填好的问答卡（只含 bot 的），没有订单块。"""
    from app.intake.bot import take_snapshot

    app = entry_app(settings, notifier, tmp_path)
    with TestClient(app):
        rt = get_runtime(app)
        with rt.database.session() as db:
            c = service.get_or_create_customer(db, "web", "key-faq-0123456789abcdef")
            service.receive_text(db, rt.ctx, c, "多少钱", claim=False)
            snap = take_snapshot(db, rt.ctx, c)
            assert snap.deps.mode == "visitor_qa"
            assert "【常见问题怎么答】" in snap.situation and "24.9 元起" in snap.situation and "{起价}" not in snap.situation
            assert "平台订单完成后（你点确认收货，或平台自动确认）" not in snap.situation  # platform 版的卡不进助手
