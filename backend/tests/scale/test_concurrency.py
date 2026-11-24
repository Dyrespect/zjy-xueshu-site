"""并发正确性（设计第九节第 3 条）：同一件事 N 个线程同时打，两种库下都只成功一次。

每个线程自己一个写会话（跟一个 POST 请求一样）：SQLite 上一开始就 BEGIN IMMEDIATE 排队，PG 上靠唯一约束 + 行锁 +
事务锁。这些测试也是 check.py 规矩 S2 盯着的，删了会失败。
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.db import Database
from app.core.nodes import NodeCall, run_node
from app.delivery.models import DeliveryVersion
from app.intake import clock, codes, orders, service
from app.intake.config_store import load_config
from app.intake.models import ActivationCode, CodeRedemption, Order
from app.intake.runtime import get_runtime
from app.invoices.models import InvoiceRequest
from app.invoices.models_io import RequestIn
from app.shop.gateways import fake
from app.shop.models import ShopCheckout, ShopNotification, ShopRefund
from app.shop.models_io import WebNotify, WebRefund
from app.shop.runtime import get_shop, shop_ctx
from tests.delivery.helpers import add_package, delivery_app
from tests.intake.helpers import PDF_BYTES, claimed, confirm_brief, make_ctx, ready
from tests.invoices.helpers import FIELDS, checkout, complete, invoice_app, web_order
from tests.scale.helpers import no_errors, run_at_once

N = 8


@pytest.fixture
def db_(settings):
    d = Database(settings.DATABASE_URL)
    yield d
    d.dispose()


@pytest.fixture
def ctx(tmp_path, notifier):
    return make_ctx(tmp_path, notifier)


@pytest.fixture
def shop_env(settings, notifier, tmp_path):
    app = invoice_app(settings, notifier, tmp_path)
    with TestClient(app) as c:
        yield app, c


# ---------------------------------------------------------------- 激活码

def test_concurrent_claim_same_code_only_one_wins(db_, ctx):
    """同一枚码，N 个不同的人同时认领：只有一个认领上，认领记录只有一行。"""
    with db_.session() as db:
        _, rows = codes.generate_batch(db, sku="regular-p1", count=1, platform="fk")
        code = rows[0].code
        cids = [service.get_or_create_customer(db, "web", f"key-race-{i:02d}-0123456789").id for i in range(N)]

    def claim(cid: int):
        with db_.session() as db:
            from app.intake.models import Customer

            return orders.claim(db, ctx, db.get(Customer, cid), code, channel="web").ok

    results = no_errors(run_at_once([lambda c=c: claim(c) for c in cids]))
    assert results.count(True) == 1
    with db_.session() as db:
        assert db.scalar(select(func.count()).select_from(CodeRedemption).where(CodeRedemption.code == code)) == 1
        row = db.scalar(select(ActivationCode).where(ActivationCode.code == code))
        assert row.status == "used" and row.customer_id in cids
        assert db.scalar(select(func.count()).select_from(Order).where(Order.code_id == row.id)) == 1


def test_concurrent_redeem_same_customer_is_idempotent(db_, ctx):
    """同一个人同一枚码连点 N 次（网页和微信同时发）：都回「认领上了」，但核销只记一次、只有一单。"""
    with db_.session() as db:
        _, rows = codes.generate_batch(db, sku="regular-p1", count=1, platform="fk")
        code = rows[0].code
        cid = service.get_or_create_customer(db, "web", "key-same-0123456789").id

    def claim():
        with db_.session() as db:
            from app.intake.models import Customer

            r = orders.claim(db, ctx, db.get(Customer, cid), code, channel="web")
            return r.ok, r.order_id

    results = no_errors(run_at_once([claim] * N))
    assert all(ok for ok, _ in results) and len({oid for _, oid in results}) == 1
    with db_.session() as db:
        assert db.scalar(select(func.count()).select_from(CodeRedemption).where(CodeRedemption.code == code)) == 1


# ---------------------------------------------------------------- 支付回调建单、退款

def test_concurrent_pay_notify_creates_one_order(shop_env):
    """同一笔付款通知并发打 N 次（网关重发）：只建一单、一枚码、一条通知记录。"""
    app, c = shop_env
    token = checkout(c)
    database = get_runtime(app).database
    with database.session() as db:
        trade = db.scalar(select(ShopCheckout).where(ShopCheckout.view_token == token)).out_trade_no
    raw = fake.simulate_pay(get_shop(app), trade)

    def notify():
        with database.session() as db:
            res = run_node("channel.web", NodeCall(db, shop_ctx(app), "gateway:fake"), WebNotify(pay_node="pay.fake", raw=raw))
            return res.exit

    exits = no_errors(run_at_once([notify] * N))
    assert exits.count("ok") == 1 and set(exits) <= {"ok", "exists"}
    with database.session() as db:
        row = db.scalar(select(ShopCheckout).where(ShopCheckout.view_token == token))
        assert row.status == "paid" and row.order_id is not None
        assert db.scalar(select(func.count()).select_from(Order).where(Order.platform == "web")) == 1
        assert db.scalar(select(func.count()).select_from(ActivationCode).where(ActivationCode.platform == "web")) == 1
        assert db.scalar(select(func.count()).select_from(ShopNotification).where(ShopNotification.kind == "pay")) == 1


def test_concurrent_refund_refunds_once(shop_env):
    """同一单后台同时点 N 次全额退款：只退一次，单作废一次。"""
    app, c = shop_env
    _, oid, _ = web_order(c, app)
    database = get_runtime(app).database
    with database.session() as db:
        paid = db.scalar(select(ShopCheckout).where(ShopCheckout.order_id == oid)).paid_fen

    def refund():
        with database.session() as db:
            return run_node("channel.web", NodeCall(db, shop_ctx(app), "edison", oid),
                            WebRefund(order_id=oid, amount_fen=paid, reason="并发测试")).exit

    exits = no_errors(run_at_once([refund] * N))
    assert exits.count("ok") == 1
    with database.session() as db:
        row = db.scalar(select(ShopCheckout).where(ShopCheckout.order_id == oid))
        assert row.refunded_fen == paid and row.status == "refunded"
        assert db.scalar(select(func.count()).select_from(ShopRefund).where(ShopRefund.order_id == oid)) == 1
        assert db.get(Order, oid).stage == "void"


# ---------------------------------------------------------------- 发票

def test_concurrent_invoice_request_one_active(shop_env):
    """同一单同时提交 N 次发票申请：只有一张在办。"""
    app, c = shop_env
    _, oid, _ = web_order(c, app)
    complete(app, oid)
    rt = get_runtime(app)

    def apply():
        with rt.database.session() as db:
            return run_node("invoice.request", NodeCall(db, rt.ctx, "customer"),
                            RequestIn(source="delivery", order_id=oid, fields=FIELDS, confirmed=True)).exit

    exits = no_errors(run_at_once([apply] * N))
    assert len([e for e in exits if e != "exists"]) == 1, exits
    with rt.database.session() as db:
        assert db.scalar(select(func.count()).select_from(InvoiceRequest).where(InvoiceRequest.active_order_id == oid)) == 1


# ---------------------------------------------------------------- 版次

def test_concurrent_package_receive_one_version(settings, notifier, tmp_path):
    """制作方同一版成品包连交 N 次（网络重试）：只收一次、只有一个版次。"""
    app = delivery_app(settings, notifier, tmp_path)
    with TestClient(app):
        rt = get_runtime(app)
        with rt.database.session() as db:
            _, o = ready(db, rt.ctx, name="版次", sku="light-p1", minutes=12)
            add_package(db, rt.ctx, o, pages=2)
            oid = o.id

        def receive():
            with rt.database.session() as db:
                return run_node("deliver.receive", NodeCall(db, rt.ctx, "maker", oid), {"order_id": oid}).exit

        exits = no_errors(run_at_once([receive] * N))
        assert exits.count("ok") == 1, exits
        with rt.database.session() as db:
            rounds = db.scalars(select(DeliveryVersion.round).where(DeliveryVersion.order_id == oid)).all()
            assert rounds == [1]


# ---------------------------------------------------------------- 名额

def test_concurrent_scheduling_never_exceeds_daily_quota(db_, ctx):
    """N 单同时资料齐、同时排期：每天开工的单不超过名额（默认每天 3 单）。"""
    with db_.session() as db:
        quota = load_config(db).daily_quota
        ids = []
        for i in range(N):
            c, o = claimed(db, ctx, name=f"名额{i}")
            service.receive_text(db, ctx, c, "组会汇报，讲 15 分钟")
            _, f = service.receive_file(db, ctx, c, filename="paper.pdf", data=PDF_BYTES)
            f.purpose = "论文"
            service.update_order(db, ctx, o, {"occasion": "组会文献", "duration_min": 15})
            confirm_brief(db, ctx, o)  # 09 需求引导：需求卡确认了才排期
            ids.append(o.id)

    def make_ready(oid: int):
        with db_.session() as db:
            o = db.get(Order, oid)
            service.update_order(db, ctx, o, {"present_date": clock.today() + timedelta(days=20)})
            return o.start_date

    no_errors(run_at_once([lambda i=i: make_ready(i) for i in ids]))
    with db_.session() as db:
        per_day = dict(db.execute(select(Order.start_date, func.count()).where(Order.id.in_(ids), Order.queued_at.is_not(None))
                                  .group_by(Order.start_date)).all())
    assert sum(per_day.values()) == N
    assert max(per_day.values()) <= quota, per_day
