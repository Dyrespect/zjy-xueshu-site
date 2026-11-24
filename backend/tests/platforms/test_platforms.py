"""平台渠道（第一期人工）：小红书人工录单出文案、幂等；固定链接 → 买家填订单号 → 核对 → 出码；平台信号（已完成、申请退款、
退款、退款关闭）；被拦的买家不发码；发货文案过红线；「该看一眼」清单；渠道档案切换。"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.nodes import NodeCall, run_node
from app.intake.models import Order
from app.platforms import redline
from app.platforms.models import PlatformsInbox
from tests.conftest import TEST_PASSWORD
from tests.shop.helpers import make_shop_app


@pytest.fixture
def admin(settings, notifier, tmp_path):
    app = make_shop_app(settings, notifier, tmp_path)
    with TestClient(app) as c:
        assert c.post("/api/auth/login", json={"password": TEST_PASSWORD}).status_code == 200
        c.app_ref = app
        yield c


def _product(c, platform="xhs", sku="regular-p1", listed="29.90", ref="note-001", **kw) -> dict:
    r = c.post("/api/admin/platforms/products", json={"platform": platform, "product_ref": ref, "title": "常规 1 篇",
                                                      "sku": sku, "listed_price": listed, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def _entry(c, platform="xhs", no="P20261118001", **kw):
    return c.post("/api/admin/platforms/manual-entry", json={"platform": platform, "platform_order_id": no, **kw})


def test_manual_entry_gives_text_and_is_idempotent(admin, database):
    p = _product(admin)
    assert p["price_ok"] and p["link"].endswith("/x/" + p["token"])
    r = _entry(admin, product_id=p["id"], buyer_hint="xhs_hangzhou")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["exit"] == "manual" and body["code"].startswith("PSY-")
    assert body["text"] == f"激活码：{body['code']}\n打开 http://127.0.0.1:8710/c/{body['code']} 查看并兑换。"
    again = _entry(admin, product_id=p["id"]).json()
    assert again["exit"] == "exists" and again["code"] == body["code"] and again["text"] == body["text"]
    with database.session() as db:
        o = db.get(Order, body["order_id"])
        assert (o.platform, o.platform_order_id, o.paid_amount, o.buyer_id, o.stage) == ("xhs", "P20261118001", "29.90", "xhs_hangzhou", "paid")
    # 不用商品、直接选货号 + 加购（闲鱼）
    r = _entry(admin, platform="xy", no="3881234567890", sku="long-p1", addons=["revision"])
    assert r.json()["exit"] == "manual"
    assert _entry(admin, no="X1").status_code == 422  # 订单号太短
    assert _entry(admin, no="P20261118999").status_code == 409  # 没选商品也没选货号
    rows = admin.get("/api/admin/platforms/inbox").json()["rows"]
    assert rows[0]["platform_label"] == "闲鱼" and rows[1]["stage_label"] == "已付款"


def test_blocked_platform_buyer_gets_no_delivery(admin, notifier, database):
    """被拦的买家：退款作废满 2 次后再来一单，不出码、没有发货文案（write_delivery 不被调）、发飞书。"""
    for i in range(2):
        r = _entry(admin, no=f"R00000{i}", sku="regular-p1", buyer_hint="same_buyer").json()
        s = admin.post("/api/admin/platforms/xhs/signal", json={"platform_order_id": f"R00000{i}", "kind": "refund"})
        assert s.status_code == 200, s.text
        with database.session() as db:
            assert db.get(Order, r["order_id"]).void_reason == "refund"
    r = _entry(admin, no="R000009", sku="regular-p1", buyer_hint="same_buyer")
    assert r.status_code == 200 and r.json()["exit"] == "blocked" and r.json()["text"] == "" and r.json()["code"] == ""
    assert any("退款作废太多次" in s for s in notifier.sent)
    due = admin.get("/api/admin/platforms/due").json()["items"]
    assert any(i.get("kind") == "problem" and "R000009" in i["title"] for i in due)


def test_signals_hold_release_void_and_early_completion(admin, database):
    a = _entry(admin, no="S0000001", sku="regular-p1").json()
    assert admin.post("/api/admin/platforms/xhs/signal", json={"platform_order_id": "S0000001", "kind": "refund_requested"}).status_code == 200
    with database.session() as db:
        assert db.get(Order, a["order_id"]).hold_reason
    assert admin.post("/api/admin/platforms/xhs/signal", json={"platform_order_id": "S0000001", "kind": "refund_closed"}).status_code == 200
    with database.session() as db:
        assert not db.get(Order, a["order_id"]).hold_reason
    # 平台的已完成来得早（还没交水印版）：先记下
    r = admin.post("/api/admin/platforms/xhs/signal", json={"platform_order_id": "S0000001", "kind": "completed"})
    assert r.status_code == 200 and r.json()["result"] == "recorded"
    with database.session() as db:
        assert db.get(Order, a["order_id"]).platform_completed_at is not None
        assert db.scalar(select(PlatformsInbox).where(PlatformsInbox.platform_order_id == "S0000001")).completed_at is not None
    # 闲鱼：只认后台点的（edison），负责人点「平台已完成」照样算
    b = _entry(admin, platform="xy", no="X0000001", sku="regular-p1").json()
    r = admin.post("/api/admin/platforms/xy/signal", json={"platform_order_id": "X0000001", "kind": "completed"})
    assert r.status_code == 200
    r = admin.post("/api/admin/platforms/xy/signal", json={"platform_order_id": "X0000001", "kind": "refund"})
    assert r.status_code == 200
    with database.session() as db:
        assert db.get(Order, b["order_id"]).stage == "void"
    assert admin.post("/api/admin/platforms/xy/signal", json={"platform_order_id": "NOPE0001", "kind": "refund"}).status_code == 409


def test_fixed_link_claim_verify_flow(admin, database, notifier):
    assert admin.put("/api/admin/platforms/profiles/xhs", json={"adapter": "nope"}).status_code == 400
    r = admin.put("/api/admin/platforms/profiles/xhs", json={"adapter": "fixed_link", "enabled": True})
    assert r.status_code == 200 and r.json()["mode"] == "verify_then_create"
    p = _product(admin, ref="note-777")
    info = admin.get(f"/api/platforms/claim/{p['token']}").json()
    assert info["ok"] and info["platform_label"] == "小红书" and info["sku_name"] == "常规 · 1 篇"
    assert not admin.get("/api/platforms/claim/badtoken1").json()["ok"]
    # 人工录单在固定链接方式下不收
    assert _entry(admin, no="P99999999", product_id=p["id"]).status_code == 409

    assert admin.post("/api/platforms/claim", json={"product_token": p["token"], "platform_order_id": "x"}).status_code == 400
    r = admin.post("/api/platforms/claim", json={"product_token": p["token"], "platform_order_id": " 2026 1118 0001 "})
    assert r.status_code == 200 and r.json()["status"] == "pending"
    token = r.json()["claim_token"]
    assert admin.get(f"/api/platforms/claim/status/{token}").json()["status"] == "pending"
    assert any("固定链接页" in s for s in notifier.sent)
    due = admin.get("/api/admin/platforms/due").json()["items"]
    item = next(i for i in due if i["kind"] == "verify")
    # 同一个订单号又来一次：不给码、不给原来的凭据
    dup = admin.post("/api/platforms/claim", json={"product_token": p["token"], "platform_order_id": "202611180001"}).json()
    assert dup["status"] == "exists" and dup["claim_token"] == "" and dup["code"] == ""

    v = admin.post("/api/admin/platforms/verify", json={"inbox_id": item["inbox_id"], "ok": True, "buyer_hint": "xhs_abc"})
    assert v.status_code == 200 and v.json()["exit"] == "delivered"
    st = admin.get(f"/api/platforms/claim/status/{token}").json()
    assert st["status"] == "ok" and st["code"].startswith("PSY-") and st["redeem_url"]
    with database.session() as db:
        o = db.scalar(select(Order).where(Order.platform_order_id == "202611180001"))
        assert o.platform == "xhs" and o.buyer_id == "xhs_abc"
    # 核对不通过
    r2 = admin.post("/api/platforms/claim", json={"product_token": p["token"], "platform_order_id": "202611180002"}).json()
    rows = admin.get("/api/admin/platforms/inbox").json()["rows"]
    iid = next(x["id"] for x in rows if x["platform_order_id"] == "202611180002")
    assert admin.post("/api/admin/platforms/verify", json={"inbox_id": iid, "ok": False}).json()["exit"] == "rejected"
    assert admin.get(f"/api/platforms/claim/status/{r2['claim_token']}").json()["status"] == "rejected"
    # 限流：同一 IP 每小时最多 10 次
    codes = [admin.post("/api/platforms/claim", json={"product_token": p["token"], "platform_order_id": f"9{i:07d}"}).status_code
             for i in range(10)]
    assert codes[-1] == 429


def test_gate_platform_text(admin):
    app = admin.app_ref
    from app.intake.runtime import get_runtime

    with app.state.db.session() as db:
        call = NodeCall(db, get_runtime(app).ctx, "test")
        ok = run_node("gate.platform_text", call, {"platform": "xhs", "text": "激活码：PSY-ABCDEFGHJ\n打开 http://127.0.0.1:8710/c/PSY-ABCDEFGHJ 查看并兑换。"})
        assert ok.exit == "clean"
        for bad in ("加我 vx 领资料", "激活码 PSY-X，详情看签名", "打开 https://evil.example.com/c/1", "扫码进群号 123"):
            assert run_node("gate.platform_text", call, {"platform": "xhs", "text": bad}).exit == "blocked", bad
        # 抖音档：查实不许放外部网址时（allow_url=false），连兑换网址也算命中；还多一档词
        assert run_node("gate.platform_text", call, {"platform": "dy", "text": "打开 http://127.0.0.1:8710/c/1"}).exit == "clean"  # 127.0.0.1 不是域名
        assert run_node("gate.platform_text", call, {"platform": "dy", "text": "打开 psyppt.pilipala.zj.cn/c/1"}).exit == "blocked"
        assert run_node("gate.platform_text", call, {"platform": "dy", "text": "开题报告"}).exit == "blocked"


def test_random_code_never_blocks_delivery(admin, monkeypatch):
    """激活码是随机的，约 2.4% 会碰巧拼出词表里的 QQ / VX / WX：这不算导流，发货文案照常出（以前会被拦成 text_blocked）。"""
    from app.intake import codes

    unlucky = iter(["PSY-QQWXVX234", "PSY-QQWXVX235"])
    monkeypatch.setattr(codes, "generate_code", lambda: next(unlucky))
    r = _entry(admin, no="U0000001", sku="regular-p1").json()
    assert r["exit"] == "manual" and r["code"] == "PSY-QQWXVX234" and "PSY-QQWXVX234" in r["text"]
    app = admin.app_ref
    from app.intake.runtime import get_runtime

    with app.state.db.session() as db:
        call = NodeCall(db, get_runtime(app).ctx, "test")
        text = "激活码：PSY-QQWXVX235\n打开 http://127.0.0.1:8710/c/PSY-QQWXVX235 查看并兑换。"
        assert run_node("gate.platform_text", call, {"platform": "xhs", "text": text}).exit == "blocked"  # 不说明是自己的码就拦
        assert run_node("gate.platform_text", call, {"platform": "xhs", "text": text, "allow": ["PSY-QQWXVX235"]}).exit == "clean"
        bad = text + " 加微信"
        assert run_node("gate.platform_text", call, {"platform": "xhs", "text": bad, "allow": ["PSY-QQWXVX235"]}).exit == "blocked"


def test_redline_pure_functions():
    assert "微信" in redline.find("加个微信吧")
    assert "微信号" in redline.find("我的 wxid_abc12345")
    assert redline.find_urls("去 a.example.com 看", ("example.com",)) == []
    assert redline.find_urls("去 www.taobao.com 看", ("example.com",)) == ["网址 www.taobao.com"]
    assert redline.find("激活码：PSY-ABCDEFGHJ") == []


def test_due_list_paste_completion_and_price(admin, database):
    p = _product(admin, listed="25.00", ref="note-price")
    assert not p["price_ok"]
    r = _entry(admin, no="D0000001", product_id=p["id"]).json()
    due = admin.get("/api/admin/platforms/due").json()["items"]
    kinds = {i["kind"] for i in due}
    assert {"paste", "price"} <= kinds
    assert admin.post(f"/api/admin/platforms/inbox/{r['inbox_id']}/pasted").json()["ok"]
    with database.session() as db:
        row = db.get(PlatformsInbox, r["inbox_id"])
        row.created_at = row.created_at - timedelta(hours=50)
    due = admin.get("/api/admin/platforms/due").json()["items"]
    assert "paste" not in {i["kind"] for i in due}
    assert any(i["kind"] == "completion" and "49 小时" in i["title"] for i in due)
    admin.patch(f"/api/admin/platforms/products/{p['id']}", json={"listed_price": "29.9"})
    assert "price" not in {i["kind"] for i in admin.get("/api/admin/platforms/due").json()["items"]}


def test_push_not_accepted_for_manual_channels(admin):
    assert admin.post("/api/platforms/xhs/push", content=b"{}").status_code == 404
    assert admin.post("/api/platforms/dy/push", content=b"{}").status_code == 404  # 抖音只有说明卡
    assert admin.post("/api/platforms/zz/push", content=b"{}").status_code == 404
    ov = admin.get("/api/admin/platforms/overview").json()
    assert {p["platform"] for p in ov["profiles"]} == {"xhs", "xy", "dy"} and ov["skus"]
