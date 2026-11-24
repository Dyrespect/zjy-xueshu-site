"""确认收货（E7 渠道不认的来源不算、E8 付费单不许 free）、三条岔路（平台提前确认、交付后再改、3 天自动确认 + 到期前提醒）、
时限看门（用掉 80% 提醒、超时记下、加急没做到记退加急费，每种只一次）。"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.core.db import utcnow
from app.core.events import Event
from app.core.nodes import NodeCall, run_node
from app.delivery import versions
from app.intake import orders, service
from app.intake.models import Outbox
from tests.delivery.helpers import add_package
from tests.intake.helpers import ready


def _confirm(db, ctx, o, source, by="test"):
    return run_node("confirm.receipt", NodeCall(db, ctx, by, o.id), {"order_id": o.id, "source": source})


def _deliver(db, ctx, o, pages=2, **kw):
    add_package(db, ctx, o, pages=pages, **kw)
    res = run_node("deliver.receive", NodeCall(db, ctx, "maker", o.id), {"order_id": o.id})
    assert res.exit == "ok", res.detail


def _events(db, oid, t):
    return list(db.scalars(select(Event).where(Event.type == t, Event.subject == f"order:{oid}")))


def test_e7_sources_not_on_the_list_do_nothing(database, ctx):
    with database.session() as db:
        _, x = ready(db, ctx, name="小红书客人", platform="xhs")
        _deliver(db, ctx, x)
        assert _confirm(db, ctx, x, "auto").exit == "ignored" and x.stage == "watermarked"  # 小红书不认 72 小时自动确认
        _, y = ready(db, ctx, name="闲鱼客人", platform="xy")
        _deliver(db, ctx, y)
        res = _confirm(db, ctx, y, "customer", by="customer")
        assert res.exit == "fail" and "平台" in res.detail and y.stage == "watermarked"
        assert len(_events(db, x.id, "intake.signal_ignored")) == 1


def test_e8_free_not_allowed_on_paid_flow(database, ctx, notifier):
    with database.session() as db:
        _, o = ready(db, ctx, name="付费")
        _deliver(db, ctx, o)
        res = _confirm(db, ctx, o, "free")
        assert res.exit == "fail" and "付费单不能当免费单" in res.detail and "说明" in res.detail
        assert o.stage == "watermarked" and any("免费单" in m for m in notifier.sent)


def test_branch_platform_confirmed_early_releases_right_after_publish(database, ctx):
    with database.session() as db:
        _, o = ready(db, ctx, name="抖音客人", platform="dy")
        assert o.stage == "making"
        res = _confirm(db, ctx, o, "platform", by="platform")
        assert res.exit == "recorded" and o.platform_completed_at is not None and o.stage == "making"  # 先记成事实
        _deliver(db, ctx, o)
        assert o.stage == "delivered" and o.finished_at is not None  # 发布那一步看到事实，直接放最终版
        assert versions.version_of(db, o.id, 1).status == "published"
        texts = [ob.text for ob in db.scalars(select(Outbox).where(Outbox.order_id == o.id, Outbox.kind == "text"))]
        assert not any("先给你看" in t for t in texts) and any("可编辑" in t for t in texts)


def test_branch_revise_after_delivered_releases_new_finals(database, ctx):
    with database.session() as db:
        _, o = ready(db, ctx, name="先确认后改")
        _deliver(db, ctx, o)
        assert _confirm(db, ctx, o, "customer", by="customer").exit == "completed" and o.stage == "delivered"
        assert service.revisions_left(o, service.load_config(db)) == 1  # 含的一轮还在
        res = run_node("revision.collect", NodeCall(db, ctx, "customer", o.id),
                       {"order_id": o.id, "items": [{"page": 2, "text": "图注字大一号"}], "source": "delivery"})
        assert res.exit == "ok" and o.flow_step == "revising_after"
        _deliver(db, ctx, o, pages=0, slides=2)  # 已完成之后交的：只要最终版，不要整页图
        assert o.stage == "delivered"
        v = versions.version_of(db, o.id, 2)
        assert v.status == "final" and v.published_at is not None and v.page_count == 0
        files = orders.deliverables_for_customer(db, o)
        assert {f.round for f in files} == {1, 2}  # 订单中枢给全；交付页只列最新那一版（router._final_files）


def test_branch_auto_confirm_after_72h_and_remind_once(database, ctx):
    with database.session() as db:
        _, o = ready(db, ctx, name="三天没回")
        _deliver(db, ctx, o)
        r1 = run_node("deliver.preview", NodeCall(db, ctx, "shop", o.id), {"order_id": o.id, "action": "remind"})
        r2 = run_node("deliver.preview", NodeCall(db, ctx, "shop", o.id), {"order_id": o.id, "action": "remind"})
        # 入口模块（D）的 entry.webchat 登记了就直接进对话（sent）；没登记时退回订单中枢待发（queued）
        assert r1.exit == r2.exit == "reminded" and r1.output.sent in ("queued", "sent") and r2.output.sent == "skipped"
        reminds = [ob.text for ob in db.scalars(select(Outbox).where(Outbox.order_id == o.id)) if "自动确认收货" in ob.text]
        assert len(reminds) == 1 and "/d/" in reminds[0]
        o.delivered_at = utcnow() - timedelta(hours=73)  # 模块 B 的计时器：交出 72 小时没动
        ids = orders.orders_waiting_customer(db, platforms=["fk", "web"], idle_since=utcnow() - timedelta(hours=72))
        assert o.id in ids
        assert _confirm(db, ctx, o, "auto", by="shop").exit == "completed" and o.stage == "delivered"


def _started(db, ctx, name, *, used: float, due: int = 5, rush: bool = False):
    _, o = ready(db, ctx, name=name)
    o.due_hours, o.rush = due, rush
    o.started_at = utcnow() - timedelta(hours=due * used)
    return o


def test_sla_warn_late_rush_once_each(database, ctx, notifier):
    with database.session() as db:
        w = _started(db, ctx, "快到点", used=0.85)
        late = _started(db, ctx, "超时加急", used=1.2, rush=True, due=3)
        fine = _started(db, ctx, "还早", used=0.3)
        for _ in range(2):
            out = {oid: run_node("deliver.sla", NodeCall(db, ctx, "delivery", oid), {"order_id": oid}).exit for oid in (w.id, late.id, fine.id)}
        assert out == {w.id: "warn", late.id: "late", fine.id: "ok"}
        assert len(_events(db, w.id, "delivery.sla_warned")) == 1 and len(_events(db, late.id, "delivery.late")) == 1
        assert len(_events(db, late.id, "delivery.rush_missed")) == 1
        assert late.needs_edison[-1]["type"] == "退加急费"
        assert len([m for m in notifier.sent if "时限用掉" in m]) == 1
        assert service.production_messages(db, w)[-1].text.startswith("提醒：")


def test_sla_late_publish_recorded_at_publish(database, ctx):
    with database.session() as db:
        o = _started(db, ctx, "交晚了", used=1.1, rush=True, due=3)
        _deliver(db, ctx, o)
        assert len(_events(db, o.id, "delivery.late")) == 1 and len(_events(db, o.id, "delivery.rush_missed")) == 1
        ok = _started(db, ctx, "按时", used=0.5)
        _deliver(db, ctx, ok)
        assert not _events(db, ok.id, "delivery.late")
