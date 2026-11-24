"""customer.memory：合并规则（C9）、偏好和两份摘要、给某单发话选哪个门、事件消费。"""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.channels import memory
from app.channels.models import Person
from app.core.db import utcnow
from app.core.events import Event
from app.core.nodes import NodeCall, run_node
from app.intake import flow, handoff, orders, service
from app.intake.models import Customer, Order
from app.intake.runtime import get_runtime
from tests.channels.entry_helpers import entry_app, pool_code


def _call(db, ctx):
    flow.ensure_nodes()
    return NodeCall(db, ctx, "customer")


def _claim(db, ctx, c, code):
    return run_node("order.claim", _call(db, ctx), {"customer_id": c.id, "code": code, "channel": c.channel})


def _link(db, ctx, c, code):
    return run_node("customer.memory", _call(db, ctx), {"action": "link", "session_id": c.id, "code": code})


def test_merge_rules(tmp_path, notifier, settings):
    app = entry_app(settings, notifier, tmp_path)
    with TestClient(app):
        rt = get_runtime(app)
        with rt.database.session() as db:
            ctx = rt.ctx
            web = service.get_or_create_customer(db, "web", "key-merge-web-0123456789")
            code = pool_code(db)
            assert _claim(db, ctx, web, code).exit == "ok"
            assert _link(db, ctx, web, code).exit == "linked"
            p = web.person_id
            # 规则 1：同一枚码从微信进来，码的主人还没有微信门 → 微信门并进这个人
            wx = service.get_or_create_customer(db, "wecom", "wm_merge")
            r = _link(db, ctx, wx, code)
            assert r.exit == "merged" and wx.person_id == web.person_id == p
            assert service.current_order(db, wx) is not None  # 微信会话也看得到网页认领的单（按人算）
            # 再并一次 = noop
            assert _link(db, ctx, wx, code).exit == "noop"
            # 规则 2：主人已经有微信门了，另一个微信拿着码来 → 拒绝
            wx2 = service.get_or_create_customer(db, "wecom", "wm_other")
            r = _link(db, ctx, wx2, code)
            assert r.exit == "refused" and wx2.person_id != p
            # 规则 1 后半 + 规则 3：Q（自己认领过别的码、有自己的人）拿着 P 的码进来 → Q 整个并进来，保留较早的 id
            q_web = service.get_or_create_customer(db, "web", "key-merge-q-0123456789")
            code_q = pool_code(db)
            _claim(db, ctx, q_web, code_q)
            _link(db, ctx, q_web, code_q)
            q = q_web.person_id
            assert q != p
            code_p2 = pool_code(db)
            owner2 = service.get_or_create_customer(db, "wecom", "wm_owner2")
            _claim(db, ctx, owner2, code_p2)
            _link(db, ctx, owner2, code_p2)
            p2 = owner2.person_id
            r = _link(db, ctx, q_web, code_p2)
            assert r.exit == "merged"
            keep = min(p2, q)
            assert q_web.person_id == owner2.person_id == keep
            dropped = db.get(Person, max(p2, q))
            assert dropped.merged_into_id == keep
            assert db.scalar(select(func.count()).select_from(Event).where(Event.type == "customer.merged")) == 2


def test_briefs_and_pick_session(tmp_path, notifier, settings):
    app = entry_app(settings, notifier, tmp_path)
    with TestClient(app):
        rt = get_runtime(app)
        with rt.database.session() as db:
            from tests.intake.helpers import claimed

            c, o = claimed(db, rt.ctx, name="回头客")
            o.school, o.title, o.duration_min, o.occasion = "华东师范大学", "依恋与社交焦虑", 15, "组会文献"
            o.requirement_quotes = ["组里要求每页都写出处", "结论页要有一句话总结"]
            o.stage = "delivered"
            o.finished_at = utcnow() - timedelta(days=10)
            prefs = run_node("customer.memory", _call(db, rt.ctx), {"action": "refresh", "session_id": c.id}).output.preferences
            assert prefs["school"] == "华东师范大学" and prefs["last_orders"][0]["title"] == "依恋与社交焦虑"
            assert "华东师范大学" in c.memory_brief and "组里要求每页都写出处" in c.memory_brief
            assert c.handoff_brief.startswith("老客户") and "不自动套" not in c.handoff_brief  # 没有模板就不提模板
            # 第二单开单说明里带上次的偏好（订单中枢 handoff.render_requirements 读 customer.handoff_brief）
            code2 = pool_code(db)
            assert _claim(db, rt.ctx, c, code2).exit == "ok"
            o2 = service.current_order(db, c)
            text = handoff.render_requirements(o2, [], "常规 · 1 篇", c.handoff_brief)
            assert "老客户" in text and "依恋与社交焦虑" in text
            # 给某单发话选门：微信窗口关着、又有网页门 → 发网页
            wx = service.get_or_create_customer(db, "wecom", "wm_pick")
            orders.set_customer_memory(db, wx.id, person_id=c.person_id)
            wx.last_customer_msg_at = utcnow() - timedelta(hours=60)
            c.last_customer_msg_at = utcnow() - timedelta(hours=70)
            picked = run_node("customer.memory", _call(db, rt.ctx), {"action": "pick_session", "order_id": o2.id}).output
            assert picked.session_id == c.id
            wx.last_customer_msg_at = utcnow() - timedelta(hours=1)  # 微信窗口开着 → 发微信
            picked = run_node("customer.memory", _call(db, rt.ctx), {"action": "pick_session", "order_id": o2.id}).output
            assert picked.session_id == wx.id


def test_consume_events_refreshes(tmp_path, notifier, settings):
    app = entry_app(settings, notifier, tmp_path)
    with TestClient(app):
        rt = get_runtime(app)
        with rt.database.session() as db:
            memory.consume_events(db)  # 第一次：只把游标放到现在
            from tests.intake.helpers import claimed

            c, o = claimed(db, rt.ctx, name="事件")
            assert memory.consume_events(db) == 1  # 认领事件 → 给这个人建档、刷新
            assert c.person_id is not None
            assert memory.consume_events(db) == 0  # 游标前进了
            assert db.scalar(select(func.count()).select_from(Order)) == 1 and db.get(Customer, c.id).person_id
