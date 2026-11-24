"""告警（开、去重、静默、恢复、每小时上限）、告警消息必须带后台链接、日报（第一段永远是「有没有问题」、建议不混交付页修改意见）、调度。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from app.core.events import Event, record_event
from app.core.nodes import NodeCall, run_node
from app.ops import alerts, report, scheduler
from app.ops.config import OpsConfig, jobs, load_config, save_config
from app.ops.models import OpsAlert, OpsSample
from app.ops.models_io import AlertMessage, MessageSection
from app.ops.runtime import get_ops
from tests.ops.helpers import login, ops_app


def _errors(db, now, ok: int, bad: int) -> None:
    m = now.replace(second=0, microsecond=0) - timedelta(minutes=1)
    db.add(OpsSample(minute=m, kind="http", key="/api/shop/checkout", dim="POST 2xx", n=ok, total=ok * 20.0, max=30, hist=[0, ok] + [0] * 9))
    db.add(OpsSample(minute=m, kind="http", key="/api/shop/checkout", dim="POST 5xx", n=bad, total=bad * 20.0, max=30,
                     hist=[0, bad] + [0] * 9))


def _eval(app, now):
    ctx = get_ops(app)
    ctx.now_fn = lambda: now
    with ctx.database.session() as db:
        r = run_node("ops.alert_eval", NodeCall(db, ctx, "test"), {"now": now})
    return r.output


def test_5xx_alert_opens_pushes_once_then_resolves(settings, notifier):
    app = ops_app(settings, notifier)
    with TestClient(app):
        ctx = get_ops(app)
        now = datetime.now(timezone.utc)
        with ctx.database.session() as db:
            _errors(db, now, ok=90, bad=10)
        out = _eval(app, now)
        assert out.opened == ["http_5xx"] and out.pushed == 1
        sent = notifier.sent[-1]
        assert "网站报错变多" in sent and "要立刻处理" in sent and "10 次出错" in sent
        assert "下单页、付款页" in sent and "/admin/ops?tab=errors" in sent  # 影响什么、后台链接
        n_before = len(notifier.sent)
        out = _eval(app, now + timedelta(minutes=2))  # 还在报：去重，静默期内不再推
        assert out.still_open == ["http_5xx"] and out.pushed == 0 and len(notifier.sent) == n_before
        with ctx.database.session() as db:
            a = db.scalar(select(OpsAlert).where(OpsAlert.key == "http_5xx"))
            assert a.count == 2 and a.status == "open"
        out = _eval(app, now + timedelta(minutes=15))  # 窗口里没错误了：关掉，说一声恢复了
        assert out.resolved == ["http_5xx"]
        assert "已恢复" in notifier.sent[-1]
        with ctx.database.session() as db:
            types = [e.type for e in db.scalars(select(Event).where(Event.type.like("ops.%")).order_by(Event.id))]
        assert types.count("ops.alert_opened") == 1 and "ops.alert_resolved" in types and types.count("ops.sent") == 2


def test_silence_window_then_remind_and_hourly_cap(settings, notifier):
    app = ops_app(settings, notifier)
    with TestClient(app):
        ctx = get_ops(app)
        now = datetime.now(timezone.utc)
        with ctx.database.session() as db:
            save_config(db, {"push": {"silence_minutes": {"urgent": 30, "today": 360, "info": 1440}, "max_per_hour": 1}}, by="test")
            for i in range(3):
                record_event(db, "shop.pay_invalid", f"notify:pay.fake:{i}", {"why": "验签不过"})
            _errors(db, now, ok=50, bad=50)
        out = _eval(app, now + timedelta(seconds=5))  # 两条都开：每小时只推 1 条，另一条记下来
        assert set(out.opened) == {"http_5xx", "pay_notify_invalid"} and out.pushed == 1 and out.suppressed == 1
        with ctx.database.session() as db:
            for e in db.scalars(select(Event).where(Event.type == "ops.sent")):
                e.created_at -= timedelta(hours=2)  # 假装那条是两小时前推的
            _errors(db, now + timedelta(minutes=40), ok=50, bad=50)
        out = _eval(app, now + timedelta(minutes=40))  # 过了静默期还没好：再推「还没好」，并说有几条没推
        assert out.pushed == 1
        assert "还没好" in notifier.sent[-1] or "没推" in notifier.sent[-1]


def test_alert_message_has_admin_link(settings, notifier):
    """规矩 19：告警消息必须带后台链接；规则数据里每条的 link 都是 /admin 开头。"""
    with pytest.raises(ValidationError):
        AlertMessage(kind="alert", title="x", link="https://example.com/", happened_at=datetime.now(timezone.utc),
                     sections=[MessageSection(title="")])
    assert all(r["link"].startswith("/admin") for r in OpsConfig().all_rules())
    app = ops_app(settings, notifier)
    with TestClient(app):
        ctx = get_ops(app)
        a = OpsAlert(key="disk_usage", rule="disk_usage", level="today", title="磁盘快满了", detail="用了 85%", impact="满了写不进",
                     link="/admin/ops?tab=overview", first_at=datetime.now(timezone.utc), last_at=datetime.now(timezone.utc))
        msg = alerts.build_message(ctx, a)
        text = msg.text()
        for part in ("发生了什么", "什么时候", "影响什么", "http://127.0.0.1:8710/admin/ops?tab=overview", "今天看一下"):
            assert part in text


def test_health_driven_alerts_disk_cert_external(settings, notifier):
    from tests.ops.helpers import Recorder

    rec = Recorder(down=("api.deepseek",))
    s = settings.model_copy(update={"PUBLIC_BASE_URL": "https://psyppt.example.cn", "LLM_BASE_URL": "https://api.deepseek.com"})
    app = ops_app(s, notifier, recorder=rec, cert_days=10, OPS_EXTERNAL_CHECKS=True)
    with TestClient(app, base_url="https://testserver") as c:  # 网址是 https：后台 cookie 带 Secure
        login(c)
        h = c.get("/api/admin/ops/health?external=1").json()
        by = {i["key"]: i for i in h["items"]}
        assert by["cert:psyppt.example.cn"]["status"] == "warn" and by["cert:psyppt.example.cn"]["value"] == 10
        assert by["ext:deepseek"]["status"] == "problem" and by["ext:wechatpay"]["status"] == "skipped"  # 没配的跳过
        assert by["db_write"]["status"] == "ok"
        ctx = get_ops(app)
        now = datetime.now(timezone.utc)
        with ctx.database.session() as db:
            save_config(db, {"rules": {"external_down": {"params": {"fail_times": 1, "every_minutes": 0}}}}, by="test")
        out = _eval(app, now)
        assert "cert_expiring:psyppt.example.cn" in out.opened and "external_down:deepseek" in out.opened
        assert all("api.deepseek" not in r.url.path for r in rec.requests)  # 只 HEAD 首页，不带路径、不带密钥
        assert not any("authorization" in r.headers for r in rec.requests)


def test_daily_report_always_has_problems_section(settings, notifier):
    """规矩 19：日报第一段永远是「有没有问题」，没有问题写「一切正常」。"""
    app = ops_app(settings, notifier)
    with TestClient(app):
        ctx = get_ops(app)
        with ctx.database.session() as db:
            msg, problems = report.build(db, ctx, load_config(db), report.yesterday(ctx.now(), "Asia/Shanghai"), None)
        assert problems == 0 and msg.sections[0].title == "有没有要你处理的问题"
        assert "一切正常" in msg.sections[0].lines[0].text and "一切正常" in msg.title
        assert [s.title for s in msg.sections[:6]] == ["有没有要你处理的问题", "昨天的单和需要你看一眼的", "昨天网站运行", "昨天业务数据",
                                                      "新收集的建议", "待处理事项"]
        with ctx.database.session() as db:
            db.add(OpsAlert(key="backup_failed", rule="backup_failed", level="urgent", title="备份失败或太久没备份", detail="还没成功备份过",
                            link="/admin/ops?tab=backups", first_at=ctx.now(), last_at=ctx.now()))
        with ctx.database.session() as db:
            msg, problems = report.build(db, ctx, load_config(db), report.yesterday(ctx.now(), "Asia/Shanghai"), None)
        assert problems == 1 and "有 1 件要你处理" in msg.title
        assert "备份失败" in msg.sections[0].lines[0].text and "/admin/ops?tab=backups" in msg.sections[0].lines[0].link


def test_report_suggestions_and_todo(settings, notifier):
    from app.figures.models import FigureFeedback, FigureRequest, SiteFeedback
    from app.intake.models import Customer, Order

    app = ops_app(settings, notifier)
    with TestClient(app):
        ctx = get_ops(app)
        day = report.yesterday(ctx.now(), "Asia/Shanghai")
        from app.ops.stats import local_day_bounds

        start, _ = local_day_bounds(day, "Asia/Shanghai")
        at = start + timedelta(hours=10)
        with ctx.database.session() as db:
            db.add(FigureFeedback(figure_id=12, reason="wrong_tags", note="不是中介模型", created_at=at))
            db.add(FigureRequest(want="想要一张交叉滞后模型的图，联系我 13812345678", contact="13812345678", created_at=at))
            db.add(SiteFeedback(content="搜索框太小", created_at=at))
            db.add(SiteFeedback(content="今天的不算", created_at=start + timedelta(days=1, hours=1)))
            cu = Customer(channel="web", external_id="k1")
            db.add(cu)
            db.flush()
            o = Order(delivery_token="tok-abcdefghijklmnop", customer_id=cu.id, stage="watermarked", platform="web")
            db.add(o)
            db.flush()
            record_event(db, "delivery.revision", f"order:{o.id}", {"text": "第 3 页改一下"})  # 交付页修改意见：不是建议
        with ctx.database.session() as db:
            msg, _ = report.build(db, ctx, load_config(db), day, None)
        sug = next(s for s in msg.sections if s.title == "新收集的建议")
        text = "\n".join(ln.text for ln in sug.lines)
        assert "昨天新收到 3 条" in text and "标签反馈 1" in text and "提需求 1" in text and "网站意见 1" in text
        assert "13812345678" not in text and "第 3 页" not in text and "今天的不算" not in text
        assert any("/admin/figures/requests" in ln.link for ln in sug.lines)
        todo = next(s for s in msg.sections if s.title == "待处理事项")
        assert todo.lines  # 没有待处理也写「没有待处理的。」


def test_report_node_sends_and_preview_does_not(settings, notifier):
    app = ops_app(settings, notifier)
    with TestClient(app) as c:
        login(c)
        p = c.get("/api/admin/ops/report/preview").json()
        assert p["message"]["sections"][0]["title"] == "有没有要你处理的问题" and notifier.sent == []
        r = c.post("/api/admin/ops/report/send", json={})
        assert r.status_code == 200 and notifier.sent and "【日报】" in notifier.sent[-1]


def test_scheduler_daily_and_interval_rules():
    assert OpsConfig().report.time == "21:00" and OpsConfig().push.levels == ["urgent"]  # 11-19：每晚 9 点；只推要立刻处理的
    cfg = OpsConfig()
    cfg = cfg.model_copy(update={"report": cfg.report.model_copy(update={"time": "09:00"})})  # 调度规则本身照 9 点那套测
    job = next(j for j in jobs() if j["id"] == "report")
    tz = "Asia/Shanghai"
    bj = timezone(timedelta(hours=8))
    at = lambda h, m=0, d=18: datetime(2026, 11, d, h, m, tzinfo=bj).astimezone(timezone.utc)  # noqa: E731
    assert not scheduler.is_due(job, cfg, {}, at(8, 59), tz)
    assert scheduler.is_due(job, cfg, {}, at(9, 0), tz)
    assert scheduler.is_due(job, cfg, {}, at(14, 0), tz)  # 6 小时内补跑
    assert not scheduler.is_due(job, cfg, {}, at(15, 30), tz)  # 太晚了等明天
    assert not scheduler.is_due(job, cfg, {"last_at": at(9, 1).isoformat()}, at(10), tz)  # 今天跑过
    assert scheduler.is_due(job, cfg, {"last_at": at(9, 1, 17).isoformat()}, at(9, 2), tz)
    off = cfg.model_copy(update={"report": cfg.report.model_copy(update={"enabled": False})})
    assert not scheduler.is_due(job, off, {}, at(9, 30), tz)
    drill = next(j for j in jobs() if j["id"] == "drill")
    assert not scheduler.is_due(drill, cfg, {"last_at": at(5, 1, 1).isoformat()}, at(5, 5, 18), tz)  # 30 天才一次
    assert scheduler.is_due(drill, cfg, {"last_at": at(5, 1, 1).isoformat()}, at(5, 5, 18).replace(month=12), tz)
    flush = next(j for j in jobs() if j["id"] == "flush")
    assert not scheduler.is_due(flush, cfg, {}, at(9), tz)  # 每个进程自己跑，不走单例调度
    alerts_job = next(j for j in jobs() if j["id"] == "alerts")
    assert scheduler.is_due(alerts_job, cfg, {"last_at": (at(9) - timedelta(seconds=130)).isoformat()}, at(9), tz)
    assert not scheduler.is_due(alerts_job, cfg, {"last_at": (at(9) - timedelta(seconds=30)).isoformat()}, at(9), tz)


def test_tick_runs_due_jobs_once(settings, notifier):
    app = ops_app(settings, notifier)
    with TestClient(app):
        bj = timezone(timedelta(hours=8))
        now = datetime(2026, 11, 18, 21, 1, tzinfo=bj).astimezone(timezone.utc)
        ran = scheduler.tick(app, now)
        assert "report" in ran and "alerts" in ran and "rollup" in ran
        assert any("【日报】11-18" in s for s in notifier.sent)  # 21:00 发，汇报当天
        ran2 = scheduler.tick(app, now + timedelta(seconds=40))
        assert "report" not in ran2 and "alerts" not in ran2
