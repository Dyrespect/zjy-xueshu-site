"""计数、分位数、页面访问、小时聚合、清理、/api/ops/metrics。"""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.ops import retention, stats, store
from app.ops.config import OpsConfig
from app.ops.models import OpsError, OpsHourly, OpsSample, OpsVisitor
from app.ops.runtime import get_ops
from tests.conftest import make_settings
from tests.ops.helpers import UA, login, ops_app


def test_percentile_from_buckets():
    hist = stats.new_hist()
    for ms in [5] * 50 + [30] * 45 + [700] * 5:
        hist[stats.bucket_index(ms)] += 1
    assert stats.percentile(hist, 0.5) <= 10
    assert 25 <= stats.percentile(hist, 0.95) <= 50
    assert 400 <= stats.percentile(hist, 0.99) <= 800
    assert stats.percentile(stats.new_hist(), 0.5) is None


def test_requests_counted_flushed_and_summarised(settings, notifier):
    app = ops_app(settings, notifier)
    with TestClient(app, raise_server_exceptions=False) as c:
        for _ in range(95):
            assert c.get("/api/_ok").status_code == 200
        for _ in range(5):
            assert c.get("/api/_boom").status_code == 500
        r = c.get("/api/_ok", headers={"x-request-id": "my-request-0001"})
        assert r.headers["x-request-id"] == "my-request-0001"  # 带来的请求号沿用
        assert len(c.get("/health").headers["x-request-id"]) == 16  # 没带就生成
        ctx = get_ops(app)
        now = ctx.now() + timedelta(minutes=1)
        with ctx.database.session() as db:
            res = store.flush(db, ctx.collector, now=now)
        assert res["samples"] >= 2 and res["errors"] == 5
        with ctx.database.session() as db:
            rows = {r["route"]: r for r in stats.route_table(db, now - timedelta(hours=1), now + timedelta(minutes=1), limit=50)}
            assert rows["/api/_ok"]["n"] == 96 and rows["/api/_ok"]["errors_5xx"] == 0
            assert rows["/api/_boom"]["n"] == 5 and rows["/api/_boom"]["errors_5xx"] == 5
            assert rows["/api/_ok"]["p95_ms"] is not None
            assert "/health" not in rows  # 健康检查不算进请求量
            errs = list(db.scalars(select(OpsError)))
            assert len(errs) == 5 and errs[0].route == "/api/_boom" and errs[0].kind == "RuntimeError"
            assert "13812345678" not in errs[0].message  # 错误摘要已脱敏
            # 再落一次：没有新请求就没有新数（取的是差值，不会重复算）
            store.flush(db, ctx.collector, now=now + timedelta(minutes=1))
            again = {r["route"]: r for r in stats.route_table(db, now - timedelta(hours=1), now + timedelta(minutes=3), limit=50)}
            assert again["/api/_ok"]["n"] == 96


def test_page_views_and_visitors(tmp_path, notifier):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>t</title>", encoding="utf-8")
    s = make_settings(tmp_path, FRONTEND_DIST=dist)
    from app.core.migrate import upgrade_to_heads

    upgrade_to_heads(s.DATABASE_URL)
    app = ops_app(s, notifier)
    html = {"accept": "text/html", "user-agent": UA}
    with TestClient(app) as c:
        c.get("/order", headers=html)
        c.get("/order", headers=html)  # 同一个人：pv 2、uv 1
        c.get("/figures", headers={**html, "user-agent": UA + " other"})
        c.get("/admin/ops", headers=html)  # 后台不算
        c.get("/order", headers={"accept": "text/html", "user-agent": "Googlebot/2.1"})  # 爬虫不算
        c.get("/order", headers={"accept": "application/json", "user-agent": UA})  # 不是整页不算
        ctx = get_ops(app)
        now = ctx.now() + timedelta(minutes=1)
        with ctx.database.session() as db:
            store.flush(db, ctx.collector, now=now)
        with ctx.database.session() as db:
            p = stats.pages(db, now - timedelta(hours=1), now + timedelta(minutes=1))
            assert p["by_page"] == {"下单页": 2, "图库": 1} and p["uv"] == 2
            vh = db.scalar(select(OpsVisitor.vh))
            assert len(vh) == 16 and "testclient" not in vh  # 只存散列，不存 IP


def test_rollup_then_purge_keeps_totals(settings, notifier):
    app = ops_app(settings, notifier)
    with TestClient(app):
        ctx = get_ops(app)
        now = ctx.now().replace(minute=30, second=0, microsecond=0)
        old = now - timedelta(days=40)
        with ctx.database.session() as db:
            for i in range(120):  # 两小时、每分钟一格
                db.add(OpsSample(minute=old + timedelta(minutes=i), kind="http", key="/api/x", dim="GET 2xx", n=2, total=40.0, max=30.0,
                                 hist=[2] + [0] * 10))
            db.add(OpsSample(minute=now - timedelta(minutes=5), kind="http", key="/api/x", dim="GET 2xx", n=1, total=10.0, max=10.0,
                             hist=[1] + [0] * 10))
        with ctx.database.session() as db:
            out = retention.purge(db, OpsConfig(), now=now, tzname="Asia/Shanghai")
        assert out["ops_samples"] == 120
        with ctx.database.session() as db:
            assert db.scalar(select(func.sum(OpsHourly.n)).where(OpsHourly.hour < now - timedelta(days=30))) == 240
            assert db.scalar(select(func.count()).select_from(OpsSample)) == 1  # 近的原始行还在
            s = stats.http_summary(db, old - timedelta(hours=1), now)  # 跨 30 天：老的读小时表、新的读原始表
            assert s["requests"] == 241


def test_metrics_endpoint_needs_token(settings, notifier):
    app = ops_app(settings, notifier)
    with TestClient(app) as c:
        c.get("/api/_ok")
        assert c.get("/api/ops/metrics").status_code == 404  # 没配令牌 = 关着
    app2 = ops_app(settings, notifier, OPS_METRICS_TOKEN="t" * 32)
    with TestClient(app2) as c:
        c.get("/api/_ok")
        assert c.get("/api/ops/metrics", headers={"authorization": "Bearer wrong"}).status_code == 404
        r = c.get("/api/ops/metrics", headers={"authorization": "Bearer " + "t" * 32})
        assert r.status_code == 200 and 'psyppt_http_request_duration_seconds_bucket{le="0.01",method="GET",route="/api/_ok"' in r.text


def test_overview_today_and_week(settings, notifier):
    app = ops_app(settings, notifier)
    with TestClient(app, raise_server_exceptions=False) as c:
        login(c)
        for _ in range(9):
            c.get("/api/_ok")
        c.get("/api/_boom")
        ctx = get_ops(app)
        ctx.now_fn = lambda: __import__("datetime").datetime.now(__import__("datetime").timezone.utc) + timedelta(minutes=1)
        assert c.post("/api/admin/ops/flush").status_code == 200
        body = c.get("/api/admin/ops/overview").json()
        today = body["windows"]["today"]
        assert today["http"]["errors_5xx"] == 1 and today["http"]["requests"] >= 10
        assert [f["key"] for f in today["funnel"]] == ["visit", "checkout", "paid", "claimed", "delivered", "completed", "invoice"]
        assert {g["key"] for g in body["gauges"]} >= {"watermark.rendering", "capacity.making", "pay.notify_missing"}
        assert body["sender"]["configured"] is True and "open.feishu.cn" not in str(body)
        assert [j["id"] for j in body["jobs"]][:3] == ["flush", "alerts", "rollup"]
