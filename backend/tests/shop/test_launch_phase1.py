"""第一阶段上线（11-19）：下单前三项同意后端必过、自有网页暂不收款时引导去平台、生产拦假网关、
平台单在需求确认卡上勾同意、没勾过的不许代确认。"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.events import Event
from app.shop.models import ShopCheckout
from app.shop.router import lifespan
from tests.conftest import TEST_PASSWORD
from tests.intake.helpers import CONSENTS
from tests.shop.helpers import PC_UA, checkout_body, make_shop_app


def _events(database, type_: str, subject: str | None = None) -> list[Event]:
    with database.session() as db:
        q = select(Event).where(Event.type == type_)
        if subject is not None:
            q = q.where(Event.subject == subject)
        rows = list(db.scalars(q))
        db.expunge_all()
        return rows


def _checkouts(database) -> int:
    with database.session() as db:
        return db.scalar(select(func.count()).select_from(ShopCheckout)) or 0


def test_checkout_refused_without_all_three_consents(settings, notifier, tmp_path, database):
    """没勾全不建单（后端拦，不靠前端）：缺哪项都 422，库里没有付款单、没有同意记录；勾全了建单并留痕（同一个事务）。"""
    app = make_shop_app(settings, notifier, tmp_path)
    with TestClient(app) as c:
        for items in ([], ["terms_privacy", "custom_no_refund"], ["terms_privacy", "ai_processing"]):
            r = c.post("/api/shop/checkout", json={**checkout_body(), "consents": items}, headers={"user-agent": PC_UA})
            assert r.status_code == 422, items
            assert "没勾全" in r.json()["detail"]
        r = c.post("/api/shop/checkout", json={**checkout_body(), "terms_version": "最新"}, headers={"user-agent": PC_UA})
        assert r.status_code == 422
        r = c.post("/api/shop/checkout", json={**checkout_body(), "terms_version": ""}, headers={"user-agent": PC_UA})
        assert r.status_code == 422 and "版本" in r.json()["detail"]
        assert _checkouts(database) == 0 and _events(database, "website.consent") == []

        v = c.post("/api/shop/checkout", json=checkout_body(), headers={"user-agent": PC_UA}).json()
        got = _events(database, "website.consent", f"checkout:{v['view_token']}")
        assert len(got) == 1 and got[0].content["items"] == sorted(CONSENTS["consents"])
        assert got[0].content["terms_version"] == "2026-11-18" and got[0].content["where"] == "checkout"
        # 付了：同意抄一份到订单上（需求确认卡不再要勾，后台代确认也认）
        paid = c.post(f"/api/shop/fake/pay/{v['view_token']}", json={}).json()
        assert paid["code"]
        with database.session() as db:
            oid = db.scalar(select(ShopCheckout.order_id).where(ShopCheckout.view_token == v["view_token"]))
        assert len(_events(database, "website.consent", f"order:{oid}")) == 1


def test_no_real_gateway_means_platform_mode(settings, notifier, tmp_path):
    """商户号没下来（SHOP_METHODS 空、或配了但缺项）：下单页照常看价、报价，「去付款」换成去小红书 / 闲鱼下单；建单 409。"""
    app = make_shop_app(settings, notifier, tmp_path, SHOP_METHODS="", SHOP_FAKE_PAY=False)
    with TestClient(app) as c:
        cat = c.get("/api/shop/catalog", headers={"user-agent": PC_UA}).json()
        assert cat["pay_mode"] == "platforms" and cat["methods"] == []
        assert cat["hint"] == "现在请在小红书或闲鱼下单，付款后会收到兑换码"
        assert "小红书或闲鱼付款后" in cat["notices"][-1] and cat["tiers"]
        assert c.post("/api/shop/quote", json={"tier": "regular", "band": "p1"}).json()["ok"] is True
        assert c.post("/api/shop/checkout", json=checkout_body(), headers={"user-agent": PC_UA}).status_code == 409

    # 方法里写了假网关但 SHOP_FAKE_PAY 关着：一样当没开（不出假网关）
    app = make_shop_app(settings, notifier, tmp_path / "b", SHOP_FAKE_PAY=False)
    with TestClient(app) as c:
        assert c.get("/api/shop/catalog", headers={"user-agent": PC_UA}).json()["pay_mode"] == "platforms"

    app = make_shop_app(settings, notifier, tmp_path / "c")  # 本机走查：假网关开着 = online
    with TestClient(app) as c:
        cat = c.get("/api/shop/catalog", headers={"user-agent": PC_UA}).json()
        assert cat["pay_mode"] == "online" and cat["methods"]


@pytest.mark.parametrize("over, match", [
    ({}, "SHOP_FAKE_PAY"),  # 假网关开关开着
    ({"SHOP_FAKE_PAY": False}, "SHOP_METHODS 里有 pay.fake"),  # 开关关着，方法里还写着假网关
])
def test_prod_refuses_any_fake_gateway(settings, notifier, tmp_path, over, match):
    app = make_shop_app(settings, notifier, tmp_path, **over)
    app.state.settings = settings.model_copy(update={"APP_ENV": "prod"})

    async def enter() -> None:
        async with lifespan(app):
            pass

    with pytest.raises(RuntimeError, match=match):
        asyncio.run(enter())


def test_prod_with_empty_methods_starts_in_platform_mode(settings, notifier, tmp_path):
    app = make_shop_app(settings, notifier, tmp_path, SHOP_METHODS="", SHOP_FAKE_PAY=False)
    app.state.settings = settings.model_copy(update={"APP_ENV": "prod"})

    async def enter() -> None:
        async with lifespan(app):
            pass

    asyncio.run(enter())  # 不报错


def _platform_order(app, c: TestClient) -> tuple[int, str]:
    """后台录一单（码池里的码）→ 客人在兑换页认领 → （订单号，需求卡令牌）。平台单下单时没有勾同意。"""
    from app.intake import codes
    from app.intake.models import ActivationCode, Order
    from app.intake.runtime import get_runtime

    rt = get_runtime(app)
    with rt.database.session() as db:
        _, rows = codes.generate_batch(db, sku="regular-p1", count=1, platform="xianyu")
        code = rows[0].code
    claimed = c.post(f"/api/channels/redeem/{code}/web", json={}).json()
    with rt.database.session() as db:
        o = db.get(Order, db.scalar(select(ActivationCode.order_id).where(ActivationCode.code == code)))
        return o.id, o.delivery_token if claimed["brief_path"] else ""


def test_platform_order_consents_on_brief_and_proxy_needs_it(settings, notifier, tmp_path, database):
    """平台单：确认卡上要勾三项（consent_needed），没勾 422；勾了确认成、留痕挂在订单上。
    没勾过同意的单，后台代确认 409（出境要本人单独同意）。"""
    app = make_shop_app(settings, notifier, tmp_path)
    with TestClient(app) as c:
        oid, token = _platform_order(app, c)
        assert token
        v = c.get(f"/api/channels/brief/{token}").json()
        assert v["consent_needed"] is True
        answers = {q["key"]: {"choice": "__default__"} for q in v["settings"]["questions"]}
        v = c.put(f"/api/channels/brief/{token}", json={"answers": answers}).json()
        assert c.post("/api/auth/login", json={"password": TEST_PASSWORD}).status_code == 200
        r = c.post(f"/api/admin/brief/orders/{oid}/confirm", json={"note": "客人在聊天里说可以"})
        assert r.status_code == 409 and "本人单独同意" in r.json()["detail"]
        r = c.post(f"/api/channels/brief/{token}/confirm", json={"version": v["version"]})
        assert r.status_code == 422
        v = c.post(f"/api/channels/brief/{token}/confirm", json={"version": v["version"], **CONSENTS}).json()
        assert v["state"] == "confirmed" and v["consent_needed"] is False
        got = _events(database, "website.consent", f"order:{oid}")
        assert len(got) == 1 and got[0].content["where"] == "brief" and got[0].content["by"] == "customer"


def test_web_order_brief_needs_no_second_consent(settings, notifier, tmp_path, database):
    """自有网页单：下单时勾过（付款后抄到订单上），确认卡不再放勾选，直接点「对，开工」。"""
    from app.intake.models import ActivationCode, Order

    app = make_shop_app(settings, notifier, tmp_path)
    with TestClient(app) as c:
        v = c.post("/api/shop/checkout", json=checkout_body(band="p1", extra_revisions=0), headers={"user-agent": PC_UA}).json()
        code = c.post(f"/api/shop/fake/pay/{v['view_token']}", json={}).json()["code"]
        c.post(f"/api/channels/redeem/{code}/web", json={})
        with database.session() as db:
            oid = db.scalar(select(ActivationCode.order_id).where(ActivationCode.code == code))
            token = db.get(Order, oid).delivery_token
        b = c.get(f"/api/channels/brief/{token}").json()
        assert b["consent_needed"] is False
        answers = {q["key"]: {"choice": "__default__"} for q in b["settings"]["questions"]}
        b = c.put(f"/api/channels/brief/{token}", json={"answers": answers}).json()
        b = c.post(f"/api/channels/brief/{token}/confirm", json={"version": b["version"]}).json()
        assert b["state"] == "confirmed"
