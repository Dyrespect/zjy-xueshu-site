"""不加急的单，第一版水印版最早在「加急承诺时长」之后才发（Edison 11-19；docs/任务单/12_接待机器人_设计.md 第十五节；check.py 规矩 25）。

- 不加急、档位卖加急：做完了先压着（停在「把水印版发布给客人」），不发链接；版本表记几点自动发；
- 到点后台圈自动发；没到点圈里不动；
- 负责人在后台订单卡看得到「几点自动发」，点「现在就发」立刻发；
- 加急单、改稿后的版本、档位不卖加急的单：不压；
- 对客说的时限 = 正常用时 + 余量（promised_hours），余量改成 0 就是正常用时。
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.db import utcnow
from app.delivery import release, runtime, versions
from app.delivery.tick import release_due
from app.intake import pricing, service
from app.intake.config_store import BizConfig, DEFAULT_CONFIG, load_config, save_config
from app.intake.models import Order, Outbox
from app.intake.runtime import IntakeRuntime, get_runtime
from tests.conftest import TEST_PASSWORD
from tests.delivery.helpers import delivery_app
from tests.intake.helpers import package, ready

CFG = BizConfig.model_validate(DEFAULT_CONFIG)


@pytest.fixture(autouse=True)
def _hold_on(monkeypatch):
    monkeypatch.setenv("DELIVERY_HOLD_STANDARD", "true")
    runtime.reset()
    yield
    runtime.reset()


def _links(db, oid: int) -> list[Outbox]:
    return list(db.scalars(select(Outbox).where(Outbox.order_id == oid, Outbox.category == "交付")))


def test_promised_hours_are_normal_plus_buffer():
    t = CFG.tier("regular")
    assert pricing.promised_hours(CFG, t) == t.std_hours + 2
    assert pricing.promised_hours(CFG, t, rush=True) == t.rush_hours + 2
    assert pricing.promised_hours(CFG, t, find_refs=True) == t.std_hours + CFG.find_refs_extra_hours + 2
    zero = CFG.model_copy(update={"promise_buffer_hours": 0})
    assert pricing.promised_hours(zero, t) == t.std_hours
    cat = pricing.catalog(CFG)
    reg = next(x for x in cat["tiers"] if x["key"] == "regular")
    assert (reg["std_hours"], reg["rush_hours"]) == (t.std_hours + 2, t.rush_hours + 2)  # 对外说明也含余量
    assert f"开工后 {t.std_hours + 2} 小时内交水印版" in pricing.terms_head(CFG, pricing.quote(CFG, minutes=20, papers=1))


def test_standard_order_waits_until_rush_promise_then_auto_publishes(database, ctx, settings, notifier, tmp_path):
    with database.session() as db:
        c, o = ready(db, ctx, name="压着")
        assert o.stage == "making" and not o.rush and o.started_at is not None
        oid = o.id
        package(db, ctx, o, hold=True)
        v = versions.version_of(db, o.id, 1)
        t = load_config(db).tier(o.tier_key)
        want = o.started_at + timedelta(hours=pricing.promised_hours(load_config(db), t, rush=True))
        assert o.flow_step == "publish" and o.delivery_round == 0 and v.status == "ready"
        assert abs((v.release_at - want).total_seconds()) < 2
        assert release.waiting(db, o) == v.release_at and _links(db, o.id) == []  # 压着：没发链接
    rt = IntakeRuntime(ctx, None, database)
    assert release_due(rt) == 0  # 没到点圈里不动
    with database.session() as db:
        v = versions.version_of(db, oid, 1)
        v.release_at = utcnow() - timedelta(seconds=1)  # 到点了
    assert release_due(rt) == 1
    with database.session() as db:
        o = db.get(Order, oid)
        assert o.stage == "watermarked" and o.delivery_round == 1 and len(_links(db, oid)) == 1


def test_rush_order_and_revisions_and_no_rush_tier_not_held(database, ctx):
    with database.session() as db:
        _, o = ready(db, ctx, name="加急", addons=["rush"])
        assert o.rush
        package(db, ctx, o, hold=True)
        assert o.stage == "watermarked"  # 加急：做完就发
        _, o2 = ready(db, ctx, name="长档", sku="long-p1", minutes=30)
        package(db, ctx, o2, hold=True)
        assert o2.stage == "watermarked"  # 长档不卖加急：没有更快的能买，不压
        _, o3 = ready(db, ctx, name="改稿")
        package(db, ctx, o3)  # 第一版（测试里当场发）
        service.submit_revision(db, ctx, o3, items=[{"page": 1, "text": "图放大"}], files=[], source="bot")
        package(db, ctx, o3, hold=True)
        assert o3.delivery_round == 2  # 改稿后的版本不压


def test_admin_sees_hold_time_and_releases_now(settings, notifier, tmp_path):
    app = delivery_app(settings, notifier, tmp_path)
    with TestClient(app) as c:
        rt = get_runtime(app)
        with rt.database.session() as db:
            cu, o = ready(db, rt.ctx, name="后台发")
            package(db, rt.ctx, o, hold=True)
            oid, cid = o.id, cu.id
        assert c.post(f"/api/admin/delivery/orders/{oid}/release-now").status_code == 401
        c.post("/api/auth/login", json={"password": TEST_PASSWORD})
        detail = c.get(f"/api/admin/intake/conversations/{cid}").json()["order"]
        assert detail["hold_until"]
        r = c.post(f"/api/admin/delivery/orders/{oid}/release-now")
        assert r.status_code == 200 and r.json()["published"] is True
        assert c.get(f"/api/admin/intake/conversations/{cid}").json()["order"]["hold_until"] is None
        assert c.post(f"/api/admin/delivery/orders/{oid}/release-now").status_code == 409  # 已经发了


def test_hold_switch_off_publishes_at_once(database, ctx, monkeypatch):
    monkeypatch.setenv("DELIVERY_HOLD_STANDARD", "false")
    runtime.reset()
    with database.session() as db:
        _, o = ready(db, ctx, name="关了")
        package(db, ctx, o, hold=True)
        assert o.stage == "watermarked"


def test_buffer_setting_changes_every_customer_facing_number(database, ctx):
    with database.session() as db:
        cfg = load_config(db)
        cfg.promise_buffer_hours = 3
        save_config(db, cfg)
        q = pricing.quote(load_config(db), minutes=20, papers=1)
        assert q.hours == cfg.tier("regular").std_hours + 3
