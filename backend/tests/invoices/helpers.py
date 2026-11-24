"""开票测试共用：建 app（假网关、定时任务关掉）、下一单网页单并付款、把单推到「已完成」、造发票文件。不联网、不读 .env。"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core.db import utcnow
from app.core.nodes import NodeCall, run_node
from app.intake import flow, orders, pricing
from app.intake.adapters import PaidIn
from app.intake.config_store import load_config
from app.intake.models import Order
from app.intake.runtime import get_runtime
from app.invoices.settings import InvoiceSettings
from app.shop.gateways import fake
from app.shop.models import ShopCheckout
from app.shop.runtime import get_shop
from tests.conftest import TEST_PASSWORD
from tests.shop.helpers import PC_UA, checkout_body, make_shop_app

# 清华大学的统一社会信用代码（公开信息，校验位对得上）
FIELDS: dict[str, Any] = {"kind": "normal", "title_kind": "unit", "title": "清华大学", "tax_id": "12100000400000624D",
                          "email": "lab@example.edu.cn"}
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
XML = '<?xml version="1.0" encoding="UTF-8"?><EInvoice><Header/></EInvoice>'.encode()


def ofd_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("OFD.xml", "<ofd:OFD/>")
        z.writestr("Doc_0/Document.xml", "<ofd:Document/>")
    return buf.getvalue()


def invoice_app(settings, notifier, tmp_path: Path, **over: Any):
    app = make_shop_app(settings, notifier, tmp_path)
    values: dict[str, Any] = dict(INVOICE_TIMER_ENABLED=False, INVOICE_PUBLIC_HOURLY_LIMIT=100000)
    values.update(over)
    app.state.invoice_settings = InvoiceSettings(_env_file=None, **values)
    return app


def login(c) -> None:
    assert c.post("/api/auth/login", json={"password": TEST_PASSWORD}).status_code == 200


def checkout(c) -> str:
    """下单（还没付）→ 付款页令牌。"""
    r = c.post("/api/shop/checkout", json=checkout_body(), headers={"user-agent": PC_UA})
    assert r.status_code == 200, r.text
    return r.json()["view_token"]


def pay(c, app, view_token: str) -> int:
    """假网关付款 → 订单号。"""
    rt = get_runtime(app)
    with rt.database.session() as db:
        row = db.scalar(select(ShopCheckout).where(ShopCheckout.view_token == view_token))
        trade = row.out_trade_no
    raw = fake.simulate_pay(get_shop(app), trade)
    assert c.post("/api/shop/pay/fake/notify", content=raw).status_code == 200
    with rt.database.session() as db:
        return db.scalar(select(ShopCheckout).where(ShopCheckout.view_token == view_token)).order_id


def web_order(c, app) -> tuple[str, int, str]:
    """下单 + 付款 →（付款页令牌, 订单号, 交付页令牌）。"""
    token = checkout(c)
    oid = pay(c, app, token)
    with get_runtime(app).database.session() as db:
        return token, oid, db.get(Order, oid).delivery_token


def platform_order(app, platform: str = "xhs", sku: str = "regular-p1") -> tuple[int, str]:
    """平台人工录单那样建的一单（已付款，没认领）→（订单号, 交付页令牌）。"""
    rt = get_runtime(app)
    with rt.database.session() as db:
        price = pricing.sku_price(load_config(db), sku)
        res = orders.receive_paid(db, rt.ctx, PaidIn(platform=platform, platform_order_id=f"P{utcnow().timestamp()}", sku=sku,
                                                     addons=[], buyer_id="b1", paid_amount=f"{price:.2f}", raw_ref="test"), by="test")
        db.commit()
        return res.order.id, res.order.delivery_token


def complete(app, order_id: int) -> None:
    """把单放到「已交水印版」，客人点确认收货 → 已完成（走 confirm.receipt，completed_at 是真写的）。"""
    rt = get_runtime(app)
    with rt.database.session() as db:
        o = db.get(Order, order_id)
        flow.seed_stage(o, "watermarked")
        o.delivered_at, o.delivery_round = utcnow(), 1
        db.commit()
        source = "customer" if o.platform in ("web", "fk", "manual") else "edison"
        r = run_node("confirm.receipt", NodeCall(db, rt.ctx, "test", o.id), {"order_id": o.id, "source": source})
        assert r.exit == "completed", (r.exit, r.detail)
        db.commit()
        assert db.get(Order, order_id).completed_at is not None


def apply_delivery(c, delivery_token: str, **over: Any):
    fields = {**FIELDS, **over}
    return c.post(f"/api/invoices/order/{delivery_token}/apply", json={"fields": fields, "confirmed": True})


def admin_rows(c, status: str = "pending") -> list[dict]:
    r = c.get("/api/admin/invoices", params={"status": status})
    assert r.status_code == 200, r.text
    return r.json()["rows"]


def issue(c, invoice_id: int, *, files: list[tuple[str, bytes]] | None = None, amount: str = ""):
    files = files if files is not None else [("发票.pdf", PDF)]
    return c.post(f"/api/admin/invoices/{invoice_id}/issue", data={"amount": amount, "invoice_no": "26330000000012345678"},
                  files=[("files", (n, d, "application/octet-stream")) for n, d in files])
