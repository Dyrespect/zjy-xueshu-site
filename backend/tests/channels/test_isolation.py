"""数据隔离（12 号设计第十节）：A 客户登录后访问 B 客户的每类资源，全部 404；凭令牌的接口只给它自己那一单的子资源。

资源：订单详情、「记到我的账号」、交付页最终版（成品）、需求卡上传的材料、网页聊天里的文件、发票文件、兑换页（B 的码）。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.channels.settings import ChannelsSettings
from app.channels.sms import FakeSms
from app.core.db import utcnow
from app.core.nodes import NodeCall, run_node
from app.intake.models import FileRecord, Message, Order
from app.intake.runtime import get_runtime
from app.invoices.models import InvoiceFile, InvoiceRequest
from tests.channels.login_helpers import MOBILE_UA, sms_login
from tests.delivery.helpers import add_package, delivery_app
from tests.intake.helpers import PDF_BYTES, ready


def _deliver_and_release(c: TestClient, rt, oid: int, token: str) -> int:
    with rt.database.session() as db:
        o = db.get(Order, oid)
        add_package(db, rt.ctx, o, pages=2)
        assert run_node("deliver.receive", NodeCall(db, rt.ctx, "maker", o.id), {"order_id": o.id}).exit == "ok"
    r = c.post(f"/api/delivery/{token}/received")
    assert r.status_code == 200 and r.json()["released"]
    return r.json()["files"][0]["id"]


def _invoice_file(rt, oid: int) -> int:
    with rt.database.session() as db:
        inv = InvoiceRequest(order_id=oid, flow_step="issued", stage="issued", title="某某大学", email="a@b.cn")
        db.add(inv)
        db.flush()
        key = rt.ctx.storage.save(b"%PDF-1.4 invoice", folder="invoices", filename=f"test-{oid}.pdf")
        f = InvoiceFile(invoice_id=inv.id, filename="发票.pdf", kind="pdf", storage_key=key, created_at=utcnow())
        db.add(f)
        db.flush()
        return f.id


@pytest.fixture
def two(settings, notifier, tmp_path):
    """两个客户 A、B：各一单（已交付、放出最终版、开了发票）+ 各一单还在填需求卡（传了一份旧材料），各自用手机号登录并认领成自己的。"""
    settings.PUBLIC_BASE_URL = "https://psyppt.example.cn"
    app = delivery_app(settings, notifier, tmp_path)
    app.state.channels_settings = ChannelsSettings(_env_file=None, CHANNELS_DISPATCH=False, CHANNELS_TICK=False,
                                                   WECOM_API_BASE="https://qyapi.test/cgi-bin")
    sms = FakeSms()
    app.state.sms_sender = sms
    out: dict = {}
    with TestClient(app, base_url="https://testserver", headers={"User-Agent": MOBILE_UA}) as c0:
        rt = get_runtime(app)
        for who, phone in (("A", "13800000001"), ("B", "13800000002")):
            with rt.database.session() as db:
                door, o = ready(db, rt.ctx, name=f"Kehu{who}")
                door2, o2 = ready(db, rt.ctx, name=f"Kehu{who}Two", brief=False)
                paper = db.scalar(select(Message).where(Message.customer_id == door.id, Message.file_id.is_not(None))).file_id
                info = dict(key=door.external_id, key2=door2.external_id, oid=o.id, token=o.delivery_token, oid2=o2.id,
                            token2=o2.delivery_token, paper=paper)
            info["final"] = _deliver_and_release(c0, rt, info["oid"], info["token"])
            info["invoice_file"] = _invoice_file(rt, info["oid"])
            up = c0.post(f"/api/channels/brief/{info['token2']}/files", data={"kind": "ref"},
                         files={"file": ("旧PPT.pdf", PDF_BYTES, "application/pdf")})
            assert up.status_code == 200, up.text
            with rt.database.session(write=False) as db:
                info["brief_file"] = db.scalar(select(FileRecord.id).where(FileRecord.order_id == info["oid2"])
                                               .order_by(FileRecord.id.desc()).limit(1))
            out[who] = info
        clients = {}
        for who, phone in (("A", "13800000001"), ("B", "13800000002")):
            c = TestClient(app, base_url="https://testserver", headers={"User-Agent": MOBILE_UA})
            c.__enter__()
            assert sms_login(c, sms, phone).status_code == 200
            for k in ("key", "key2"):
                assert c.post("/api/channels/account/adopt", json={"key": out[who][k]}).json()["state"] == "adopted"
            clients[who] = c
        yield app, clients, out
        for c in clients.values():
            c.__exit__(None, None, None)


def test_idor_other_customer_gets_404(two):
    """A 登录后拿 B 的每类资源：一律 404（不说 403、不给任何 B 的信息）。"""
    app, cl, d = two
    a, A, B = cl["A"], d["A"], d["B"]
    mine = [o["order_no"] for o in a.get("/api/channels/account/orders").json()["orders"]]
    assert sorted(mine) == sorted([f"{A['oid']:05d}", f"{A['oid2']:05d}"])
    # 订单详情
    assert a.get(f"/api/channels/account/orders/{A['oid']:05d}").status_code == 200
    for oid in (B["oid"], B["oid2"], 99999):
        r = a.get(f"/api/channels/account/orders/{oid:05d}")
        assert r.status_code == 404 and str(oid) not in r.text
    # 「记到我的账号」：B 的单是 B 账号的
    assert a.post("/api/channels/account/order-link", json={"token": B["token"]}).status_code == 404
    assert a.post("/api/channels/account/order-link", json={"chat_key": B["key"]}).status_code == 404
    assert a.get("/api/channels/account/order-link", params={"token": B["token"]}).json()["state"] == "none"
    assert a.get("/api/channels/account/order-link", params={"token": A["token"]}).json()["state"] == "mine"
    # 「把这台设备的会话归我」：B 的聊天 key 不动
    assert a.post("/api/channels/account/adopt", json={"key": B["key"]}).json()["state"] == "other"
    # 成品（最终版）
    assert a.get(f"/api/delivery/{A['token']}/final/{A['final']}").status_code == 200
    assert a.get(f"/api/delivery/{A['token']}/final/{B['final']}").status_code == 404
    # 上传的材料（聊天里的文件、需求卡上的旧材料）
    assert a.get(f"/api/channels/web/{A['key']}/files/{A['paper']}").status_code == 200
    assert a.get(f"/api/channels/web/{A['key']}/files/{B['paper']}").status_code == 404
    assert a.delete(f"/api/channels/brief/{A['token2']}/files/{B['brief_file']}").status_code == 404
    # 发票文件
    assert a.get(f"/api/invoices/order/{A['token']}/files/{A['invoice_file']}").status_code == 200
    assert a.get(f"/api/invoices/order/{A['token']}/files/{B['invoice_file']}").status_code == 404
    # 兑换页：B 认领过的码不给任何信息
    with get_runtime(app).database.session(write=False) as db:
        from app.intake.models import ActivationCode

        b_code = db.scalar(select(ActivationCode.code).where(ActivationCode.order_id == B["oid"]))
    if b_code:
        v = a.get(f"/api/channels/redeem/{b_code}").json()
        assert v["state"] == "taken" and not v["sku_name"] and not v["progress"]


def test_token_routes_only_own_subresources(two):
    """凭令牌的接口不看会话：没登录照样能用自己的令牌（老链接、平台复制来的链接），但令牌只管它那一单。"""
    app, cl, d = two
    A, B = d["A"], d["B"]
    with TestClient(app, base_url="https://testserver", headers={"User-Agent": MOBILE_UA}) as anon:
        assert anon.get(f"/api/delivery/{A['token']}").status_code == 200
        assert anon.get(f"/api/delivery/{A['token']}/final/{A['final']}").status_code == 200
        assert anon.get(f"/api/delivery/{A['token']}/final/{B['final']}").status_code == 404
        assert anon.get(f"/api/channels/web/{B['key']}/files/{A['paper']}").status_code == 404
        assert anon.get(f"/api/invoices/order/{B['token']}/files/{A['invoice_file']}").status_code == 404
        assert anon.get("/api/channels/account/orders").status_code == 401
        assert anon.get(f"/api/channels/account/orders/{A['oid']:05d}").status_code == 401
        assert anon.get("/api/channels/account/order-link", params={"token": A["token"]}).json()["state"] == "login"
    # B 登录着、拿 A 的令牌：令牌是凭证（照旧能看 A 这一单），但不会因此把 A 的单记到 B 名下
    b = cl["B"]
    assert b.get(f"/api/delivery/{A['token']}").status_code == 200
    assert b.post("/api/channels/account/order-link", json={"token": A["token"]}).status_code == 404
    assert f"{A['oid']:05d}" not in str(b.get("/api/channels/account/orders").json())
