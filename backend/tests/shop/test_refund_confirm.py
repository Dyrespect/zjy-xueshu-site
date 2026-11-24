"""后台退款（只在 /api/admin）、退全款作废订单、退款处理中靠定时任务补查、退款太多次的付款人不发码、
3 天超时自动确认（71:59 不确认、72:00 确认；中间提修改不确认，改好的那版交出后重新算）。"""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.db import utcnow
from app.core.nodes import NodeCall, run_node
from app.intake import service
from app.intake.models import ActivationCode, Order
from app.shop.gateways import fake
from app.shop.models import ShopCheckout, ShopRefund
from app.shop.models_io import TickIn, WebSweep
from app.shop.runtime import get_shop, shop_ctx
from tests.conftest import TEST_PASSWORD
from tests.intake.helpers import package, ready
from tests.shop.helpers import PC_UA, checkout_body, make_shop_app


def _paid(c, app, database, *, payer: str = "", band: str = "p1") -> ShopCheckout:
    v = c.post("/api/shop/checkout", json=checkout_body(band=band, extra_revisions=0), headers={"user-agent": PC_UA}).json()
    with database.session() as db:
        row = db.scalar(select(ShopCheckout).where(ShopCheckout.view_token == v["view_token"]))
    raw = fake.simulate_pay(get_shop(app), row.out_trade_no, payer_ref=payer)
    assert c.post("/api/shop/pay/fake/notify", content=raw).status_code == 200
    with database.session() as db:
        return db.get(ShopCheckout, row.id)


def test_refund_only_under_admin(settings, notifier, tmp_path, database):
    """检查 8：路由表里路径带 refund 的都在 /api/admin 下；没登录退不了。"""
    app = make_shop_app(settings, notifier, tmp_path)
    paths = list(app.openapi()["paths"])  # 全部接口（含各模块挂上来的子 router）
    refund_paths = [p for p in paths if "refund" in p.lower()]
    assert refund_paths and all(p.startswith("/api/admin/") for p in refund_paths), refund_paths
    with TestClient(app) as c:
        row = _paid(c, app, database)
        assert c.post("/api/admin/shop/refunds", json={"order_id": row.order_id, "amount_fen": 100}).status_code == 401
        assert row.status == "paid" and not row.refunded_fen


def test_full_and_partial_refund(settings, notifier, tmp_path, database):
    app = make_shop_app(settings, notifier, tmp_path)
    with TestClient(app) as c:
        assert c.post("/api/auth/login", json={"password": TEST_PASSWORD}).status_code == 200
        row = _paid(c, app, database)
        assert c.post("/api/admin/shop/refunds", json={"order_id": row.order_id, "amount_fen": 99999}).status_code == 409
        r = c.post("/api/admin/shop/refunds", json={"order_id": row.order_id, "amount_fen": 1000, "reason": "加急没做到"})
        assert r.json()["exit"] == "ok"
        r = c.post("/api/admin/shop/refunds", json={"order_id": row.order_id, "amount_fen": 1990, "reason": "开工前撤单"})
        assert r.json()["exit"] == "ok"
        with database.session() as db:
            row = db.get(ShopCheckout, row.id)
            o = db.get(Order, row.order_id)
            assert (row.status, row.refunded_fen) == ("refunded", 2990)
            assert o.stage == "void" and o.void_reason == "refund"
            assert db.scalar(select(ActivationCode).where(ActivationCode.order_id == o.id)).status == "void"
            refs = list(db.scalars(select(ShopRefund).order_by(ShopRefund.id)))
            assert [r.status for r in refs] == ["success", "success"] and "作废" in refs[1].void_result
        assert c.post("/api/admin/shop/refunds", json={"order_id": row.order_id, "amount_fen": 1}).status_code == 409
        got = c.get(f"/api/shop/checkout/{row.view_token}").json()
        assert got["status"] == "refunded" and got["code"] == ""  # 退了就不再给码
        rows = c.get("/api/admin/shop/checkouts?status=paid").json()["rows"]
        assert rows[0]["status_label"] == "已退款" and len(rows[0]["refunds"]) == 2
        # 不是自有网页的单：后台退不了（平台单去平台退）
        with database.session() as db:
            _, o2 = ready(db, shop_ctx(app), name="闲鱼单", platform="xy")
            oid = o2.id
        assert c.post("/api/admin/shop/refunds", json={"order_id": oid, "amount_fen": 100}).status_code == 409


def test_refund_processing_then_sweep(settings, notifier, tmp_path, database):
    app = make_shop_app(settings, notifier, tmp_path)
    with TestClient(app) as c:
        assert c.post("/api/auth/login", json={"password": TEST_PASSWORD}).status_code == 200
        row = _paid(c, app, database)
        get_shop(app).fake_trades[row.out_trade_no]["refund_mode"] = "processing"
        r = c.post("/api/admin/shop/refunds", json={"order_id": row.order_id, "amount_fen": 2990, "reason": "撤单"})
        assert r.json()["exit"] == "waiting"
        with database.session() as db:
            assert db.get(Order, row.order_id).stage == "paid"  # 钱还没退成，单不动
        get_shop(app).fake_trades[row.out_trade_no]["refund_mode"] = "ok"
        with app.state.db.session() as db:
            out = run_node("channel.web", NodeCall(db, shop_ctx(app), "system:sweep"), WebSweep(now=utcnow() + timedelta(minutes=2)))
            assert out.output.swept["refunds"] == 1
        with database.session() as db:
            assert db.get(Order, row.order_id).stage == "void"
            assert db.get(ShopCheckout, row.id).status == "refunded"


def test_blocked_buyer_gets_no_code(settings, notifier, tmp_path, database):
    """检查 10：同一个付款人退款作废满 2 次后再来一单：钱收了但不发码、发飞书、后台「该看一眼」里有它。"""
    app = make_shop_app(settings, notifier, tmp_path)
    with TestClient(app) as c:
        assert c.post("/api/auth/login", json={"password": TEST_PASSWORD}).status_code == 200
        for _ in range(2):
            row = _paid(c, app, database, payer="fake:same-payer")
            assert c.post("/api/admin/shop/refunds", json={"order_id": row.order_id, "amount_fen": row.paid_fen}).json()["exit"] == "ok"
        row = _paid(c, app, database, payer="fake:same-payer")
        assert row.create_exit == "blocked" and row.code == "" and row.order_id is None
        got = c.get(f"/api/shop/checkout/{row.view_token}").json()
        assert got["code"] == "" and "没能发激活码" in got["message"]
        assert any("退款作废太多次" in s for s in notifier.sent)
        due = c.get("/api/admin/shop/due").json()["items"]
        assert any(i["kind"] == "paid_no_code" for i in due)
        # 别的付款人照常
        assert _paid(c, app, database, payer="fake:other").code.startswith("PSY-")


def _tick(db, ctx, now):
    return run_node("trigger.confirm_timeout", NodeCall(db, ctx, "system:auto_confirm"), TickIn(now=now)).output


def test_auto_confirm_72h_boundary_and_revision(settings, notifier, tmp_path, database):
    """检查 9：交水印版后 71:59 不确认、72:00 确认；中间提了修改不确认，改好的那版交出后重新算。"""
    app = make_shop_app(settings, notifier, tmp_path)
    ctx = shop_ctx(app)
    with app.state.db.session() as db:
        _, o = ready(db, ctx, name="网页客人", platform="web")
        package(db, ctx, o)
        assert o.stage == "watermarked"
        t0 = o.delivered_at
        out = _tick(db, ctx, t0 + timedelta(hours=71, minutes=59))
        assert o.id not in out.completed and o.stage == "watermarked" and out.hours == 72
        service.submit_revision(db, ctx, o, text="第 3 页的图换成原文图 2")
        assert o.stage == "revising"
        assert o.id not in _tick(db, ctx, t0 + timedelta(hours=80)).completed  # 改稿中：不算
        package(db, ctx, o)  # 改好的第 2 版
        t1 = o.delivered_at
        assert o.stage == "watermarked" and t1 > t0
        assert o.id not in _tick(db, ctx, t1 + timedelta(hours=71, minutes=59)).completed
        out = _tick(db, ctx, t1 + timedelta(hours=72))
        assert out.completed == [o.id]
        assert o.stage in ("completed", "delivered") and o.completed_at is not None
        assert _tick(db, ctx, t1 + timedelta(hours=100)).completed == []  # 幂等：完成的不再动


def test_auto_confirm_reminds_once_before(settings, notifier, tmp_path, database):
    """到期前 24 小时提醒一次（模块 E 的 deliver.preview action=remind），同一版不重复发。"""
    from app.core.events import Event

    app = make_shop_app(settings, notifier, tmp_path)
    ctx = shop_ctx(app)
    with app.state.db.session() as db:
        _, o = ready(db, ctx, name="提醒客人", platform="web")
        package(db, ctx, o)
        t0 = o.delivered_at
        assert _tick(db, ctx, t0 + timedelta(hours=47)).reminded == []
        assert _tick(db, ctx, t0 + timedelta(hours=48)).reminded == [o.id]
        _tick(db, ctx, t0 + timedelta(hours=50))
        sent = [e for e in db.scalars(select(Event).where(Event.type == "delivery.sent"))
                if str((e.content or {}).get("dedupe_key", "")).startswith(f"remind:{o.id}:")]
        assert len(sent) == 1 and o.stage == "watermarked"


def test_auto_confirm_skips_platform_orders(settings, notifier, tmp_path, database):
    app = make_shop_app(settings, notifier, tmp_path, SHOP_AUTO_CONFIRM_PLATFORMS="web,xhs")
    ctx = shop_ctx(app)
    with app.state.db.session() as db:
        _, o = ready(db, ctx, name="平台客人", platform="xhs")
        package(db, ctx, o)
        out = _tick(db, ctx, o.delivered_at + timedelta(days=4))
        assert out.skipped == [o.id] and o.stage == "watermarked"  # 订单中枢的确认来源表不认小红书单的超时
    app2 = make_shop_app(settings, notifier, tmp_path / "b")
    with app2.state.db.session() as db:
        _, o = ready(db, shop_ctx(app2), name="闲鱼客人", platform="xy")
        package(db, shop_ctx(app2), o)
        assert _tick(db, shop_ctx(app2), o.delivered_at + timedelta(days=4)).checked == 0  # 默认不扫平台单


def test_admin_tick_and_status(settings, notifier, tmp_path):
    app = make_shop_app(settings, notifier, tmp_path)
    with TestClient(app) as c:
        assert c.post("/api/auth/login", json={"password": TEST_PASSWORD}).status_code == 200
        r = c.post("/api/admin/shop/tick", json={})
        assert r.status_code == 200 and "confirm" in r.json() and "sweep" in r.json()
        st = c.get("/api/admin/shop/status").json()
        assert st["fake"] and st["auto_confirm_days"] == 3
        assert {m["method"]: m["ready"] for m in st["methods"]}["wechat_native"] is True
