"""资料清单（Edison 11-19：「做之前要跟他讲清楚，我们要拿到一些什么资料」）：
一个数据源（设置里各场合的 must / nice + materials）→ 官网、小鱼售前、认领那句话、场合定了那条、缺了点名要，都从它出；
按场合出文字；场合定了一次发全、之后不重发；缺了点名要、不齐不开工；旧设置和旧知识库补上新东西。"""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.db import utcnow
from app.core.events import Event
from app.intake import brief, clock, materials, pricing, service
from app.intake.config_store import CONFIG_KEY, DEFAULT_CONFIG, BizConfig, MaterialLine, load_config, save_config
from app.intake.models import KV, Customer, Outbox
from app.intake.reception import kb as rkb
from app.intake.runtime import get_runtime
from app.intake.worker import run_due_jobs
from app.channels.dispatch import dispatch_approved
from app.channels.runtime import get_channels
from tests.intake.helpers import PDF_BYTES, claimed, confirm_brief, make_app, make_ctx, scripted_model

ROOT = Path(__file__).resolve().parents[3]
CFG = BizConfig.model_validate(DEFAULT_CONFIG)


@pytest.fixture
def ctx(tmp_path, notifier):
    return make_ctx(tmp_path, notifier)


def _lists(db, customer_id: int) -> list[Outbox]:
    return list(db.scalars(select(Outbox).where(Outbox.customer_id == customer_id, Outbox.asset == "materials").order_by(Outbox.id)))


# ---------------------------------------------------------------- 一个数据源

def test_required_comes_from_must_lines():
    """核对用途（开工判断看的）由「必须发的」每样登记成什么算出来，不另写一份；没选登记成什么的存不进去。"""
    assert CFG.occasions["中期"].required == ["开题报告", "进展"]
    assert CFG.occasions["组会文献"].required == ["论文"] and CFG.occasions["其他"].required == []
    data = CFG.model_dump(mode="json")
    data["occasions"]["开题"]["must"].append({"text": "实验材料", "use": "画流程图", "purpose": "材料", "key": ""})
    data["occasions"]["开题"]["required"] = ["论文"]  # 前端传来的旧值不算数
    assert BizConfig.model_validate(data).occasions["开题"].required == ["开题报告", "材料"]
    data["occasions"]["开题"]["must"][-1]["purpose"] = ""
    with pytest.raises(ValueError, match="登记成哪种用途"):
        BizConfig.model_validate(data)


def test_every_place_reads_the_same_settings(database, ctx):
    """后台改一处字（开题必须发的那样），官网数据、小鱼售前那段、认领那句话、场合定了那条、追缺的叫法全跟着变。"""
    with database.session() as db:
        cfg = load_config(db)
        cfg.occasions["开题"].must[0].text = "开题报告终稿（PDF 或 Word）"
        cfg.occasions["开题"].nice.append(MaterialLine(text="导师签过字的意见表", use="照着改"))
        save_config(db, cfg)
        cfg = load_config(db)
        site = next(o for o in pricing.catalog(cfg)["materials"]["occasions"] if o["key"] == "开题")
        assert site["must"][0]["text"] == "开题报告终稿（PDF 或 Word）" and site["nice"][-1]["text"] == "导师签过字的意见表"
        assert "开题报告终稿（PDF 或 Word）" in materials.occasion_text(cfg, "开题", head="visitor")
        assert "导师签过字的意见表：照着改" in materials.occasion_text(cfg, "开题", head="visitor")
        assert "开题：开题报告终稿（PDF 或 Word）" in materials.overview_text(cfg)
        c, o = claimed(db, ctx, name="一个来源")
        service.update_order(db, ctx, o, {"occasion": "开题"}, by="edison")
        assert "开题报告终稿（PDF 或 Word）" in service.collect_for(db, o, ctx).ask_text  # 缺了点名要，用的是同一句
        assert "开题报告终稿（PDF 或 Word）" in _lists(db, c.id)[-1].text


def test_material_wording_lives_only_in_settings():
    """对客的资料清单原话只写在订单中枢设置的默认值里；代码、页面、提示词、知识库不许各写一份（示例数据 example.ts 除外）。"""
    phrases = [m.text for r in CFG.occasions.values() for m in [*r.must, *r.nice] if len(m.text) >= 7]
    assert phrases
    files = [p for p in (ROOT / "backend" / "app").rglob("*") if p.suffix in (".py", ".md", ".json")]
    files += [p for p in (ROOT / "frontend" / "src").rglob("*") if p.suffix in (".ts", ".tsx") and p.name != "example.ts"]
    hits = []
    for f in files:
        if f.name == "config_store.py":
            continue
        text = f.read_text(encoding="utf-8")
        hits += [(f.name, p) for p in phrases if p in text]
    assert not hits, hits


# ---------------------------------------------------------------- 按场合出文字

@pytest.mark.parametrize("occ", materials.shown_occasions(CFG))
def test_occasion_text_lists_everything_one_per_line(occ):
    rule = CFG.occasions[occ]
    text = materials.occasion_text(CFG, occ, head="visitor")
    assert text.startswith(f"{rule.label(occ)}要准备这几样")
    lines = text.splitlines()
    for m in [*rule.must, *rule.nice, *CFG.materials.common]:
        want = f"· {m.text}：{m.use}"
        assert want in lines, (occ, want)  # 每样一行，后面半句说用来干什么
    assert text.index("必须发的：") < text.index("有的话更好：")
    assert "· 讲几分钟：" in text.split("有的话更好：")[0] and "· 学校名：" in text.split("有的话更好：")[1]  # 必需不必需看资料清单
    assert lines[-1] == CFG.materials.start_rule
    for bad in ("注意事项", "发卡", "微信号", "二维码", "加微信"):
        assert bad not in text


def test_overview_when_occasion_unknown_and_find_refs():
    text = materials.overview_text(CFG)
    for k in materials.shown_occasions(CFG):
        assert CFG.occasions[k].label(k) in text
    assert "组会读文献、课程汇报：" in text  # 必须发的一样的场合并成一行
    assert text.endswith("告诉我是哪种场合，我把这个场合要的完整列给你。") and "其他" not in text
    refs = materials.occasion_text(CFG, "组会文献", find_refs=True)
    assert "要我们找的文献方向和关键词" in refs and "要讲的论文 PDF" not in refs
    assert materials.missing_names(CFG, "中期", ["进展"]) == ["现在的进展（文稿、PPT、跑出来的结果图都行）"]


# ---------------------------------------------------------------- 开工之前：一次发全、之后不重发

def test_claim_lists_by_occasion_then_full_list_once_when_occasion_is_set(tmp_path, notifier, settings):
    """认领：场合不知道 → 按场合各一行主材料、问场合（分行，不挤一行）；场合定了（需求卡确认）→ 这个场合要的完整发一遍；
    再定同一个场合不重发；换了场合再发新场合的；资料齐了的不发。"""
    from tests.channels.entry_helpers import pool_code

    app = make_app(settings, notifier, tmp_path)
    with TestClient(app) as c:
        rt = get_runtime(app)
        with rt.database.session() as db:
            code = pool_code(db)
        key = c.post(f"/api/channels/redeem/{code}/web", json={}).json()["key"]
        first = c.get(f"/api/channels/web/{key}").json()["messages"][0]["text"]
        assert first.startswith("已对上你的订单") and "要发的主材料看场合：" in first
        assert "\n· 开题：开题报告（或开题 PPT 初稿）\n" in first and "告诉我是哪种场合" in first
        assert "资料齐了才开工" in first and "时限从开工那会儿算" in first
        with rt.database.session() as db:
            cust = db.scalar(select(Customer).where(Customer.external_id == key))
            o = service.current_order(db, cust)
            answers = {q.key: {"choice": brief.DEFAULT_CHOICE} for q in brief.load_settings(db).questions if not q.optional}
            answers["occasion"] = {"choice": "proposal"}  # 客人点了「开题」，其余按推荐
            brief.save(db, rt.ctx, o, answers, by="customer")
            brief.confirm(db, rt.ctx, o, method="customer", by="customer")  # 场合 = 开题写回订单
            assert o.occasion == "开题"
            got = _lists(db, cust.id)
            assert len(got) == 1 and got[0].category == "资料清单" and got[0].author == "system"
            text = got[0].text
            assert text.startswith("开题要发这几样，直接发在这里") and "\n· 开题报告（或开题 PPT 初稿）：研究问题、方法、预期都从这里出\n" in text
            assert "· 老师意见：" in text and "· 学校名：放校徽和配色" in text and text.endswith(CFG.materials.start_rule)
            service.update_order(db, rt.ctx, o, {"occasion": "开题"}, by="edison")
            service.update_order(db, rt.ctx, o, {"title": "x"}, by="edison")
            assert len(_lists(db, cust.id)) == 1  # 同一个场合不重发
            service.update_order(db, rt.ctx, o, {"occasion": "中期"}, by="edison")
            got = _lists(db, cust.id)
            assert len(got) == 2 and got[-1].text.startswith("中期要发这几样")
        c.portal.call(dispatch_approved, get_channels(app))
        msgs = c.get(f"/api/channels/web/{key}").json()["messages"]
        assert [m["card"] for m in msgs if m["card"] == "materials"] == ["materials", "materials"]


def test_claim_with_known_occasion_carries_full_list_and_is_not_resent(database, ctx):
    """认领时场合已经知道（后台手动建的单这类）：认领那句话里就带全这个场合的清单，后面定同一个场合不再发。"""
    from app.core.nodes import NodeCall, run_node
    from app.intake import flow

    with database.session() as db:
        c, o = claimed(db, ctx, name="早知道")
        o.occasion = "答辩"
        flow.ensure_nodes()
        out = run_node("entry.notice", NodeCall(db, ctx, "system"), {
            "session_id": c.id, "template": "claim_ok", "order_id": o.id, "code": "PSY-ABCDEFGHJ"}).output
        text = out.message.text
        assert "答辩要发这几样" in text and "\n必须发的：\n· 毕业论文全文（Word 也行）：PPT 的内容全从它来\n" in text
        assert "\n有的话更好：\n· 学校模板：" in text and "要发的主材料看场合" not in text
        materials.mark_listed(db, o.id, "答辩", via="claim")  # entry.route 认领后记一笔（inbound.do_claim）
        o.occasion = ""
        service.update_order(db, ctx, o, {"occasion": "答辩"}, by="brief")
        assert _lists(db, c.id) == []


def test_received_items_marked_and_complete_orders_get_no_list(database, ctx):
    with database.session() as db:
        c, o = claimed(db, ctx, name="收到了")
        _, f = service.receive_file(db, ctx, c, filename="开题报告.pdf", data=PDF_BYTES)
        f.purpose = "开题报告"
        service.update_order(db, ctx, o, {"occasion": "中期", "duration_min": 10}, by="edison")
        text = _lists(db, c.id)[-1].text
        assert "· 开题报告（或开题 PPT）：交代研究问题和当初的计划（收到了）" in text
        assert "讲几分钟" not in text and "· 哪天汇报：" in text  # 说过的几样不再列

        c2, o2 = claimed(db, ctx, name="齐了")
        _, f2 = service.receive_file(db, ctx, c2, filename="论文.pdf", data=PDF_BYTES)
        f2.purpose = "论文"
        service.update_order(db, ctx, o2, {"duration_min": 15, "present_date": clock.today() + timedelta(days=7)}, by="edison")
        service.update_order(db, ctx, o2, {"occasion": "组会文献"}, by="edison")
        assert _lists(db, c2.id) == []  # 资料已经齐了：不用再发清单


# ---------------------------------------------------------------- 缺了点名要、不齐不开工

def test_missing_named_and_gate_still_blocks(database, ctx):
    with database.session() as db:
        c, o = claimed(db, ctx, name="缺进展")
        confirm_brief(db, ctx, o)
        _, f = service.receive_file(db, ctx, c, filename="开题报告.pdf", data=PDF_BYTES)
        f.purpose = "开题报告"
        service.update_order(db, ctx, o, {"occasion": "中期", "duration_min": 10,
                                          "present_date": clock.today() + timedelta(days=7)}, by="edison")
        col = service.collect_for(db, o, ctx)
        assert not col.complete and col.ask_text == "还要：现在的进展（文稿、PPT、跑出来的结果图都行）"
        assert o.stage == "collecting" and o.started_at is None and o.queued_at is None  # 已有的门照旧挡
        cond = next(x for x in service.conditions_for(db, o) if x.key == "materials")
        assert not cond.ok and "现在的进展" in cond.detail
        _, g = service.receive_file(db, ctx, c, filename="进展.pptx", data=PDF_BYTES)
        g.purpose = "进展"
        service.refresh_status(db, ctx, o)
        assert o.queued_at is not None or o.started_at is not None


# ---------------------------------------------------------------- 小鱼

def _visitor_script(prompt: str):
    if "这个会话还没有订单" not in prompt:
        return [], "好滴"
    if "开题" in prompt.split("【这次客户新说的】")[-1].split("【")[0]:
        return [("send_materials", {"occasion": "开题"})], "开题要准备这几样，我列给你"
    return [("send_materials", {})], "你这次是组会读文献，还是开题、中期这类呀"


def test_bot_sends_materials_before_purchase_by_occasion(tmp_path, notifier, settings):
    app = make_app(settings, notifier, tmp_path, model=scripted_model(_visitor_script))
    with TestClient(app) as c:
        rt = get_runtime(app)
        key = c.post("/api/channels/web/sessions").json()["key"]
        c.post(f"/api/channels/web/{key}/messages", json={"text": "要准备什么资料呀"})
        c.portal.call(run_due_jobs, rt)
        c.portal.call(dispatch_approved, get_channels(app))
        msgs = c.get(f"/api/channels/web/{key}").json()["messages"]
        assert msgs[-1]["text"] == "你这次是组会读文献，还是开题、中期这类呀" and all(m["card"] != "materials" for m in msgs)
        c.post(f"/api/channels/web/{key}/messages", json={"text": "开题的"})
        c.portal.call(run_due_jobs, rt)
        c.portal.call(dispatch_approved, get_channels(app))
        msgs = c.get(f"/api/channels/web/{key}").json()["messages"]
        assert msgs[-2]["text"] == "开题要准备这几样，我列给你"
        assert msgs[-1]["card"] == "materials" and msgs[-1]["text"].startswith("开题要准备这几样，付款认领后发我就行：")
        assert "· 开题报告（或开题 PPT 初稿）：研究问题、方法、预期都从这里出" in msgs[-1]["text"]


def test_reception_kb_knows_ask_materials_and_old_saved_kb_gets_it():
    kb = rkb.load(None)
    card = kb.card("ask_materials")
    assert card is not None and "send_materials" in card.reply and kb.ask("occasion") is not None
    assert "材料直接发我就行，组会就发论文" not in kb.ask("materials").say
    from app.intake.reception import intent

    for t in ("要准备什么资料", "开题的话需要给你们准备什么", "下单前要准备啥"):
        assert intent.classify_rules(kb, [t], ["text"]).intents[0] == "ask_materials", t
    # 后台存过的旧知识库（v1）：补上这一版新加的卡和要问的事，旧默认原话换新，后台删掉的卡不加回来
    old = rkb.defaults()
    old["version"] = 1
    old["intents"] = [x for x in old["intents"] if x["id"] not in ("ask_materials", "invoice")]
    old["asks"] = [x for x in old["asks"] if x["key"] != "occasion"]
    for a in old["asks"]:
        if a["key"] == "materials":
            a["say"] = "材料直接发我就行，组会就发论文，开题就发开题报告"
    got = rkb.ReceptionKB.model_validate(rkb._merge(rkb.defaults(), rkb.upgrade_stored(old, rkb.defaults())))
    assert got.card("ask_materials") is not None and got.card("invoice") is None and got.ask("occasion") is not None
    assert got.ask("materials").say == kb.ask("materials").say


def test_old_saved_settings_get_material_lists_and_new_claim_text(database):
    """线上存过的设置（11-19 之前）：场合没有 must / nice → 照默认补上；认领话术还是旧默认原文 → 换新；后台改过的不动。"""
    with database.session() as db:
        old = CFG.model_dump(mode="json")
        for r in old["occasions"].values():
            r.pop("must"), r.pop("nice"), r.pop("name")
        old["occasions"]["会议"]["required"] = ["论文", "数据"]  # 后台改过核对用途：不照默认补
        old.pop("materials")
        old["entry_texts"]["claim_ok"] = DEFAULT_OLD_CLAIM
        old["entry_texts"]["claim_taken"] = "我自己改过的"
        db.add(KV(key=CONFIG_KEY, value=old, updated_at=utcnow()))
        db.flush()
        cfg = load_config(db)
        assert cfg.occasions["开题"].must[0].text == "开题报告（或开题 PPT 初稿）" and cfg.occasions["开题"].label("开题") == "开题"
        assert [m.text for m in cfg.occasions["会议"].must] == ["论文", "数据"] and cfg.occasions["会议"].required == ["论文", "数据"]
        assert "{materials}" in cfg.entry_texts["claim_ok"] and cfg.entry_texts["claim_taken"] == "我自己改过的"
        assert cfg.materials.common and cfg.materials.order


DEFAULT_OLD_CLAIM = ("已对上你的订单：{sku_name}（激活码尾号 {last4}）。直接在这里发资料，一次发齐最快：\n必需：{required_list}\n"
                     "有的话也发：{optional_list}\n资料齐了就排期开工，开工后 {hours} 小时内先发你一版带水印的看效果，哪里要改一次说完。")


def test_catalog_api_has_materials(tmp_path, notifier, settings):
    app = make_app(settings, notifier, tmp_path)
    with TestClient(app) as c:
        cat = c.get("/api/shop/catalog").json()
        m = cat["materials"]
        assert m["title"] == "下单前准备好这些" and [o["name"] for o in m["occasions"]][:3] == ["组会读文献", "课程汇报", "开题"]
        assert all(o["must"] and "purpose" not in o["must"][0] for o in m["occasions"])  # 只给对客的字
        assert [x["required"] for x in m["common"]] == [True, True, False]
        assert not re.search(r"\d+\.9|\d+\s*元", str(m))
        assert cat["price_hash"] == pricing.price_hash(load_config_for(app))


def load_config_for(app):
    with get_runtime(app).database.session() as db:
        return load_config(db)


def test_listed_event_recorded(database, ctx):
    with database.session() as db:
        c, o = claimed(db, ctx, name="记一笔")
        service.update_order(db, ctx, o, {"occasion": "会议"}, by="brief")
        ev = db.scalar(select(Event).where(Event.type == materials.LISTED_EVENT))
        assert ev.subject == f"order:{o.id}" and ev.content == {"occasion": "会议", "via": "brief"}
        assert materials.listed_occasions(db, o.id) == {"会议"}


def _serve_script(prompt: str):
    if "这个会话还没有订单" in prompt:
        return [], "好滴"
    if "已经原样整张发给客户了" in prompt:  # 情况里写着发过了：客人再问「还要发什么」，小鱼调 send_materials 也不重发
        return [("send_materials", {})], "还差论文，直接发我就行"
    return [("record_info", {"occasion": "组会文献"})], "好嘞，组会的话要发的我列在下面了"


def test_bot_lists_once_when_it_records_occasion(tmp_path, notifier, settings):
    """认领后小鱼从话里记下场合：清单跟在她那句后面发一遍；之后再记同一个场合、客人再问，都不重发，只点名要缺的。"""
    from app.channels.dispatch import dispatch_approved as dispatch

    app = make_app(settings, notifier, tmp_path, model=scripted_model(_serve_script))
    with TestClient(app) as c:
        rt = get_runtime(app)
        from tests.channels.entry_helpers import pool_code

        with rt.database.session() as db:
            code = pool_code(db)
        key = c.post(f"/api/channels/redeem/{code}/web", json={}).json()["key"]
        for text in ("组会用的", "组会文献，讲一篇", "还要发什么吗"):
            c.post(f"/api/channels/web/{key}/messages", json={"text": text})
            c.portal.call(run_due_jobs, rt)
        c.portal.call(dispatch, get_channels(app))
        msgs = c.get(f"/api/channels/web/{key}").json()["messages"]
        lists = [m for m in msgs if m["card"] == "materials"]
        assert len(lists) == 1 and lists[0]["text"].startswith("组会读文献要发这几样")
        i = msgs.index(lists[0])
        assert msgs[i - 1]["text"] == "好嘞，组会的话要发的我列在下面了"  # 跟在小鱼那句后面
        assert msgs[-1]["text"] == "还差论文，直接发我就行"
