"""开票会失败的检查（设计第七节）：每条好例子过、坏例子报错，失败信息三件都在。"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.invoices import checks
from app.invoices.checks import InvoiceCheckFailed
from tests.invoices.helpers import PDF, XML, ofd_bytes


def _three(e: InvoiceCheckFailed) -> None:
    assert e.what and e.fix and e.see.startswith("docs/任务单/07_开票_设计.md")


def test_tax_id_format_rules():
    """K2：15 / 18 / 20 位，只许数字和大写字母；18 位按 GB 32100 校验第 18 位。"""
    assert checks.require_tax_id("91330110MAKFUNHCXY") == "91330110MAKFUNHCXY"  # 竹涧云
    assert checks.require_tax_id(" 91330110makfunhcxy ") == "91330110MAKFUNHCXY"  # 小写、空格规整
    assert checks.require_tax_id("9133-0110-MAKF-UNHCXY") == "91330110MAKFUNHCXY"
    assert checks.require_tax_id("12100000400000624D") == "12100000400000624D"  # 事业单位（高校）
    assert checks.require_tax_id("330100123456789") == "330100123456789"  # 旧 15 位
    assert checks.require_tax_id("33010012345678901234") == "33010012345678901234"  # 旧 20 位
    bad = {
        "": "没填",
        "91330110MAKFUNHCX": "17 位",
        "91330110MAKFUNHCXYZ": "19 位",
        "91330110MAKFUNHCX#": "不该有的字符",
        "91330110MAKFUNHCXI": "不会出现字母",  # 18 位里不会有 I
        "91330110MAKFUNHCXA": "校验不对",  # 最后一位抄错
        "91330110MAKFUNHDXY": "校验不对",  # 中间一位抄错
    }
    for raw, hint in bad.items():
        with pytest.raises(InvoiceCheckFailed) as ei:
            checks.require_tax_id(raw)
        assert hint in ei.value.what, (raw, ei.value.what)
        assert ei.value.field == "tax_id"
        _three(ei.value)


def test_email_and_fields():
    assert checks.require_email("lab@example.edu.cn") == "lab@example.edu.cn"
    for bad in ("", "lab", "lab@", "lab@example", "a b@example.com"):
        with pytest.raises(InvoiceCheckFailed):
            checks.require_email(bad)
    out = checks.clean_fields({"title": " 清华大学  ", "tax_id": "12100000400000624d", "email": "x@y.cn", "remark": "项目 123"},
                              kind="normal", title_kind="unit", required=["title", "tax_id", "email"], allow_remark=False)
    assert out["title"] == "清华大学" and out["tax_id"] == "12100000400000624D" and out["remark"] == ""
    with pytest.raises(InvoiceCheckFailed) as ei:  # 专票缺开户行
        checks.clean_fields({"title": "清华大学", "tax_id": "12100000400000624D", "email": "x@y.cn"}, kind="special",
                            title_kind="unit", required=["title", "tax_id", "email", "bank_name"], allow_remark=True)
    assert ei.value.field == "bank_name"
    with pytest.raises(InvoiceCheckFailed):  # 专票不能开给个人
        checks.clean_fields({"title": "张三", "email": "x@y.cn"}, kind="special", title_kind="personal", required=["title"],
                            allow_remark=True)


def test_amount_rules_unit():
    """K3 的纯函数部分（接口那一半在 test_amount_cannot_exceed_paid）。"""
    assert checks.require_amount_within_paid(Decimal("39.80"), Decimal("39.80")) == Decimal("39.80")
    for amount, cap in ((Decimal("39.81"), Decimal("39.80")), (Decimal("0.00"), Decimal("39.80")), (None, Decimal("1.00")),
                        (Decimal("1.00"), None)):
        with pytest.raises(InvoiceCheckFailed) as ei:
            checks.require_amount_within_paid(amount, cap)
        _three(ei.value)


def test_refund_and_completed_rules_unit():
    with pytest.raises(InvoiceCheckFailed) as ei:
        checks.require_not_refunded(fully_refunded=True, refund_pending=False, voided=False)
    _three(ei.value)
    with pytest.raises(InvoiceCheckFailed):
        checks.require_not_refunded(fully_refunded=False, refund_pending=True, voided=False)
    checks.require_not_refunded(fully_refunded=False, refund_pending=False, voided=False)
    with pytest.raises(InvoiceCheckFailed):
        checks.require_completed(completed_at=None, voided=False)
    with pytest.raises(InvoiceCheckFailed):
        checks.require_owner(invoice_order_id=1, order_id=2, issued=True)
    with pytest.raises(InvoiceCheckFailed):
        checks.require_owner(invoice_order_id=1, order_id=1, issued=False)
    checks.require_owner(invoice_order_id=1, order_id=1, issued=True)


def test_invoice_file_type_and_size():
    """K7：只收 PDF、OFD、XML，后缀和内容都要对上；单个不超过设置的大小。"""
    allowed = ["pdf", "ofd", "xml"]
    assert checks.require_invoice_file("发票.pdf", PDF, allowed=allowed, max_mb=10) == "pdf"
    assert checks.require_invoice_file("发票.OFD", ofd_bytes(), allowed=allowed, max_mb=10) == "ofd"
    assert checks.require_invoice_file("发票.xml", b"\xef\xbb\xbf" + XML, allowed=allowed, max_mb=10) == "xml"
    bad = [
        ("发票.docx", b"PK\x03\x04", "不是发票文件"),
        ("发票.pdf", b"<html><body>hi</body></html>", "内容却不是"),  # 网页改了后缀
        ("发票.xml", b"<!DOCTYPE html><html></html>", "内容却不是"),
        ("发票.ofd", b"PK\x03\x04not-a-zip", "内容却不是"),
        ("发票.pdf", b"", "空文件"),
        ("发票.pdf", PDF + b"0" * (1024 * 1024), "超过了 1MB"),
        ("发票", PDF, "不是发票文件"),
    ]
    for name, data, hint in bad:
        with pytest.raises(InvoiceCheckFailed) as ei:
            checks.require_invoice_file(name, data, allowed=allowed, max_mb=1)
        assert hint in ei.value.what, (name, ei.value.what)
        _three(ei.value)
    with pytest.raises(InvoiceCheckFailed):  # 设置里关掉了 xml
        checks.require_invoice_file("发票.xml", XML, allowed=["pdf"], max_mb=10)
