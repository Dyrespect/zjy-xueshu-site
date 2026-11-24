"""开票的闭环和防护（设计第七节 K1、K3–K6，第八节第 2 条）。全走接口、假网关、假通知，不联网。"""

from __future__ import annotations

import csv
import io

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.events import Event, record_event
from app.intake.models import Order
from app.intake.runtime import get_runtime
from app.invoices.models import InvoiceNotice, InvoiceRequest
from tests.invoices.helpers import (
    FIELDS,
    PDF,
    XML,
    admin_rows,
    apply_delivery,
    checkout,
    complete,
    invoice_app,
    issue,
    login,
    ofd_bytes,
    pay,
    platform_order,
    web_order,
)


def _events(app, type_: str) -> list[dict]:
    with get_runtime(app).database.session() as db:
        return [e.content for e in db.scalars(select(Event).where(Event.type == type_).order_by(Event.id))]


def test_checkout_prefill_to_issue_loop(settings, notifier, tmp_path):
    """下单页预填 → 付款 → 付款页挂上订单（草稿）→ 确认收货 → 自动进待开票 → 后台上传开好 → 两个页面都能下载 → 作废重开 → 再开。"""
    app = invoice_app(settings, notifier, tmp_path)
    with TestClient(app) as c:
        cfg = c.get("/api/invoices/config").json()
        assert cfg["enabled"] and [k["key"] for k in cfg["kinds"]] == ["normal"] and cfg["item_name"] == "技术服务费"

        token = checkout(c)
        # 没核对不收
        r = c.post("/api/invoices/drafts", json={"checkout_token": token, "fields": FIELDS, "confirmed": False})
        assert r.status_code == 422 and r.json()["field"] == "confirmed"
        # 乱写的付款页令牌不收
        assert c.post("/api/invoices/drafts", json={"checkout_token": "x" * 32, "fields": FIELDS, "confirmed": True}).status_code == 404
        r = c.post("/api/invoices/drafts", json={"checkout_token": token, "fields": FIELDS, "confirmed": True})
        assert r.status_code == 200 and r.json()["exit"] == "prefilled", r.text

        oid = pay(c, app, token)
        p = c.post(f"/api/invoices/checkout/{token}").json()
        assert p["current"]["step"] == "waiting" and p["current"]["title"] == "清华大学"
        assert "订单完成" in p["current"]["note"]
        with get_runtime(app).database.session() as db:
            dtoken = db.get(Order, oid).delivery_token

        complete(app, oid)
        p = c.get(f"/api/invoices/order/{dtoken}").json()  # 打开交付页就顺手推进
        assert p["current"]["step"] == "pending" and p["current"]["requested_at"]

        login(c)
        rows = admin_rows(c)
        assert len(rows) == 1 and rows[0]["order_id"] == oid and rows[0]["max_amount"] == rows[0]["paid"]
        assert "纳税人识别号：12100000400000624D" in rows[0]["copy_text"] and "项目：技术服务费" in rows[0]["copy_text"]
        inv_id = rows[0]["id"]

        r = issue(c, inv_id, files=[("发票.pdf", PDF), ("发票.ofd", ofd_bytes()), ("发票.xml", XML)])
        assert r.status_code == 200 and r.json()["exit"] == "issued", r.text
        p = c.get(f"/api/invoices/order/{dtoken}").json()
        assert p["current"]["step"] == "issued" and len(p["current"]["files"]) == 3
        got = c.get(p["current"]["files"][0]["url"])
        assert got.status_code == 200 and got.content == PDF and "attachment" in got.headers["content-disposition"]
        assert got.headers["cache-control"] == "no-store"
        p2 = c.post(f"/api/invoices/checkout/{token}").json()
        assert c.get(p2["current"]["files"][0]["url"]).content == PDF

        # 通知：邮件进待发（还没有发邮件的服务），没认领的单站内跳过
        n = c.get("/api/admin/invoices/notices").json()["rows"]
        assert len(n) == 1 and n[0]["channel"] == "email" and "开好了" in n[0]["text"] and f"/d/{dtoken}" in n[0]["text"]
        assert c.post(f"/api/admin/invoices/notices/{n[0]['id']}/sent").status_code == 200

        # 作废重开：旧的作废，新的一张进待开票，客人那边看到新的
        r = c.post(f"/api/admin/invoices/{inv_id}/void", json={"reason": "抬头少了「大学」两个字", "reopen": True,
                                                               "fields": {**FIELDS, "title": "清华大学（重开）"}})
        assert r.status_code == 200 and r.json()["new_invoice_id"], r.text
        new_id = r.json()["new_invoice_id"]
        p = c.get(f"/api/invoices/order/{dtoken}").json()
        assert p["current"]["id"] == new_id and p["current"]["step"] == "pending" and p["current"]["title"] == "清华大学（重开）"
        assert p["history"][0]["step"] == "voided" and "抬头" in p["history"][0]["reason"]
        assert issue(c, new_id).json()["exit"] == "issued"

        # 评估数据
        m = c.get("/api/admin/invoices/metrics", params={"days": 7}).json()
        assert m["completed_orders"] == 1 and m["orders_with_request"] == 1 and m["request_rate"] == 1.0
        assert m["issued"] == 2 and m["issue_hours_avg"] is not None and m["pending_now"] == 0

        # 导出：BOM、表头、防公式注入
        exp = c.get("/api/admin/invoices/export.csv", params={"status": "all"})
        assert exp.status_code == 200 and exp.content.startswith("﻿".encode())
        table = list(csv.reader(io.StringIO(exp.content.decode("utf-8-sig"))))
        assert table[0][:3] == ["申请号", "单号", "渠道"] and any("清华大学（重开）" in row for row in table[1:])

    for t in ("invoice.prefilled", "invoice.submitted", "invoice.issued", "invoice.voided", "invoice.notified", "invoice.downloaded"):
        assert _events(app, t), t
    assert any(e["to_step"] == "pending" for e in _events(app, "invoice.stage"))


def test_gate_waits_until_completed(settings, notifier, tmp_path):
    """K5：订单不到「已完成」不进待开票（存成草稿），后台出票也不行；完成后自动进。"""
    app = invoice_app(settings, notifier, tmp_path)
    with TestClient(app) as c:
        _, oid, dtoken = web_order(c, app)
        r = apply_delivery(c, dtoken)
        assert r.status_code == 200 and r.json()["exit"] == "drafted", r.text
        inv_id = r.json()["invoice_id"]
        login(c)
        assert admin_rows(c, "pending") == [] and admin_rows(c, "draft")[0]["id"] == inv_id
        with get_runtime(app).database.session() as db:  # 硬塞也开不了：出票节点再过一遍关口
            inv = db.get(InvoiceRequest, inv_id)
            assert inv.flow_step == "waiting" and inv.requested_at is None
        r = issue(c, inv_id)
        assert r.status_code == 409 and "待开票" in r.json()["detail"]
        complete(app, oid)
        assert c.post("/api/admin/invoices/sweep").json()["promoted"] == 1
        assert admin_rows(c, "pending")[0]["id"] == inv_id


def test_one_active_request_per_order(settings, notifier, tmp_path):
    """K6：一单只能有一张在办的；撤回、驳回、作废后能重新申请；库里的唯一键兜底。"""
    app = invoice_app(settings, notifier, tmp_path)
    with TestClient(app) as c:
        _, oid, dtoken = web_order(c, app)
        complete(app, oid)
        first = apply_delivery(c, dtoken).json()
        assert first["exit"] == "requested"
        again = apply_delivery(c, dtoken, title="北京百度网讯科技有限公司", tax_id="91110000802100433B").json()
        assert again["exit"] == "exists" and again["invoice_id"] == first["invoice_id"]
        # 客人撤回 → 能再申请
        assert c.post(f"/api/invoices/order/{dtoken}/withdraw", json={"invoice_id": first["invoice_id"]}).status_code == 200
        second = apply_delivery(c, dtoken).json()
        assert second["exit"] == "requested" and second["invoice_id"] != first["invoice_id"]
        # 后台驳回 → 客人看到原因、能再申请
        login(c)
        assert c.post(f"/api/admin/invoices/{second['invoice_id']}/reject", json={"reason": "税号和抬头对不上"}).status_code == 200
        p = c.get(f"/api/invoices/order/{dtoken}").json()
        assert p["current"] is None and p["can_apply"] and "税号和抬头对不上" in p["history"][0]["note"]
        third = apply_delivery(c, dtoken).json()
        assert third["exit"] == "requested"
        # 唯一键兜底：直接往库里塞第二张在办的会撞
        with get_runtime(app).database.session() as db:
            db.add(InvoiceRequest(order_id=oid, active_order_id=oid, title="x", email="x@y.cn"))
            try:
                db.flush()
                raise AssertionError("唯一键没挡住")
            except IntegrityError:
                db.rollback()
        # 撤回别人的申请不行（交付页只认自己这单）
        _, oid2, dtoken2 = web_order(c, app)
        assert c.post(f"/api/invoices/order/{dtoken2}/withdraw", json={"invoice_id": third["invoice_id"]}).status_code == 404


def test_download_requires_order_owner(settings, notifier, tmp_path):
    """K1：A 单的交付页令牌、付款页令牌都拿不到 B 单的发票；作废了的不给；乱写的令牌 404。"""
    app = invoice_app(settings, notifier, tmp_path)
    with TestClient(app) as c:
        login(c)
        ids = {}
        for who in ("a", "b"):
            token, oid, dtoken = web_order(c, app)
            complete(app, oid)
            inv_id = apply_delivery(c, dtoken).json()["invoice_id"]
            assert issue(c, inv_id).json()["exit"] == "issued"
            fid = c.get(f"/api/invoices/order/{dtoken}").json()["current"]["files"][0]["id"]
            ids[who] = (token, dtoken, inv_id, fid)
        (ta, da, ia, fa), (tb, db_, ib, fb) = ids["a"], ids["b"]
        assert c.get(f"/api/invoices/order/{da}/files/{fa}").status_code == 200
        r = c.get(f"/api/invoices/order/{da}/files/{fb}")
        assert r.status_code == 404  # 12 号设计第十节：别的单的发票文件一律 404（不说 403，不暴露存在）
        assert c.get(f"/api/invoices/checkout/{ta}/files/{fb}").status_code == 404
        assert c.get(f"/api/invoices/checkout/{tb}/files/{fb}").status_code == 200
        assert c.get(f"/api/invoices/order/{da}/files/999999").status_code == 404
        assert c.get(f"/api/invoices/order/{'z' * 40}/files/{fa}").status_code == 404
        assert c.get("/api/invoices/order/short/files/1").status_code == 404
        # 作废以后连自己也拿不到这张
        assert c.post(f"/api/admin/invoices/{ia}/void", json={"reason": "金额开错了"}).status_code == 200
        r = c.get(f"/api/invoices/order/{da}/files/{fa}")
        assert r.status_code == 403 and "不能下载" in r.json()["detail"]


def test_amount_cannot_exceed_paid(settings, notifier, tmp_path):
    """K3：开票金额不能超过实付（含加购）；失败信息三件写回后台，什么都不动。"""
    app = invoice_app(settings, notifier, tmp_path)
    with TestClient(app) as c:
        _, oid, dtoken = web_order(c, app)
        complete(app, oid)
        inv_id = apply_delivery(c, dtoken).json()["invoice_id"]
        login(c)
        row = admin_rows(c)[0]
        paid = row["paid"]
        with get_runtime(app).database.session() as db:  # 实付 = 下单页那笔（基础价 + 再改一轮）
            assert db.get(Order, oid).paid_amount == paid
        too_much = f"{float(paid) + 0.01:.2f}"
        r = issue(c, inv_id, amount=too_much)
        assert r.status_code == 409
        d = r.json()["detail"]
        assert "超过了实付" in d and "怎么改" in d and "07_开票_设计.md" in d
        assert issue(c, inv_id, amount="0").status_code == 409
        with get_runtime(app).database.session() as db:
            inv = db.get(InvoiceRequest, inv_id)
            assert inv.flow_step == "pending" and not inv.amount
        r = issue(c, inv_id, amount=paid)
        assert r.status_code == 200 and r.json()["amount"] == paid


def test_refunded_order_cannot_issue(settings, notifier, tmp_path):
    """K4：退了款的不能开；在退款中的先等；部分退款的按退后金额开；开票后再退款提醒负责人。"""
    app = invoice_app(settings, notifier, tmp_path)
    with TestClient(app) as c:
        login(c)
        # 1. 已完成的单申请了，网页退了一部分 → 只能开退后的数
        _, oid, dtoken = web_order(c, app)
        complete(app, oid)
        inv_id = apply_delivery(c, dtoken).json()["invoice_id"]
        r = c.post("/api/admin/shop/refunds", json={"order_id": oid, "amount_fen": 990, "scope": "addon:revision", "reason": "没用上"})
        assert r.json()["exit"] == "ok", r.text
        row = admin_rows(c)[0]
        assert row["refunded"] == "9.90" and any("退过 9.90" in w for w in row["warnings"])
        assert issue(c, inv_id, amount=row["paid"]).status_code == 409
        assert issue(c, inv_id).json()["amount"] == row["max_amount"]
        # 开票后又退款 → 定时任务提醒负责人一次，后台列表有警告
        r = c.post("/api/admin/shop/refunds", json={"order_id": oid, "amount_fen": 100, "scope": "other", "reason": "补偿"})
        assert r.json()["exit"] == "ok"
        out = c.post("/api/admin/invoices/sweep").json()
        assert out["refund_after_issue"] == [inv_id]
        assert c.post("/api/admin/invoices/sweep").json()["refund_after_issue"] == []
        assert any("作废" in t for t in notifier.sent if "开了发票" in t)
        assert "又退了款" in admin_rows(c, "issued")[0]["warnings"][0]

        # 2. 全退了（完成之后退款：订单作废不了，但钱退光了）→ 不能开、客人也不能申请
        _, oid2, dtoken2 = web_order(c, app)
        complete(app, oid2)
        inv2 = apply_delivery(c, dtoken2).json()["invoice_id"]
        paid2 = admin_rows(c)[0]["paid"]
        fen = round(float(paid2) * 100)
        assert c.post("/api/admin/shop/refunds", json={"order_id": oid2, "amount_fen": fen, "reason": "全退"}).json()["exit"] == "ok"
        r = issue(c, inv2)
        assert r.status_code == 409 and "退款" in r.json()["detail"]

        # 3. 在退款中（网关还没出结果）→ 先等
        _, oid3, dtoken3 = web_order(c, app)
        complete(app, oid3)
        inv3 = apply_delivery(c, dtoken3).json()["invoice_id"]
        with get_runtime(app).database.session() as db:
            record_event(db, "shop.refund_requested", "checkout:999", {"order_id": oid3, "amount_fen": 100, "by": "edison"})
            db.commit()
        r = issue(c, inv3)
        assert r.status_code == 409 and "正在退款" in r.json()["detail"]

        # 4. 作废了的单（开工前退款）客人申请不了
        _, oid4, dtoken4 = web_order(c, app)
        assert c.post("/api/admin/shop/refunds", json={"order_id": oid4, "amount_fen": fen, "reason": "撤单"}).json()["exit"] == "ok"
        r = apply_delivery(c, dtoken4)
        assert r.status_code == 409 and "退款" in r.json()["detail"]


def test_platform_order_customer_cannot_apply_but_admin_can_record(settings, notifier, tmp_path):
    """平台单：客人在交付页不能自己申请（平台能不能开没核实）；后台能手工录一条，开好后客人能下载。"""
    app = invoice_app(settings, notifier, tmp_path)
    with TestClient(app) as c:
        oid, dtoken = platform_order(app, "xhs")
        complete(app, oid)
        p = c.get(f"/api/invoices/order/{dtoken}").json()
        assert not p["can_apply"] and "小红书" in p["why_not"]
        assert apply_delivery(c, dtoken).status_code == 409
        login(c)
        look = c.get("/api/admin/invoices/order-lookup", params={"order_id": oid}).json()
        assert look["platform"] == "xhs" and look["gate"] == "open" and look["paid"]
        r = c.post("/api/admin/invoices/manual", json={"order_id": oid, "fields": FIELDS})
        assert r.status_code == 200 and r.json()["exit"] == "requested", r.text
        assert issue(c, r.json()["invoice_id"]).json()["exit"] == "issued"
        p = c.get(f"/api/invoices/order/{dtoken}").json()
        assert p["current"]["step"] == "issued" and c.get(p["current"]["files"][0]["url"]).status_code == 200


def test_settings_defaults_and_special_invoice(settings, notifier, tmp_path):
    """设置默认值照 Edison 11-18 的话（小规模、技术服务费、税率空、专票关），都标「待财务确认」；开了专票就多要四项。"""
    app = invoice_app(settings, notifier, tmp_path)
    with TestClient(app) as c:
        login(c)
        s = c.get("/api/admin/invoices/settings").json()
        cfg = s["config"]
        assert (cfg["taxpayer_type"], cfg["item_name"], cfg["tax_rate"], cfg["special_enabled"]) == ("小规模纳税人", "技术服务费", "", False)
        assert {"taxpayer_type", "tax_rate", "item_name", "special_enabled"} <= set(s["pending_finance"])
        _, oid, dtoken = web_order(c, app)
        complete(app, oid)
        r = apply_delivery(c, dtoken, kind="special")
        assert r.status_code == 422 and r.json()["field"] == "kind"
        r = c.put("/api/admin/invoices/settings", json={"config": {**cfg, "special_enabled": True, "confirmed_fields": ["item_name"]}})
        assert r.status_code == 200 and "item_name" not in r.json()["pending_finance"]
        assert [k["key"] for k in c.get("/api/invoices/config").json()["kinds"]] == ["normal", "special"]
        r = apply_delivery(c, dtoken, kind="special")
        assert r.status_code == 422 and r.json()["field"] == "bank_name"
        r = apply_delivery(c, dtoken, kind="special", bank_name="中国工商银行北京海淀支行", bank_account="0200 0045 0908 8888 888",
                           address="北京市海淀区清华园 1 号", phone="010-62770000")
        assert r.json()["exit"] == "requested", r.text
        assert c.put("/api/admin/invoices/settings", json={"config": {**cfg, "file_types": ["doc"]}}).status_code == 422
        assert _events(app, "invoice.config_changed")[0]["fields"]


def test_admin_edit_before_issue(settings, notifier, tmp_path):
    app = invoice_app(settings, notifier, tmp_path)
    with TestClient(app) as c:
        _, oid, dtoken = web_order(c, app)
        complete(app, oid)
        inv_id = apply_delivery(c, dtoken).json()["invoice_id"]
        login(c)
        r = c.patch(f"/api/admin/invoices/{inv_id}", json={**FIELDS, "tax_id": "12100000400000624X"})
        assert r.status_code == 422 and r.json()["field"] == "tax_id"
        assert c.patch(f"/api/admin/invoices/{inv_id}", json={**FIELDS, "title": "清华大学心理学系"}).status_code == 200
        assert admin_rows(c)[0]["title"] == "清华大学心理学系"
        assert _events(app, "invoice.edited")[0]["fields"] == ["title"]


def test_pay_page_apply_and_disabled(settings, notifier, tmp_path):
    """付款页没预填也能补填；没付的付款单看不了；设置关掉后网上不受理。"""
    app = invoice_app(settings, notifier, tmp_path)
    with TestClient(app) as c:
        token = checkout(c)
        assert c.post(f"/api/invoices/checkout/{token}").status_code == 409  # 还没付
        pay(c, app, token)
        p = c.post(f"/api/invoices/checkout/{token}").json()
        assert p["current"] is None and p["can_apply"] and p["apply_note"]
        r = c.post(f"/api/invoices/checkout/{token}/apply", json={"fields": FIELDS, "confirmed": True})
        assert r.json()["exit"] == "drafted"
        login(c)
        cfg = c.get("/api/admin/invoices/settings").json()["config"]
        c.put("/api/admin/invoices/settings", json={"config": {**cfg, "enabled": False}})
        _, _, dtoken = web_order(c, app)
        assert apply_delivery(c, dtoken).status_code == 409


def test_notice_goes_to_chat_when_claimed(settings, notifier, tmp_path):
    """认领过会话的单：开好后站内走订单中枢的发件接口（待发 outbox），邮件进待发。"""
    from app.intake import service as intake_service
    from app.intake.models import Outbox

    app = invoice_app(settings, notifier, tmp_path)
    with TestClient(app) as c:
        _, oid, dtoken = web_order(c, app)
        rt = get_runtime(app)
        with rt.database.session() as db:
            cust = intake_service.get_or_create_customer(db, "web", "key-invoice-0123456789", nickname="课题组")
            db.get(Order, oid).customer_id = cust.id
            db.commit()
        complete(app, oid)
        inv_id = apply_delivery(c, dtoken).json()["invoice_id"]
        login(c)
        assert issue(c, inv_id).json()["exit"] == "issued"
        with rt.database.session() as db:
            chans = {n.channel: n.status for n in db.scalars(select(InvoiceNotice).where(InvoiceNotice.invoice_id == inv_id))}
            assert chans == {"email": "pending", "chat": "queued"}
            ob = db.scalars(select(Outbox).where(Outbox.order_id == oid)).all()
            assert any("发票开好了" in (o.text or "") for o in ob)
