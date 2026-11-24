"""entry.route 入站分流：未认领不收资料（C1）、认领幂等（C2）、访客上限（C7）、记忆不开工（C8）、确认说法。"""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.channels.entry_types import InboundMessage
from app.channels.runtime import get_channels
from app.channels.wecom import sync_messages
from app.core.events import Event
from app.core.nodes import NodeCall, run_node
from app.intake import clock, flow, service
from app.intake.config_store import load_config, save_config
from app.intake.models import CodeRedemption, Customer, FileRecord, Job, Message, Order, Outbox
from app.intake.runtime import get_runtime
from app.intake.worker import run_due_jobs
from tests.channels.entry_helpers import CountingModel, enable_wecom, entry_app, paid_code, pool_code, wecom_settings
from tests.channels.fake_wecom import KFID, FakeWecom
from tests.intake.helpers import PDF_BYTES


def _route(db, ctx, msg: InboundMessage):
    flow.ensure_nodes()
    return run_node("entry.route", NodeCall(db, ctx, "customer"), {"msg": msg})


def _web(db, name: str) -> Customer:
    return service.get_or_create_customer(db, "web", f"key-{name}-0123456789abcdef")


def test_unclaimed_file_not_fetched_or_stored(tmp_path, notifier):
    fake = FakeWecom(page_size=10)
    app = entry_app(wecom_settings(tmp_path), notifier, tmp_path, wecom=fake)
    enable_wecom(app)
    fake.customer_says("wm_new", "在吗，想问问", "m1")
    fake.customer_sends_file("wm_new", "MEDIA_PDF", "m2")
    fake.customer_sends_file("wm_new", "MEDIA_PDF", "m3")
    with TestClient(app) as c:
        rt = get_channels(app)
        c.portal.call(sync_messages, rt, KFID, "")
        assert "/media/get" not in fake.calls  # 没认领：一个文件都不下载
        with rt.intake.database.session() as db:
            assert db.scalar(select(func.count()).select_from(FileRecord)) == 0
            told = list(db.scalars(select(Outbox).where(Outbox.category == "收到文件")))
            assert len(told) == 1 and "激活码" in told[0].text  # 每个会话每天说一次，之后静默
            assert db.scalar(select(func.count()).select_from(Event).where(Event.type == "entry.file_refused")) == 2
        # 网页：上传前先问 entry.route，409 + 固定话术，存储里什么都没写
        key = c.post("/api/channels/web/sessions").json()["key"]
        r = c.post(f"/api/channels/web/{key}/files", files={"file": ("论文.pdf", PDF_BYTES, "application/pdf")})
        assert r.status_code == 409 and "激活码" in r.json()["detail"]
        files_dir = tmp_path / "data" / "files"
        assert not files_dir.exists() or not any(p.is_file() for p in files_dir.rglob("*"))


def test_claim_idempotent_and_concurrent(tmp_path, notifier, settings):
    app = entry_app(settings, notifier, tmp_path)
    with TestClient(app):
        rt = get_runtime(app)
        with rt.database.session() as db:
            code = pool_code(db)
            a, b = _web(db, "a"), _web(db, "b")
            r1 = _route(db, rt.ctx, InboundMessage(entry="entry.webchat", session_id=a.id, text=code))
            r2 = _route(db, rt.ctx, InboundMessage(entry="entry.webchat", session_id=a.id, text=f"激活码 {code}"))
            assert r1.exit == "claimed" and r1.output.claim_result == "ok"
            assert r2.exit in ("claimed", "serve")  # 同一个人再交同一枚码：不再认领
            assert db.scalar(select(func.count()).select_from(CodeRedemption)) == 1
            assert db.scalar(select(func.count()).select_from(Event).where(Event.type == "intake.order_claimed")) == 1
            claim_ok = [ob for ob in db.scalars(select(Outbox).where(Outbox.customer_id == a.id)) if ob.text.startswith("已对上")]
            assert len(claim_ok) == 1  # dedupe：认领结果只发一遍
            # 另一个浏览器抢同一枚码：认领不上，回「认领过了」
            r3 = _route(db, rt.ctx, InboundMessage(entry="entry.webchat", session_id=b.id, text=code))
            assert r3.exit == "claim_failed" and r3.output.claim_result == "used"
            last = db.scalar(select(Outbox).where(Outbox.customer_id == b.id).order_by(Outbox.id.desc()).limit(1))
            assert "认领过了" in last.text
            assert db.scalar(select(func.count()).select_from(CodeRedemption)) == 1
            # 码不对、作废
            r4 = _route(db, rt.ctx, InboundMessage(entry="entry.webchat", session_id=b.id, text="PSY-ABCDEFGHJ"))
            assert r4.exit == "claim_failed" and r4.output.claim_result == "not_found"


def test_visitor_daily_limit(tmp_path, notifier, settings, monkeypatch):
    model = CountingModel()
    app = entry_app(settings, notifier, tmp_path, model=model.model)
    with TestClient(app) as c:
        rt = get_runtime(app)
        with rt.database.session() as db:
            assert load_config(db).visitor_daily_limit == 20
            v = _web(db, "visitor")
            exits = [_route(db, rt.ctx, InboundMessage(entry="entry.webchat", session_id=v.id, text=f"问题 {i}")).exit
                     for i in range(22)]
        assert exits[:20] == ["visitor_qa"] * 20 and exits[20:] == ["visitor_limited"] * 2
        with rt.database.session() as db:
            limited = list(db.scalars(select(Outbox).where(Outbox.customer_id == v.id, Outbox.category == "访客上限")))
            assert len(limited) == 1  # 第 21 条回一次固定话，第 22 条不回
        c.portal.call(run_due_jobs, rt)
        assert model.calls == 0  # 超了上限的会话不调模型
        # 全站上限
        with rt.database.session() as db:
            cfg = load_config(db)
            cfg.visitor_global_daily_limit = 23
            save_config(db, cfg)
            w = _web(db, "w")
            assert _route(db, rt.ctx, InboundMessage(entry="entry.webchat", session_id=w.id, text="在吗")).exit == "visitor_qa"
            assert _route(db, rt.ctx, InboundMessage(entry="entry.webchat", session_id=w.id, text="在吗")).exit == "visitor_limited"
        # 第二天重新算
        tomorrow = clock.today() + timedelta(days=1)
        monkeypatch.setattr(clock, "today", lambda: tomorrow)
        with rt.database.session() as db:
            v = db.get(Customer, v.id)
            cfg = load_config(db)
            cfg.visitor_global_daily_limit = 500
            save_config(db, cfg)
            assert _route(db, rt.ctx, InboundMessage(entry="entry.webchat", session_id=v.id, text="又来问")).exit == "visitor_qa"


def test_web_visitor_ip_limit(tmp_path, notifier, settings):
    from tests.channels.entry_helpers import set_entry

    app = entry_app(settings, notifier, tmp_path)
    set_entry(app, web_visitor_ip_daily=3)
    with TestClient(app) as c:
        keys = [c.post("/api/channels/web/sessions").json()["key"] for _ in range(2)]
        for i in range(3):
            c.post(f"/api/channels/web/{keys[i % 2]}/messages", json={"text": f"问 {i}"})
        c.post(f"/api/channels/web/{keys[1]}/messages", json={"text": "第四句"})
        rt = get_runtime(app)
        with rt.database.session() as db:
            ev = [e.content["rule"] for e in db.scalars(select(Event).where(Event.type == "entry.routed").order_by(Event.id))]
        assert ev == ["visitor_qa"] * 3 + ["visitor_limited"]  # 同一 IP 一天第 4 条：换个会话也不行


def test_memory_does_not_start_work(tmp_path, notifier, settings):
    app = entry_app(settings, notifier, tmp_path)
    with TestClient(app):
        rt = get_runtime(app)
        with rt.database.session() as db:
            from tests.intake.helpers import claimed

            c, o = claimed(db, rt.ctx, name="老客户")
            o.stage = "delivered"  # 测试里直接摆成「上一单做完了」（不经引擎）
            o.finished_at = o.finished_at or service.utcnow() - timedelta(days=30)
            run_node("customer.memory", NodeCall(db, rt.ctx, "system"), {"action": "refresh", "session_id": c.id})
            n_orders = db.scalar(select(func.count()).select_from(Order))
            r = _route(db, rt.ctx, InboundMessage(entry="entry.webchat", session_id=c.id, text="照上次的再做一份"))
            assert r.exit == "visitor_qa"  # 记忆不代替付款：只问答
            assert db.scalar(select(func.count()).select_from(Order)) == n_orders
            assert db.scalar(select(func.count()).select_from(Job).where(Job.customer_id == c.id, Job.status == "pending")) == 1


def test_confirm_phrase_by_platform(tmp_path, notifier, settings):
    app = entry_app(settings, notifier, tmp_path)
    with TestClient(app):
        rt = get_runtime(app)
        with rt.database.session() as db:
            code, oid = paid_code(db, rt.ctx, platform="xhs")
            c = _web(db, "xhs")
            assert _route(db, rt.ctx, InboundMessage(entry="entry.webchat", session_id=c.id, text=code)).exit == "claimed"
            o = db.get(Order, oid)
            o.stage, o.flow_step = "watermarked", "watermarked"  # 交了水印版（测试直接摆状态）
            r = _route(db, rt.ctx, InboundMessage(entry="entry.webchat", session_id=c.id, text="确认收货。"))
            assert r.exit == "confirm" and r.output.rule == "confirm_platform"
            last = db.scalar(select(Message).where(Message.customer_id == c.id, Message.direction == "out").order_by(Message.id.desc()).limit(1))
            assert "订单里点「确认收货」" in last.text and o.stage == "watermarked"  # 平台单：叫他去平台点，订单不动
