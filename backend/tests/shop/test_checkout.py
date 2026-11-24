"""自有网页下单（假网关 pay.fake）：金额只认服务端、按 User-Agent 给付款方式、档位组合、回调幂等和并发、回调丢了靠查单、
过期关单、关单后到的付款照样建单、限流、生产不许开假网关。"""

from __future__ import annotations

import asyncio
import threading
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.db import utcnow
from app.core.nodes import NodeCall, run_node
from app.intake.models import ActivationCode, Order
from app.intake.runtime import get_runtime
from app.shop.gateways import fake
from app.shop.models import ShopCheckout, ShopNotification
from app.shop.models_io import WebNotify, WebSweep
from app.shop.router import lifespan
from app.shop.runtime import get_shop, shop_ctx
from tests.shop.helpers import MOBILE_UA, PC_UA, WECHAT_UA, checkout_body, make_shop_app


def _count(database, model) -> int:
    with database.session() as db:
        return db.scalar(select(func.count()).select_from(model)) or 0


def _row(database, token: str) -> ShopCheckout:
    with database.session() as db:
        return db.scalar(select(ShopCheckout).where(ShopCheckout.view_token == token))


def test_amount_only_from_server(settings, notifier, tmp_path, database):
    """检查 6：前端把价改成 0.01，待付款单和网关收到的仍是报价金额。"""
    app = make_shop_app(settings, notifier, tmp_path)
    with TestClient(app) as c:
        q = c.post("/api/shop/quote", json={"tier": "regular", "band": "p2_3", "extra_revisions": 1, "total": "0.01"}).json()
        assert q["ok"] and q["total"] == "49.8" and q["total_fen"] == 4980
        body = checkout_body(price=0.01, total="0.01", total_fen=1, amount_fen=1)
        v = c.post("/api/shop/checkout", json=body, headers={"user-agent": PC_UA}).json()
        assert v["total_fen"] == 4980
        row = _row(database, v["view_token"])
        assert row.amount_fen == 4980 and get_shop(app).fake_trades[row.out_trade_no]["amount_fen"] == 4980
        assert row.addons == ["revision"] and row.sku == "regular-p2_3"
        paid = c.post(f"/api/shop/fake/pay/{v['view_token']}", json={}).json()
        assert paid["code"].startswith("PSY-")
        with database.session() as db:
            assert db.scalar(select(Order)).paid_amount == "49.80"


def test_methods_by_user_agent(settings, notifier, tmp_path):
    """检查 11：微信里不出支付宝（也不出 Native）、手机上不出 Native；电脑上两种都有。"""
    app = make_shop_app(settings, notifier, tmp_path)
    with TestClient(app) as c:
        def methods(ua: str) -> list[str]:
            return [m["method"] for m in c.get("/api/shop/catalog", headers={"user-agent": ua}).json()["methods"]]

        assert methods(PC_UA) == ["wechat_native", "alipay_page"]
        assert methods(MOBILE_UA) == ["alipay_wap"]
        wechat = c.get("/api/shop/catalog", headers={"user-agent": WECHAT_UA}).json()
        assert wechat["methods"] == [] and "浏览器" in wechat["hint"] and wechat["ua_kind"] == "wechat"
        assert not any(m.startswith("alipay") for m in methods(WECHAT_UA))
        # 接口也拦：微信里硬要支付宝、手机上硬要 Native 都不行
        assert c.post("/api/shop/checkout", json=checkout_body(method="alipay_wap"), headers={"user-agent": WECHAT_UA}).status_code == 409
        assert c.post("/api/shop/checkout", json=checkout_body(method="wechat_native"), headers={"user-agent": MOBILE_UA}).status_code == 409
        assert c.post("/api/shop/checkout", json=checkout_body(method="alipay_wap"), headers={"user-agent": MOBILE_UA}).status_code == 200


def test_catalog_prices_come_from_settings(settings, notifier, tmp_path, database):
    from app.intake.config_store import load_config, save_config

    app = make_shop_app(settings, notifier, tmp_path)
    with TestClient(app) as c:
        cat = c.get("/api/shop/catalog", headers={"user-agent": PC_UA}).json()
        reg = next(t for t in cat["tiers"] if t["key"] == "regular")
        assert reg["prices"]["p1"] == "29.9" and cat["auto_confirm_days"] == 3 and len(cat["notices"]) == 3
        with database.session() as db:
            cfg = load_config(db)
            next(t for t in cfg.duration_tiers if t.key == "regular").prices["p1"] = "27.9"
            save_config(db, cfg)
        cat = c.get("/api/shop/catalog", headers={"user-agent": PC_UA}).json()
        assert next(t for t in cat["tiers"] if t["key"] == "regular")["prices"]["p1"] == "27.9"
        v = c.post("/api/shop/checkout", json=checkout_body(band="p1", extra_revisions=0), headers={"user-agent": PC_UA}).json()
        assert v["total_fen"] == 2790


def test_quote_rejects_closed_combinations(settings, notifier, tmp_path):
    app = make_shop_app(settings, notifier, tmp_path)
    with TestClient(app) as c:
        def q(**kw):
            return c.post("/api/shop/quote", json={"tier": "regular", "band": "p1", **kw}).json()

        assert not q(tier="light", band="p4_5")["ok"]  # 轻量不开放 4–5 篇
        assert "不能加急" in q(tier="long", rush=True)["why"]  # 长档不开加急
        assert "不能加急" in q(rush=True, find_refs=True)["why"]  # 加急不跟帮我找文献一起
        ok = q(rush=True)
        assert ok["ok"] and ok["hours"] == 3 + 2 and [a["key"] for a in ok["addons"]] == ["rush"]
        fr = q(find_refs=True)
        assert fr["ok"] and fr["hours"] == 7 + 2  # 含余量
        # 帮我找文献按 1 篇的价算，选了多篇也不叠（Edison 11-21）
        fr3 = q(band="p2_3", find_refs=True)
        assert fr3["ok"] and fr3["sku"] == "regular-p1" and fr3["total"] == "39.8"
        assert not q(tier="nope")["ok"]
        r = c.post("/api/shop/checkout", json=checkout_body(tier="light", band="p4_5"), headers={"user-agent": PC_UA})
        assert r.status_code == 409


def test_notify_idempotent_and_concurrent(settings, notifier, tmp_path, database):
    """检查 5：同一笔通知来 10 次、并发 2 次，只有一单一码；通知和轮询查单同时到也只一单。"""
    app = make_shop_app(settings, notifier, tmp_path)
    with TestClient(app) as c:
        v = c.post("/api/shop/checkout", json=checkout_body(), headers={"user-agent": PC_UA}).json()
        row = _row(database, v["view_token"])
        raw = fake.simulate_pay(get_shop(app), row.out_trade_no)
        codes = set()
        for _ in range(10):
            r = c.post("/api/shop/pay/fake/notify", content=raw)
            assert r.status_code == 200 and r.text == "success"
            codes.add(c.get(f"/api/shop/checkout/{v['view_token']}").json()["code"])
        assert len(codes) == 1 and _count(database, Order) == 1 and _count(database, ActivationCode) == 1
        assert _count(database, ShopNotification) == 1

        # 并发：两个线程各开一个库会话，同时处理同一笔通知
        v2 = c.post("/api/shop/checkout", json=checkout_body(band="p1"), headers={"user-agent": PC_UA}).json()
        row2 = _row(database, v2["view_token"])
        raw2 = fake.simulate_pay(get_shop(app), row2.out_trade_no)
        ctx = shop_ctx(app)
        barrier = threading.Barrier(2)
        exits: list[str] = []
        errors: list[BaseException] = []

        def worker() -> None:
            try:
                barrier.wait()
                with app.state.db.session() as db:
                    exits.append(run_node("channel.web", NodeCall(db, ctx, "gateway:fake"), WebNotify(pay_node="pay.fake", raw=raw2)).exit)
            except BaseException as e:  # noqa: BLE001
                errors.append(e)

        ts = [threading.Thread(target=worker) for _ in range(2)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        assert not errors, errors
        assert sorted(exits) == ["exists", "ok"]
        assert _count(database, Order) == 2

        # 通知和查单同时：第三单，网关记成已付，一个线程走通知、一个走轮询查单
        v3 = c.post("/api/shop/checkout", json=checkout_body(band="p4_5"), headers={"user-agent": PC_UA}).json()
        row3 = _row(database, v3["view_token"])
        raw3 = fake.simulate_pay(get_shop(app), row3.out_trade_no)
        barrier2 = threading.Barrier(2)

        def by_notify() -> None:
            barrier2.wait()
            with app.state.db.session() as db:
                run_node("channel.web", NodeCall(db, ctx, "gateway:fake"), WebNotify(pay_node="pay.fake", raw=raw3))

        def by_poll() -> None:
            barrier2.wait()
            with app.state.db.session() as db:
                from app.shop.models_io import WebPoll

                run_node("channel.web", NodeCall(db, ctx, "customer"), WebPoll(view_token=v3["view_token"]))

        ts = [threading.Thread(target=by_notify), threading.Thread(target=by_poll)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        assert _count(database, Order) == 3 and _count(database, ActivationCode) == 3
        assert c.get(f"/api/shop/checkout/{v3['view_token']}").json()["code"]


def test_lost_notify_recovered_by_poll(settings, notifier, tmp_path, database):
    app = make_shop_app(settings, notifier, tmp_path, SHOP_QUERY_MIN_INTERVAL_SEC=0)
    with TestClient(app) as c:
        v = c.post("/api/shop/checkout", json=checkout_body(), headers={"user-agent": PC_UA}).json()
        got = c.post(f"/api/shop/fake/pay/{v['view_token']}", json={"drop_notify": True}).json()
        assert got["status"] == "paid" and got["code"]  # 轮询时去网关查单补上
        assert _count(database, Order) == 1


def test_expired_checkout_closed_and_late_payment_still_creates(settings, notifier, tmp_path, database):
    app = make_shop_app(settings, notifier, tmp_path)
    with TestClient(app) as c:
        v = c.post("/api/shop/checkout", json=checkout_body(), headers={"user-agent": PC_UA}).json()
        row = _row(database, v["view_token"])
        ctx = shop_ctx(app)
        later = utcnow() + timedelta(minutes=31)
        with app.state.db.session() as db:
            r = run_node("channel.web", NodeCall(db, ctx, "system:sweep"), WebSweep(now=later))
            assert r.output.swept["closed"] == 1
        got = c.get(f"/api/shop/checkout/{v['view_token']}").json()
        assert got["status"] == "closed" and "过期" in got["message"] and got["pay"]["payload"] == {}
        # 关单后才到的付款通知：钱到了算数，照样建单
        get_shop(app).fake_trades[row.out_trade_no]["status"] = "NOTPAY"
        raw = fake.simulate_pay(get_shop(app), row.out_trade_no)
        assert c.post("/api/shop/pay/fake/notify", content=raw).status_code == 200
        got = c.get(f"/api/shop/checkout/{v['view_token']}").json()
        assert got["status"] == "paid" and got["code"]


def test_rate_limit_and_disabled(settings, notifier, tmp_path):
    app = make_shop_app(settings, notifier, tmp_path, SHOP_IP_HOURLY_LIMIT=2)
    with TestClient(app) as c:
        for _ in range(2):
            assert c.post("/api/shop/checkout", json=checkout_body(), headers={"user-agent": PC_UA}).status_code == 200
        assert c.post("/api/shop/checkout", json=checkout_body(), headers={"user-agent": PC_UA}).status_code == 429
    app2 = make_shop_app(settings, notifier, tmp_path / "x", SHOP_ENABLED=False)
    with TestClient(app2) as c:
        assert not c.get("/api/shop/catalog", headers={"user-agent": PC_UA}).json()["enabled"]
        r = c.post("/api/shop/checkout", json=checkout_body(), headers={"user-agent": PC_UA})
        assert r.status_code == 409 and "暂停" in r.json()["detail"]
        assert c.get("/api/shop/checkout/nonexistent-token-123").status_code == 404
        assert c.post("/api/shop/fake/pay/whatever-token", json={}).status_code == 404


def test_fake_gateway_refused_in_prod(settings, notifier, tmp_path):
    app = make_shop_app(settings, notifier, tmp_path)
    app.state.settings = settings.model_copy(update={"APP_ENV": "prod"})

    async def enter() -> None:
        async with lifespan(app):
            pass

    with pytest.raises(RuntimeError, match="SHOP_FAKE_PAY"):
        asyncio.run(enter())
    get_runtime(app)  # 不影响别的模块


def test_checkout_pages_not_cached(settings, notifier, tmp_path):
    app = make_shop_app(settings, notifier, tmp_path)
    with TestClient(app) as c:
        v = c.post("/api/shop/checkout", json=checkout_body(), headers={"user-agent": PC_UA})
        assert v.headers["cache-control"] == "no-store"
        assert c.get(f"/api/shop/checkout/{v.json()['view_token']}").headers["cache-control"] == "no-store"
