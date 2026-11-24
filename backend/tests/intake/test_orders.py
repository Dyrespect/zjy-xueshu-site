"""订单中枢（不调模型）：付款建单（幂等、退款太多不发码、实付对不上记一笔）、认领（码池现建单 / 绑已付款的单、挂会话、
加购码）、作废（撤单退码 / 退款作废码、已完成之后不行）、确认收货（按渠道认来源、平台来得早先记下）、暂停、
最终版关口、客户能拿到哪些文件、查码、按人找单、手动开单。"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.core.db import utcnow
from app.core.events import Event
from app.intake import codes, flow, orders, service
from app.intake.adapters import PaidIn, PlatformSignal
from app.intake.flow import StageError
from app.intake.models import ActivationCode, CodeRedemption, FileRecord, Message, Order, Outbox
from tests.intake.helpers import PDF_BYTES, claimed, confirm_brief, make_ctx, package, ready


@pytest.fixture
def ctx(tmp_path, notifier):
    return make_ctx(tmp_path, notifier)


def _paid(**kw):
    base = dict(platform="xy", platform_order_id="XY001", sku="regular-p1", buyer_id="buyer-1", paid_amount="29.90")
    base.update(kw)
    return PaidIn(**base)


def test_receive_paid_creates_code_and_unclaimed_order_idempotently(database, ctx):
    with database.session() as db:
        r = orders.receive_paid(db, ctx, _paid(source="gzh"), by="adapter:xy")
        assert r.exit == "created" and r.order.stage == "paid" and r.order.customer_id is None
        assert (r.order.platform, r.order.platform_order_id, r.order.sku, r.order.source) == ("xy", "XY001", "regular-p1", "gzh")
        assert r.code.order_id == r.order.id and r.code.status == "unused"
        again = orders.receive_paid(db, ctx, _paid(), by="adapter:xy")
        assert again.exit == "exists" and again.code.id == r.code.id
        assert db.scalar(select(func.count()).select_from(Order)) == 1
        addon = orders.receive_paid(db, ctx, _paid(platform_order_id="XY002", sku="addon-revision", paid_amount="9.90"), by="x")
        assert addon.exit == "created" and addon.order is None and addon.code.sku == "addon-revision"
        with pytest.raises(ValueError):
            orders.receive_paid(db, ctx, _paid(platform_order_id="XY003", sku="light-p4_5"), by="x")  # 不开放
        with pytest.raises(ValueError):
            orders.receive_paid(db, ctx, _paid(platform_order_id="XY004", sku="long-p1", addons=["rush"]), by="x")


def test_paid_amount_mismatch_and_refund_block(database, ctx, notifier):
    with database.session() as db:
        orders.receive_paid(db, ctx, _paid(platform_order_id="M1", paid_amount="25.00"), by="x")
        assert db.scalar(select(func.count()).select_from(Event).where(Event.type == "intake.paid_amount_mismatch")) == 1
        for i in range(2):
            r = orders.receive_paid(db, ctx, _paid(platform_order_id=f"R{i}", buyer_id="bad"), by="x")
            orders.apply_signal(db, ctx, PlatformSignal(platform="xy", platform_order_id=f"R{i}", kind="refund"), by="x")
            assert r.order.stage == "void" and r.order.void_reason == "refund"
        blocked = orders.receive_paid(db, ctx, _paid(platform_order_id="R9", buyer_id="bad"), by="x")
        assert blocked.exit == "blocked" and blocked.code is None
        assert any("去平台主动退款" in s for s in notifier.sent)


def test_claim_binds_paid_order_and_attaches_session(database, ctx, notifier):
    with database.session() as db:
        r = orders.receive_paid(db, ctx, _paid(), by="x")
        c = service.get_or_create_customer(db, "wecom", "wm_claim", nickname="来认领", source="gzh_article")
        service.receive_text(db, ctx, c, "你好，我买了")
        res = orders.claim(db, ctx, c, r.code.code.lower(), channel="wecom")
        assert res.ok and res.kind == "base" and res.order_id == r.order.id
        o = db.get(Order, r.order.id)
        assert (o.stage, o.customer_id, o.wechat_external_userid) == ("claimed", c.id, "wm_claim")
        assert db.scalar(select(Message).where(Message.customer_id == c.id)).order_id == o.id  # 会话挂上了
        assert db.scalar(select(CodeRedemption)).channel == "wecom"
        new = [(t, link, lv) for t, link, lv in zip(notifier.sent, notifier.links, notifier.levels) if t.startswith("新单")]
        assert new == [(f"新单：来认领 认领了 #{o.id}（{res.sku_name}）", f"/admin/conversations/{c.id}", "count")]  # 11-19：只进日报的个数
        again = orders.claim(db, ctx, c, r.code.code, channel="wecom")  # 幂等
        assert again.ok and "认领过" in again.detail
        assert sum(t.startswith("新单") for t in notifier.sent) == 1  # 再交同一枚码不再通知
        other = service.get_or_create_customer(db, "web", "key-other-0123456789")
        bad = orders.claim(db, ctx, other, r.code.code, channel="web")
        assert (bad.ok, bad.result, bad.claimed_by) == (False, "used", c.id)


def test_pool_code_creates_order_on_claim_and_files_before_claim_are_refused(database, ctx):
    with database.session() as db:
        c = service.get_or_create_customer(db, "web", "key-pool-0123456789")
        msg, rec = service.receive_file(db, ctx, c, filename="paper.pdf", data=PDF_BYTES)
        assert rec is None and "没收" in msg.text  # 没认领不收资料
        assert db.scalar(select(func.count()).select_from(FileRecord)) == 0
        refused = db.scalar(select(Outbox).where(Outbox.customer_id == c.id))
        assert "激活码" in refused.text
        _, rows = codes.generate_batch(db, sku="light-p2_3", count=1, platform="fk")
        res = orders.claim(db, ctx, c, f"码是 {rows[0].code}", channel="web")
        o = db.get(Order, res.order_id)
        assert o.platform == "fk" and o.sku == "light-p2_3" and o.quoted_price == "34.9" and o.stage == "claimed"


def test_addon_codes_attach_to_current_order(database, ctx):
    with database.session() as db:
        c, o = claimed(db, ctx, name="加购")
        rush = codes.generate_batch(db, sku="addon-rush", count=1)[1][0]
        rev = codes.generate_batch(db, sku="addon-revision", count=1)[1][0]
        fr = codes.generate_batch(db, sku="addon-find_refs", count=1)[1][0]
        assert orders.claim(db, ctx, c, rush.code, channel="web").ok
        assert orders.addon_keys(o) == ["rush"]
        r = orders.claim(db, ctx, c, fr.code, channel="web")  # 加急的单不能再加找文献
        assert not r.ok and r.result == "wrong" and "加急" in r.detail
        assert orders.claim(db, ctx, c, rev.code, channel="web").ok and o.extra_revisions == 1
        stranger = service.get_or_create_customer(db, "web", "key-stranger-0123456789")
        _, (x,) = codes.generate_batch(db, sku="addon-revision", count=1)
        r = orders.claim(db, ctx, stranger, x.code, channel="web")
        assert not r.ok and "先认领基础档" in r.detail


def test_two_orders_for_one_person_current_is_most_recent(database, ctx):
    with database.session() as db:
        c, first = claimed(db, ctx, name="两单")
        _, (code2,) = codes.generate_batch(db, sku="long-p1", count=1)
        r = orders.claim(db, ctx, c, code2.code, channel="web")  # 主窗口 K2：两单都允许
        assert r.ok and r.order_id != first.id
        assert orders.current_order(db, c).id == r.order_id
        assert {o.id for o in orders.active_orders(db, c)} == {first.id, r.order_id}
        # 按人算：同一个人的微信会话也看得到
        w = service.get_or_create_customer(db, "wecom", "wm_same")
        orders.set_customer_memory(db, c.id, person_id=99)
        orders.set_customer_memory(db, w.id, person_id=99, memory_brief="上次用学校模板")
        assert orders.current_order(db, w).id == r.order_id


def test_void_return_vs_refund_and_not_after_completed(database, ctx):
    with database.session() as db:
        c, o = claimed(db, ctx, name="撤单")
        code = db.get(ActivationCode, o.code_id).code
        orders.void_order(db, ctx, o, code_action="return", by="bot", why="老师取消了")
        row = db.scalar(select(ActivationCode).where(ActivationCode.code == code))
        assert (o.stage, o.voided_from, o.void_reason, row.status, row.order_id) == ("void", "claimed", "return", "unused", None)
        assert db.scalar(select(func.count()).select_from(CodeRedemption)) == 0
        res = orders.claim(db, ctx, c, code, channel="web")  # 退回的码还能再用：另建一单
        assert res.ok and res.order_id != o.id
        with pytest.raises(StageError):
            orders.void_order(db, ctx, o, code_action="void", by="x", why="")  # 作废过的不能再作废
        _, m = ready(db, ctx, name="开工了")
        assert m.stage == "making"
        with pytest.raises(StageError, match="开工"):
            orders.void_order(db, ctx, m, code_action="return", by="x", why="")
        orders.void_order(db, ctx, m, code_action="void", by="edison", why="平台退款")
        assert m.void_reason == "refund" and db.get(ActivationCode, m.code_id).status == "void"
        assert service.production_messages(db, m)[-1].text.startswith("这单作废了")
        _, d = ready(db, ctx, name="已完成")
        package(db, ctx, d)
        orders.mark_completed(db, ctx, d, source="customer", by="customer")
        assert d.stage in ("completed", "delivered")
        with pytest.raises(StageError, match="平台售后"):
            orders.void_order(db, ctx, d, code_action="void", by="x", why="")


def test_confirm_sources_by_platform_and_early_platform_completion(database, ctx):
    with database.session() as db:
        _, x = ready(db, ctx, name="闲鱼单", platform="xy")
        package(db, ctx, x)
        assert x.stage == "watermarked"
        with pytest.raises(StageError, match="平台订单"):
            orders.mark_completed(db, ctx, x, source="customer", by="customer")  # 平台单客人自己点不算
        assert orders.mark_completed(db, ctx, x, source="auto", by="b") == "ignored"  # 闲鱼不认超时
        assert orders.mark_completed(db, ctx, x, source="edison", by="edison") == "completed"
        assert x.stage == "delivered" and x.completed_at and x.finished_at
        # 小红书：平台信号来得早（还在收资料）→ 先记下
        r = orders.receive_paid(db, ctx, _paid(platform="xhs", platform_order_id="XHS1"), by="x")
        orders.apply_signal(db, ctx, PlatformSignal(platform="xhs", platform_order_id="XHS1", kind="completed"), by="x")
        assert r.order.platform_completed_at is not None and r.order.stage == "paid"


def test_refund_requested_holds_then_released(database, ctx, notifier):
    with database.session() as db:
        r = orders.receive_paid(db, ctx, _paid(platform_order_id="H1"), by="x")
        c = service.get_or_create_customer(db, "web", "key-hold-0123456789")
        orders.claim(db, ctx, c, r.code.code, channel="web")
        o = db.get(Order, r.order.id)
        confirm_brief(db, ctx, o)
        orders.apply_signal(db, ctx, PlatformSignal(platform="xy", platform_order_id="H1", kind="refund_requested"), by="x")
        assert o.hold_reason
        service.receive_text(db, ctx, c, "组会")
        service.receive_file(db, ctx, c, filename="p.pdf", data=PDF_BYTES)[1].purpose = "论文"
        service.update_order(db, ctx, o, {"occasion": "组会文献", "duration_min": 15,
                                          "present_date": utcnow().date() + timedelta(days=9)})
        assert o.started_at is None  # 暂停：不开工
        orders.apply_signal(db, ctx, PlatformSignal(platform="xy", platform_order_id="H1", kind="refund_closed"), by="x")
        assert not o.hold_reason and o.stage == "making"  # 恢复：接着判断，开工


def test_final_gate_and_customer_files(database, ctx):
    with database.session() as db:
        _, o = ready(db, ctx, name="关口")
        with pytest.raises(StageError):
            orders.release_final(db, ctx, o, by="x")  # 不是已完成不发
        package(db, ctx, o)
        files = orders.deliverables_for_customer(db, o)
        assert files and {f.purpose for f in files} == {"水印版"} and [f.page_no for f in files] == [1, 2]
        assert not db.scalar(select(func.count()).select_from(Outbox).where(Outbox.kind == "file"))  # 水印阶段不发文件
        orders.mark_completed(db, ctx, o, source="customer", by="customer")
        assert o.stage == "delivered"
        files = orders.deliverables_for_customer(db, o)
        assert {f.purpose for f in files} == {"PPT", "讲稿"}  # 最终版，不含水印版
        sent = [ob.text for ob in db.scalars(select(Outbox).where(Outbox.kind == "file"))]
        assert sorted(sent) == ["deck.pptx", "讲稿.docx"]


def test_completed_without_finals_waits_then_releases(database, ctx):
    with database.session() as db:
        _, o = ready(db, ctx, name="没最终版")
        from app.intake.models import PAGE_KIND
        from tests.intake.helpers import png

        service.add_deliverable(db, ctx, o, filename="deck.pptx", data=b"PK", kind="PPT")
        service.add_deliverable(db, ctx, o, filename="p1.png", data=png(), kind=PAGE_KIND, page_no=1)
        service.submit_package(db, ctx, o, by="maker")
        for f in db.scalars(select(FileRecord).where(FileRecord.order_id == o.id, FileRecord.purpose == "PPT")):
            db.delete(f)  # 假装最终版还没传
        db.flush()
        orders.mark_completed(db, ctx, o, source="customer", by="customer")
        assert o.stage == "completed" and o.finished_at is None
        assert "请传最终版" in service.production_messages(db, o)[-1].text
        service.add_deliverable(db, ctx, o, filename="final.pptx", data=b"PK2", kind="PPT")
        service.submit_package(db, ctx, o, by="maker")  # 交上来就发
        assert o.stage == "delivered"


def test_lookup_and_manual_order_and_waiting_list(database, ctx):
    with database.session() as db:
        assert orders.lookup_code(db, "PSY-AAAAAAAAA").state == "not_found"
        r = orders.receive_paid(db, ctx, _paid(platform_order_id="L1"), by="x")
        assert orders.lookup_code(db, r.code.code).state == "paid"
        _, (pool,) = codes.generate_batch(db, sku="regular-p1", count=1)
        assert orders.lookup_code(db, pool.code).state == "unused_pool"
        c, o = claimed(db, ctx, name="查码")
        lk = orders.lookup_code(db, db.get(ActivationCode, o.code_id).code)
        assert (lk.state, lk.customer_id, lk.stage) == ("claimed", c.id, "claimed")
        m = service.get_or_create_customer(db, "web", "key-manual-0123456789")
        mo = orders.create_manual_order(db, ctx, m, "regular-p1", by="edison", why="师妹")
        assert (mo.platform, mo.stage, mo.customer_id) == ("manual", "claimed", m.id)
        with pytest.raises(ValueError):
            orders.create_manual_order(db, ctx, m, "regular-p1", by="edison")
        _, w = ready(db, ctx, name="等确认")
        package(db, ctx, w)
        w.delivered_at = utcnow() - timedelta(days=4)
        assert orders.orders_waiting_customer(db, platforms=["fk"], idle_since=utcnow() - timedelta(days=3)) == [w.id]
        assert orders.orders_waiting_customer(db, platforms=["xy"], idle_since=utcnow()) == []


def test_free_text_revision_split_by_page():
    """交付页只写了一段话：「第 N 页」开头的记成那一页，其他的算整体意见（按行、分号拆）。"""
    from app.intake.service import split_revision_text

    got = split_revision_text("第 2 页的结果图换成原文的图 3；配色再深一点\n1. 第12页：字太多删一半")
    assert got == [{"page": 2, "text": "结果图换成原文的图 3"}, {"page": None, "text": "配色再深一点"},
                   {"page": 12, "text": "字太多删一半"}]
    assert split_revision_text("整体再简洁点") == [{"page": None, "text": "整体再简洁点"}]


def _released_files(db, o, after_id: int) -> list[str]:
    return sorted(ob.text for ob in db.scalars(select(Outbox).where(Outbox.order_id == o.id, Outbox.kind == "file", Outbox.id > after_id)))


def _last_outbox_id(db) -> int:
    return db.scalar(select(func.max(Outbox.id))) or 0


def test_redelivery_after_delivered_goes_to_next_round_and_releases_latest_only(database, ctx):
    """已交付后再改、交新的最终版：落到下一个版次，只放最新这一批（不把上一批的 pptx 一起再发）。"""
    from app.intake import production
    from tests.intake.helpers import pptx_bytes

    with database.session() as db:
        _, o = ready(db, ctx, name="再改两次")
        package(db, ctx, o)
        orders.mark_completed(db, ctx, o, source="customer", by="customer")
        assert (o.stage, o.delivery_round) == ("delivered", 1)
        assert not service.has_undelivered_deliverable(db, o)  # 放出的那批不再算「没交的新一版」

        service.submit_revision(db, ctx, o, text="第 1 页标题再短一点")
        assert o.flow_step == "revising_after"
        mark = _last_outbox_id(db)
        service.add_deliverable(db, ctx, o, filename="deck_v2.pptx", data=pptx_bytes(2), kind="PPT")
        service.add_deliverable(db, ctx, o, filename="讲稿.docx", data=b"docx2", kind="讲稿")
        service.submit_package(db, ctx, o, by="maker")
        assert (o.stage, o.delivery_round) == ("delivered", 2)
        assert _released_files(db, o, mark) == ["deck_v2.pptx", "讲稿.docx"]

        orders.apply_addon(db, ctx, o, "revision", by="edison")  # 再买一轮
        service.submit_revision(db, ctx, o, text="第 2 页配色再深一点")
        mark = _last_outbox_id(db)
        production.maker_package(db, ctx, o, [("deck_v3.pptx", pptx_bytes(2), ""), ("讲稿.docx", b"docx3", "")], [])
        assert (o.stage, o.delivery_round) == ("delivered", 3)
        assert _released_files(db, o, mark) == ["deck_v3.pptx", "讲稿.docx"]  # 只有第 3 批，没有 deck_v2
        assert sorted(f.filename for f in orders.final_files(db, o)) == ["deck_v3.pptx", "讲稿.docx"]


def test_maker_reupload_discards_unpublished_files(database, ctx):
    """制作中重交一版：之前存了、还没发布的 pptx 和整页图作废，新一版只有新文件；放最终版时只发一份 pptx。"""
    from app.intake import production
    from app.intake.models import PAGE_KIND
    from tests.intake.helpers import png, pptx_bytes

    with database.session() as db:
        _, o = ready(db, ctx, name="重交")
        assert o.stage == "making"
        # 上一次传了一半（旧 pptx、三张旧页图），没交成
        service.add_deliverable(db, ctx, o, filename="old.pptx", data=pptx_bytes(3), kind="PPT")
        for i in (1, 2, 3):
            service.add_deliverable(db, ctx, o, filename=f"old-{i}.png", data=png(), kind=PAGE_KIND, page_no=i)
        production.maker_package(db, ctx, o, [("deck.pptx", pptx_bytes(2), ""), ("讲稿.docx", b"docx", "")],
                                 [(1, "page-01.png", png(), "image/png"), (2, "page-02.png", png(), "image/png")])
        assert o.stage == "watermarked" and o.delivery_round == 1
        names = sorted(f.filename for f in db.scalars(select(FileRecord).where(
            FileRecord.order_id == o.id, FileRecord.round == 1, FileRecord.purpose != "水印版")))
        assert names == ["deck.pptx", "page-01.png", "page-02.png", "讲稿.docx"]
        ev = db.scalar(select(Event).where(Event.type == "intake.deliverables_discarded"))
        assert ev is not None and sorted(ev.content["files"]) == ["old-1.png", "old-2.png", "old-3.png", "old.pptx"]

        mark = _last_outbox_id(db)
        orders.mark_completed(db, ctx, o, source="customer", by="customer")
        assert _released_files(db, o, mark) == ["deck.pptx", "讲稿.docx"]


def test_discard_unpublished_never_touches_published_rounds(database, ctx):
    with database.session() as db:
        _, o = ready(db, ctx, name="不动发过的")
        package(db, ctx, o)  # 第 1 版发布了
        assert service.discard_unpublished(db, ctx, o, by="edison", why="测") == []
        service.add_deliverable(db, ctx, o, filename="错的.pptx", data=b"PK", kind="PPT")
        assert service.discard_unpublished(db, ctx, o, by="edison", why="传错了") == ["错的.pptx"]
        assert {f.round for f in db.scalars(select(FileRecord).where(FileRecord.order_id == o.id, FileRecord.role != "material"))} == {1}
