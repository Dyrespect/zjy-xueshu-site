"""邮箱这条老入口和「我的订单」：没配邮件服务时邮箱接口整块关闭；绑邮箱 → 凭订单号 + 邮箱登录（12 号设计起发统一的会话 cookie）
→ 看订单；对不上不露馅；试错限次；notify.email 节点（假发件员，不发真信）；开票通知接上 notify.email。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.nodes import NodeCall, run_node
from app.intake import flow
from app.intake.runtime import get_runtime
from tests.channels.entry_helpers import FakeMail, entry_app, pool_code


def test_account_off_without_mail(tmp_path, notifier, settings):
    app = entry_app(settings, notifier, tmp_path)
    with TestClient(app) as c:
        assert c.get("/api/channels/account/status").json() == {"enabled": False}
        assert c.post("/api/channels/account/login/start", json={"order_no": "00001", "email": "a@b.cn"}).status_code == 404
        assert c.get("/api/channels/account/orders").status_code == 401  # 我的订单要登录（12 号设计）
        assert c.get("/api/channels/account/session").json()["email"] is False
        key = c.post("/api/channels/web/sessions").json()["key"]
        assert c.get(f"/api/channels/web/{key}").json()["account_enabled"] is False
        with get_runtime(app).database.session() as db:
            flow.ensure_nodes()
            r = run_node("notify.email", NodeCall(db, None, "test"), {"to": "a@b.cn", "subject": "x", "text": "y"})
            assert r.exit == "off"


def test_bind_login_and_my_orders(tmp_path, notifier, settings):
    mail = FakeMail()
    app = entry_app(settings, notifier, tmp_path, mail=mail)
    with TestClient(app) as c:
        assert c.get("/api/channels/account/status").json() == {"enabled": True}
        with get_runtime(app).database.session() as db:
            code = pool_code(db)
        key = c.post(f"/api/channels/redeem/{code}/web", json={}).json()["key"]
        chat = c.get(f"/api/channels/web/{key}").json()
        assert chat["account_enabled"] and not chat["email_bound"]
        order_no = chat["order"]["order_no"]
        # 绑邮箱（凭聊天 key 证明是自己的单）
        r = c.post("/api/channels/account/bind/start", json={"chat_key": key, "email": "Lab@Example.edu.cn"}).json()
        assert r["masked"] == "la***@example.edu.cn" and len(mail.sent) == 1 and mail.sent[0]["to"] == "lab@example.edu.cn"
        bad = c.post("/api/channels/account/bind/verify", json={"chat_key": key, "email": "lab@example.edu.cn",
                                                                 "code": "000000", "challenge": r["challenge"]})
        assert bad.status_code == 400
        ok = c.post("/api/channels/account/bind/verify", json={"chat_key": key, "email": "lab@example.edu.cn",
                                                                "code": mail.last_code(), "challenge": r["challenge"]})
        assert ok.status_code == 200 and c.get(f"/api/channels/web/{key}").json()["email_bound"]
        # 凭订单号 + 邮箱登录
        s = c.post("/api/channels/account/login/start", json={"order_no": order_no, "email": "lab@example.edu.cn"}).json()
        assert len(mail.sent) == 2 and order_no in mail.sent[-1]["text"]
        t = c.post("/api/channels/account/login/verify", json={"order_no": order_no, "email": "lab@example.edu.cn",
                                                               "code": mail.last_code(), "challenge": s["challenge"]})
        assert t.status_code == 200 and "psy_sess" in t.cookies
        mine = c.get("/api/channels/account/orders").json()
        assert [o["order_no"] for o in mine["orders"]] == [order_no]
        assert mine["orders"][0]["delivery_path"].startswith("/d/") and mine["orders"][0]["chat_path"] == f"/chat/{key}"
        assert c.get("/api/channels/account/session").json()["method"] == "email"
        c.post("/api/channels/account/logout", json={})
        assert c.get("/api/channels/account/orders").status_code == 401
        # 对不上（邮箱没绑这单）：照样回「已发」，但不发信，验证码也对不上
        s2 = c.post("/api/channels/account/login/start", json={"order_no": order_no, "email": "stranger@x.cn"})
        assert s2.status_code == 200 and len(mail.sent) == 2
        guess = c.post("/api/channels/account/login/verify", json={"order_no": order_no, "email": "stranger@x.cn",
                                                                   "code": "123456", "challenge": s2.json()["challenge"]})
        assert guess.status_code == 400
        # 换了订单号的挑战不能拿来用
        swap = c.post("/api/channels/account/login/verify", json={"order_no": "99999", "email": "lab@example.edu.cn",
                                                                  "code": "000000", "challenge": s["challenge"]})
        assert swap.status_code == 400
        # 试错限次
        codes = [c.post("/api/channels/account/login/verify", json={"order_no": order_no, "email": "lab@example.edu.cn",
                                                                    "code": "111111", "challenge": s["challenge"]}).status_code
                 for _ in range(8)]
        assert codes[-1] == 429


def test_invoice_notify_uses_email_node(tmp_path, notifier, settings):
    """开票模块的 invoice.notify 见到 notify.email 登记了就用它；发信服务没配时进待发（不报错）。"""
    mail = FakeMail()
    app = entry_app(settings, notifier, tmp_path, mail=mail)
    with TestClient(app):
        with get_runtime(app).database.session() as db:
            flow.ensure_nodes()
            r = run_node("notify.email", NodeCall(db, None, "invoice.notify"),
                         {"to": "lab@example.edu.cn", "subject": "你的发票开好了", "text": "下载：/d/x"})
            assert r.exit == "sent" and mail.sent[-1]["subject"] == "你的发票开好了"
            bad = run_node("notify.email", NodeCall(db, None, "t"), {"to": "lab@example.edu.cn", "subject": "x", "text": "y"})
            assert bad.exit == "sent"
