"""微信里静默登录、会话、合并规则（docs/任务单/12_登录与正规化_设计.md 第五、六节）。假网页授权，不联网。"""

from __future__ import annotations

import logging
from urllib.parse import parse_qs, unquote, urlparse

import pytest
import requests
from sqlalchemy import select

from app.channels.models import Login, Person
from app.channels.sms import FakeSms
from app.core.events import list_events
from app.intake.models import Customer, Order
from app.intake.runtime import get_runtime
from tests.channels.entry_helpers import paid_code, pool_code
from tests.channels.login_helpers import (APPID, MOBILE_UA, PC_UA, SECRET, WECHAT_UA, FakeOAuth, all_rows_text, client,
                                          login_app, openid_for, sms_login, wx_login)


def _db(app):
    return get_runtime(app).database


def test_wx_login_state_and_no_openid_logged(settings, notifier, tmp_path, caplog):
    """授权链接格式对（snsapi_base、参数顺序、#wechat_redirect）；state 对上才换 openid；openid 只在登录身份表里，不进事件、日志。"""
    caplog.set_level(logging.DEBUG)
    oauth = FakeOAuth()
    app = login_app(settings, notifier, tmp_path, oauth=oauth)
    with client(app, WECHAT_UA) as c:
        r = c.get("/api/channels/login/wx", params={"next": "/c/PSY-ABC"}, follow_redirects=False)
        loc = r.headers["location"]
        assert loc.startswith("https://open.weixin.qq.com/connect/oauth2/authorize?appid=" + APPID + "&redirect_uri=")
        assert loc.endswith("&response_type=code&scope=snsapi_base&state=" + parse_qs(urlparse(loc[:-16]).query)["state"][0]
                            + "#wechat_redirect")
        redirect = unquote(parse_qs(urlparse(loc[:-16]).query)["redirect_uri"][0])
        assert redirect.startswith("https://psyppt.example.cn/api/channels/login/wx/callback?next=")
        cookie = r.headers["set-cookie"]
        assert "psy_wxl=" in cookie and "HttpOnly" in cookie and "Path=/api/channels/login/wx" in cookie
        # state 对不上：不换 openid
        bad = c.get("/api/channels/login/wx/callback", params={"next": "/me", "code": "C9", "state": "0" * 32}, follow_redirects=False)
        assert bad.status_code == 303 and bad.headers["location"] == "/me?login=wx_state" and oauth.calls == []
        ok = wx_login(c, "C1", "/c/PSY-ABC")
        assert ok.status_code == 303 and ok.headers["location"] == "/c/PSY-ABC" and "psy_sess" in ok.cookies
        s = c.get("/api/channels/account/session").json()
        assert s["logged_in"] and s["method"] == "wx" and s["label"] == "微信" and s["methods"] == ["wx"]
    text = all_rows_text(_db(app))
    oid = openid_for("C1")
    assert text.count(oid) == 1 and f"channels_logins:" in text.split(oid)[0].rsplit("\n", 1)[-1]  # 只在登录身份表
    assert oid not in caplog.text and SECRET not in caplog.text
    with _db(app).session(write=False) as db:
        assert all(oid not in str(e.content) for e in list_events(db, limit=500))


@pytest.mark.parametrize("case,expect", [
    ("denied", "wx_denied"), ("used", "wx_fail"), ("snapshot", "wx_snapshot"), ("network", "wx_fail"), ("notwechat", "wx_notwechat"),
])
def test_wx_login_failures_fall_back(settings, notifier, tmp_path, case, expect):
    """授权失败、拒绝、快照页、不在微信里：回原页带 login=…，页面说原因、给手机号登录；不发会话。"""
    oauth = FakeOAuth(snapshot=case == "snapshot", error=requests.ConnectionError(f"https://x?secret={SECRET}") if case == "network" else None)
    app = login_app(settings, notifier, tmp_path, oauth=oauth)
    with client(app, PC_UA if case == "notwechat" else WECHAT_UA) as c:
        if case == "notwechat":
            r = c.get("/api/channels/login/wx", params={"next": "/me"}, follow_redirects=False)
        elif case == "denied":
            r0 = c.get("/api/channels/login/wx", params={"next": "/me"}, follow_redirects=False)
            state = parse_qs(urlparse(r0.headers["location"][:-16]).query)["state"][0]
            r = c.get("/api/channels/login/wx/callback", params={"next": "/me", "state": state}, follow_redirects=False)
        else:
            if case == "used":
                oauth.used.add("C5")
            r = wx_login(c, "C5")
        assert r.status_code == 303 and r.headers["location"] == f"/me?login={expect}"
        assert "psy_sess" not in r.cookies
        assert c.get("/api/channels/account/session").json()["logged_in"] is False


def test_next_only_site_paths(settings, notifier, tmp_path):
    app = login_app(settings, notifier, tmp_path)
    with client(app, WECHAT_UA) as c:
        for i, evil in enumerate(("https://evil.example/x", "//evil.example", "/\\evil", "javascript:alert(1)")):
            r = wx_login(c, f"C7-{i}", evil)
            assert r.headers["location"] == "/me"


def test_methods_by_device_and_off_switches(settings, notifier, tmp_path):
    """微信里：微信 + 手机号；电脑：扫码 + 手机号；手机浏览器：手机号。没配的一律不出现。"""
    app = login_app(settings, notifier, tmp_path, sms=FakeSms())
    with client(app, WECHAT_UA) as c:
        assert c.get("/api/channels/account/session").json()["methods"] == ["wx", "sms"]
    with client(app, PC_UA) as c:
        assert c.get("/api/channels/account/session").json()["methods"] == ["qr", "sms"]
    with client(app, MOBILE_UA) as c:
        s = c.get("/api/channels/account/session").json()
        assert s["methods"] == ["sms"] and s["login_required"] is True
    bare = login_app(settings, notifier, tmp_path / "b", wx=False, qr=False)
    with client(bare, PC_UA) as c:
        s = c.get("/api/channels/account/session").json()
        assert s["methods"] == [] and s["login_required"] is False and s["sms"] is False
        assert c.get("/api/channels/login/wx", follow_redirects=False).headers["location"] == "/me?login=wx_off"
        assert c.post("/api/channels/login/qr").status_code == 404


def test_session_logout_and_all_devices(settings, notifier, tmp_path):
    """同一人多设备：两台都登着；退出这台只掉这台；所有设备都退出后另一台也掉。"""
    app = login_app(settings, notifier, tmp_path)
    with client(app, WECHAT_UA) as a, client(app, WECHAT_UA) as b:
        wx_login(a, "C1")
        wx_login(b, "C1-b")
        assert a.get("/api/channels/account/session").json()["logged_in"] and b.get("/api/channels/account/session").json()["logged_in"]
        a.post("/api/channels/account/logout", json={})
        assert not a.get("/api/channels/account/session").json()["logged_in"]
        assert b.get("/api/channels/account/session").json()["logged_in"]
        wx_login(a, "C2")  # 换成另一个微信：b 不受影响
        assert b.get("/api/channels/account/session").json()["logged_in"]
        wx_login(a, "C1-c")
        assert a.post("/api/channels/account/logout", json={"all": True}).status_code == 200
        assert not a.get("/api/channels/account/session").json()["logged_in"]
        assert not b.get("/api/channels/account/session").json()["logged_in"]  # 所有设备都退出：b 也掉了
        assert b.get("/api/channels/account/orders").status_code == 401
        wx_login(b, "C1-d")  # 重新登录照常
        assert b.get("/api/channels/account/session").json()["logged_in"]


def test_session_cookie_tampered_or_expired_is_ignored(settings, notifier, tmp_path, monkeypatch):
    from app.core import access

    app = login_app(settings, notifier, tmp_path)
    with client(app, WECHAT_UA) as c:
        good = wx_login(c, "C1").cookies["psy_sess"]
    for bad in (good[:-3] + ("AAA" if not good.endswith("AAA") else "BBB"), "garbage"):
        with client(app, WECHAT_UA) as c:
            c.cookies.set("psy_sess", bad)
            assert c.get("/api/channels/account/orders").status_code == 401
    monkeypatch.setattr(access, "SESSION_MAX_AGE", -1)
    with client(app, WECHAT_UA) as c:
        wx_login(c, "C1")
        assert c.get("/api/channels/account/orders").status_code == 401


def test_merge_rules_on_login(settings, notifier, tmp_path):
    """L1 同一个微信登进同一个人；L2 匿名的聊天会话登录后归过来；L3 别人（有登录身份）的不并；
    L4 绑手机号碰到另一个人就合人；L8 取消关注删 openid。"""
    sms = FakeSms()
    app = login_app(settings, notifier, tmp_path, sms=sms)
    with client(app, MOBILE_UA) as c:
        with _db(app).session() as db:
            code = pool_code(db)
        key = c.post(f"/api/channels/redeem/{code}/web", json={}).status_code  # 要登录（短信开着）
        assert key == 401
    bare = login_app(settings, notifier, tmp_path / "anon", wx=True, qr=False, sms=sms)
    with client(bare, MOBILE_UA) as c:
        # 后台把「认领前要求登录」关了：照旧匿名认领
        from tests.channels.entry_helpers import set_entry

        set_entry(bare, login_required=False)
        with _db(bare).session() as db:
            code = pool_code(db)
        anon_key = c.post(f"/api/channels/redeem/{code}/web", json={}).json()["key"]
        sms_login(c, sms, "13800138001")
        assert c.post("/api/channels/account/adopt", json={"key": anon_key}).json()["state"] == "adopted"  # L2
        mine = c.get("/api/channels/account/orders").json()["orders"]
        assert len(mine) == 1
        # L3：另一台设备上的另一个账号拿这个 key 来 adopt：不并
    with client(bare, WECHAT_UA) as d:
        wx_login(d, "C77")
        assert d.post("/api/channels/account/adopt", json={"key": anon_key}).json()["state"] == "other"
        assert d.get("/api/channels/account/orders").json()["orders"] == []
        # L4：这个微信账号绑上那个手机号 → 两个人合成一个
        r = sms_login(d, sms, "13800138001", purpose="bind")
        assert r.status_code == 200 and r.json()["merged"] is True
        assert len(d.get("/api/channels/account/orders").json()["orders"]) == 1
        s = d.get("/api/channels/account/session").json()
        assert s["phone"] == "138****8001" and s["phone_bound"] and not s["prompt_phone"]
    with _db(bare).session(write=False) as db:
        people = {x.person_id for x in db.scalars(select(Login))}
        assert len(people) == 1
        alive = [p for p in db.scalars(select(Person)) if p.merged_into_id is None and p.id in people]
        assert len(alive) == 1
        # 事件里只有打码的手机号
        assert all("13800138001" not in str(e.content) for e in list_events(db, limit=500))


def test_unsubscribe_forgets_openid(settings, notifier, tmp_path):
    from app.channels import login

    app = login_app(settings, notifier, tmp_path)
    with client(app, WECHAT_UA) as c:
        wx_login(c, "C1")
        assert c.get("/api/channels/account/session").json()["logged_in"]
        with _db(app).session() as db:
            assert login.forget_wx(db, openid_for("C1"), by="test") is not None
        assert not c.get("/api/channels/account/session").json()["logged_in"]  # 所有设备的会话失效
    with _db(app).session(write=False) as db:
        assert db.scalar(select(Login).where(Login.kind == "wx")) is None


def test_claim_requires_login_and_binds_order_to_account(settings, notifier, tmp_path):
    """认领前先登录：有登录方式时没登录 401；登录后认领，订单挂到这个账号；换一台设备登同一个账号，兑换页认得「是你的」；
    别的账号拿着码来：拒绝、不给任何那单的信息（L7）。"""
    sms = FakeSms()
    app = login_app(settings, notifier, tmp_path, sms=sms)
    with client(app, WECHAT_UA) as a:
        with _db(app).session() as db:
            code, oid = paid_code(db, get_runtime(app).ctx)
        v = a.get(f"/api/channels/redeem/{code}").json()
        assert v["state"] == "unclaimed" and v["login_required"] and not v["logged_in"]
        assert a.post(f"/api/channels/redeem/{code}/web", json={}).status_code == 401
        wx_login(a, "C1")
        v = a.get(f"/api/channels/redeem/{code}").json()
        assert v["logged_in"] and v["login_label"] == "微信"
        r = a.post(f"/api/channels/redeem/{code}/web", json={})
        assert r.status_code == 200 and r.json()["brief_path"].startswith("/b/")
        orders = a.get("/api/channels/account/orders").json()["orders"]
        assert [o["order_no"] for o in orders] == [f"{oid:05d}"] and orders[0]["brief_path"]
    with client(app, WECHAT_UA) as b:  # 换一台设备（没有聊天 key），用同一个微信登录
        wx_login(b, "C1-b")
        v = b.get(f"/api/channels/redeem/{code}").json()
        assert v["state"] == "yours" and v["progress"]
    with client(app, MOBILE_UA) as x:  # 另一个账号
        sms_login(x, sms, "13900139000")
        v = x.get(f"/api/channels/redeem/{code}").json()
        assert v["state"] == "taken" and v["sku_name"] == "" and v["progress"] == ""
        r = x.post(f"/api/channels/redeem/{code}/web", json={})
        assert r.status_code == 409 and f"{oid:05d}" not in r.text
    with _db(app).session(write=False) as db:
        o = db.get(Order, oid)
        door = db.get(Customer, o.customer_id)
        assert door.person_id is not None
