"""网站进程无状态（设计第六节）：限流计数、登录锁、会话在几个网站进程之间是同一份。两种库都跑。

「两个进程」用同一个库上的两个 app 模拟：它们之间没有共享内存，只共享库，跟 uvicorn 多 worker、多台机器一样。
"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.auth import COOKIE_NAME
from app.core.db import Database
from app.core.migrate import upgrade_to_heads
from app.core.ratelimit import RateEvent, RateLimits, SqlStorage, prune_rate_events
from app.main import create_app
from tests.conftest import TEST_PASSWORD, make_settings
from tests.scale.helpers import no_errors, run_at_once


def test_rate_limit_shared_between_processes(settings):
    a, b = Database(settings.DATABASE_URL), Database(settings.DATABASE_URL)
    try:
        la, lb = RateLimits(SqlStorage(a)), RateLimits(SqlStorage(b))
        assert la.hit("shop.checkout", "1.2.3.4", limit=3, window=3600)
        assert lb.hit("shop.checkout", "1.2.3.4", limit=3, window=3600)
        assert la.hit("shop.checkout", "1.2.3.4", limit=3, window=3600)
        assert not lb.hit("shop.checkout", "1.2.3.4", limit=3, window=3600)  # 第 4 次，换了进程也拦
        assert lb.hit("shop.checkout", "5.6.7.8", limit=3, window=3600)  # 别的 IP 不受影响
        assert lb.hit("invoices.public", "1.2.3.4", limit=3, window=3600)  # 别的类不受影响
        assert la.used("shop.checkout", "1.2.3.4", limit=3, window=3600) == 3
        la.clear("shop.checkout", "1.2.3.4", limit=3, window=3600)
        assert lb.test("shop.checkout", "1.2.3.4", limit=3, window=3600)
    finally:
        a.dispose()
        b.dispose()


def test_rate_limit_window_slides(settings):
    d = Database(settings.DATABASE_URL)
    try:
        lim = RateLimits(SqlStorage(d))
        assert lim.hit("t", "k", limit=1, window=1)
        assert not lim.hit("t", "k", limit=1, window=1)
        time.sleep(1.1)
        assert lim.hit("t", "k", limit=1, window=1)
        assert prune_rate_events(d, keep_days=0) >= 1
    finally:
        d.dispose()


def test_rate_limit_concurrent_hits_stay_near_limit(settings):
    """20 个请求同时打、上限 5：两种库都正好放过 5 个（PG 上靠同一个 key 的事务锁；不加锁实测会放过 13 个）。"""
    d = Database(settings.DATABASE_URL)
    try:
        lim = RateLimits(SqlStorage(d))
        ok = no_errors(run_at_once([lambda: lim.hit("burst", "ip", limit=5, window=60)] * 20))
        n = ok.count(True)
        assert n == 5, n
        with d.session() as db:
            assert db.scalar(select(func.count()).select_from(RateEvent)) == n
    finally:
        d.dispose()


def test_login_lockout_counts_across_web_processes(tmp_path, notifier):
    """同一 IP 在 A 进程错 3 次、B 进程错 2 次：两个进程都锁上（原来各数各的，开 4 个进程等于能试 20 次）。"""
    s = make_settings(tmp_path)
    upgrade_to_heads(s.DATABASE_URL)
    a, b = create_app(s, notifier=notifier), create_app(s, notifier=notifier)
    with TestClient(a) as ca, TestClient(b) as cb:
        for c in (ca, ca, ca, cb, cb):
            assert c.post("/api/auth/login", json={"password": "wrong"}).status_code == 401
        assert ca.post("/api/auth/login", json={"password": TEST_PASSWORD}).status_code == 429
        assert cb.post("/api/auth/login", json={"password": TEST_PASSWORD}).status_code == 429


def test_session_cookie_works_on_every_process_without_configured_secret(tmp_path, notifier):
    """本机开发没配 SESSION_SECRET：几个网站进程共用 DATA_DIR/.session_secret，A 登录的 cookie 在 B 也认。"""
    s = make_settings(tmp_path, SESSION_SECRET="")
    upgrade_to_heads(s.DATABASE_URL)
    a, b = create_app(s, notifier=notifier), create_app(s, notifier=notifier)
    with TestClient(a) as ca, TestClient(b) as cb:
        token = ca.post("/api/auth/login", json={"password": TEST_PASSWORD}).cookies[COOKIE_NAME]
        cb.cookies.set(COOKIE_NAME, token)
        assert cb.get("/api/auth/me").json() == {"admin": True}
    assert (s.DATA_DIR / ".session_secret").stat().st_mode & 0o077 == 0  # 只有自己能读


def test_count_and_add_shared_between_processes(settings):
    """入口用的「只记一笔、按窗口数」（访客问答每个 IP 每天几次）：两个进程记的加在一起数。"""
    a, b = Database(settings.DATABASE_URL), Database(settings.DATABASE_URL)
    try:
        la, lb = RateLimits(SqlStorage(a)), RateLimits(SqlStorage(b))
        la.add("entry.web_visitor", "1.2.3.4")
        lb.add("entry.web_visitor", "1.2.3.4")
        lb.add("entry.web_visitor", "5.6.7.8")
        assert la.count("entry.web_visitor", "1.2.3.4", 86400) == 2
        assert lb.count("entry.web_visitor", "5.6.7.8", 86400) == 1
        assert la.count("entry.web_visitor", "1.2.3.4", 10 * 86400) == 2  # 超过两天按两天数
    finally:
        a.dispose()
        b.dispose()
