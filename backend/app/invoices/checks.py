"""开票会失败的检查（设计 docs/任务单/07_开票_设计.md 第七节 K1–K7）。

每条失败都说三件事：错在哪、怎么改、看哪份说明（InvoiceCheckFailed）。给客人看的只用前两件（public()）。
节点、接口、测试都调这里；backend/tests/invoices/test_checks.py 盯着每一条，scripts/check.py 规矩 16 盯着测试还在。
"""

from __future__ import annotations

import re
import zipfile
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Any

DOC = "docs/任务单/07_开票_设计.md"


class InvoiceCheckFailed(ValueError):
    def __init__(self, what: str, fix: str, see: str, *, field: str = "") -> None:
        self.what, self.fix, self.see, self.field = what, fix, see, field
        super().__init__(f"{what}。怎么改：{fix}。说明：{see}")

    def public(self) -> str:
        """给客人看的：错在哪 + 怎么改（不带内部文档）。"""
        return f"{self.what}。{self.fix}"

    def as_dict(self) -> dict[str, str]:
        return {"what": self.what, "fix": self.fix, "see": self.see, "field": self.field}


def money(v: Any) -> Decimal | None:
    """两位小数字符串、数字、Decimal → Decimal（两位小数）；空、坏的 → None。"""
    if v is None or v == "":
        return None
    try:
        d = Decimal(str(v).strip()).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None
    return d if d.is_finite() else None


def fmt(d: Decimal | None) -> str:
    return "" if d is None else f"{d:.2f}"


# ---------------------------------------------------------------- K2 税号格式

# 统一社会信用代码（GB 32100-2015）：18 位，字符表去掉 I O Z S V；第 18 位是校验码
_USCC_CHARS = "0123456789ABCDEFGHJKLMNPQRTUWXY"
_USCC_WEIGHTS = (1, 3, 9, 27, 19, 26, 16, 17, 20, 29, 25, 13, 8, 24, 10, 30, 28)
_TAX_ID_RE = re.compile(r"^[0-9A-Z]+$")


def normalize_tax_id(raw: str) -> str:
    return re.sub(r"[\s\-]", "", (raw or "")).upper()


def uscc_check_char(code17: str) -> str:
    s = sum(_USCC_CHARS.index(c) * w for c, w in zip(code17, _USCC_WEIGHTS, strict=True))
    r = 31 - s % 31
    return _USCC_CHARS[0 if r == 31 else r]


def require_tax_id(raw: str) -> str:
    """K2：纳税人识别号 15 / 18 / 20 位，只许数字和大写字母；18 位的按国标校验第 18 位。返回规整后的税号。"""
    tid = normalize_tax_id(raw)
    see = f"{DOC} 第七节 K2"
    if not tid:
        raise InvoiceCheckFailed("纳税人识别号没填", "单位抬头要填税号（统一社会信用代码），找单位财务要，一般是 18 位", see,
                                 field="tax_id")
    if not _TAX_ID_RE.match(tid):
        raise InvoiceCheckFailed(f"纳税人识别号里有不该有的字符（{tid[:24]}）", "税号只有数字和大写字母，不含空格、横线以外的符号", see,
                                 field="tax_id")
    if len(tid) not in (15, 18, 20):
        raise InvoiceCheckFailed(f"纳税人识别号是 {len(tid)} 位", "税号是 15、18 或 20 位（现在大多是 18 位的统一社会信用代码），再核对一遍",
                                 see, field="tax_id")
    if len(tid) == 18:
        bad = [c for c in tid if c not in _USCC_CHARS]
        if bad:
            raise InvoiceCheckFailed(f"18 位税号里不会出现字母 {'、'.join(dict.fromkeys(bad))}",
                                     "统一社会信用代码不含 I、O、Z、S、V，多半是把数字 1、0、2、5 抄成了字母", see, field="tax_id")
        if uscc_check_char(tid[:17]) != tid[17]:
            raise InvoiceCheckFailed("18 位税号的最后一位校验不对，多半是哪一位抄错了",
                                     "对着单位财务给的税号（或营业执照、事业单位法人证书）逐位再核一遍", see, field="tax_id")
    return tid


# ---------------------------------------------------------------- 字段校验（邮箱、长度、专票几项）

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$")
_ACCOUNT_RE = re.compile(r"^[0-9 \-]{6,40}$")
_PHONE_RE = re.compile(r"^[0-9+\-() ]{5,30}$")
_LIMITS = {"title": (2, 100), "bank_name": (2, 60), "address": (2, 120), "remark": (0, 100)}


def require_email(raw: str) -> str:
    email = (raw or "").strip()
    if not email or len(email) > 120 or not _EMAIL_RE.match(email):
        raise InvoiceCheckFailed(f"邮箱格式不对（{email[:40] or '没填'}）", "填一个能收信的邮箱，例如 name@example.edu.cn；发票开好会发到这里",
                                 f"{DOC} 第七节 K2", field="email")
    return email


def clean_fields(data: dict[str, Any], *, kind: str, title_kind: str, required: list[str], allow_remark: bool) -> dict[str, str]:
    """按发票类型校验客人填的东西，返回规整后的字段。第一处不对就抛 InvoiceCheckFailed（带 field）。"""
    see = f"{DOC} 第四节"
    out: dict[str, str] = {}
    for key in ("title", "tax_id", "email", "bank_name", "bank_account", "address", "phone", "remark"):
        out[key] = re.sub(r"\s+", " ", str(data.get(key) or "")).strip()
    if not allow_remark:
        out["remark"] = ""
    if kind == "special" and title_kind != "unit":
        raise InvoiceCheckFailed("专用发票只能开给单位", "抬头类型选「单位」，填单位全称和税号", see, field="title")
    labels = {"title": "抬头", "tax_id": "纳税人识别号", "email": "邮箱", "bank_name": "开户行", "bank_account": "银行账号",
              "address": "单位地址", "phone": "单位电话"}
    for key in required:
        if not out.get(key):
            raise InvoiceCheckFailed(f"{labels.get(key, key)}没填", f"{labels.get(key, key)}是这种发票必填的", see, field=key)
    for key, (lo, hi) in _LIMITS.items():
        v = out.get(key, "")
        if v and not lo <= len(v) <= hi:
            raise InvoiceCheckFailed(f"{labels.get(key, '备注')}的长度不对（{len(v)} 个字）", f"在 {lo}–{hi} 个字之间", see, field=key)
    if out["tax_id"] or "tax_id" in required:
        out["tax_id"] = require_tax_id(out["tax_id"])
    out["email"] = require_email(out["email"])
    if out["bank_account"]:
        if not _ACCOUNT_RE.match(out["bank_account"]):
            raise InvoiceCheckFailed("银行账号格式不对", "只填数字（可以带空格），照开户许可证或单位财务给的抄", see, field="bank_account")
        out["bank_account"] = re.sub(r"[\s\-]", "", out["bank_account"])
    if out["phone"] and not _PHONE_RE.match(out["phone"]):
        raise InvoiceCheckFailed("单位电话格式不对", "填数字，区号和分机可以用横线隔开，例如 0571-12345678", see, field="phone")
    return out


# ---------------------------------------------------------------- K3 金额不超过实付；K4 退款的不能开

def require_amount_within_paid(amount: Decimal | None, max_amount: Decimal | None) -> Decimal:
    see = f"{DOC} 第四节「开票金额 = 实付」、第七节 K3"
    if max_amount is None:
        raise InvoiceCheckFailed("这单查不到实付金额", "后台手工录的单先在订单上补实付，或在开票时填金额（不能超过客人真付的）", see)
    if amount is None or amount <= 0:
        raise InvoiceCheckFailed(f"开票金额不对（{fmt(amount) or '没填'}）", f"填大于 0、不超过 {fmt(max_amount)} 的金额", see)
    if amount > max_amount:
        raise InvoiceCheckFailed(f"开票金额 {fmt(amount)} 超过了实付 {fmt(max_amount)}（已扣掉退款）",
                                 f"改成不超过 {fmt(max_amount)}；客人付多少开多少，含税、不另加税", see)
    return amount


def require_not_refunded(*, fully_refunded: bool, refund_pending: bool, voided: bool, refunded: Decimal | None = None) -> None:
    see = f"{DOC} 第七节 K4"
    if voided or fully_refunded:
        raise InvoiceCheckFailed("这单已经退款（订单作废了）", "退了款的单不开票；已经开了的去后台作废", see)
    if refund_pending:
        raise InvoiceCheckFailed("这单正在退款或客人申请了退款", "等退款处理完（关掉或退成）再开；部分退款的按退后金额开", see)


# ---------------------------------------------------------------- K5 订单要到「已完成」

def require_completed(*, completed_at: Any, voided: bool) -> None:
    if voided or completed_at is None:
        raise InvoiceCheckFailed("这单还没到「已完成」", "等客人确认收货（或 3 天自动确认、平台确认）后再开，和发最终版是同一个关口，不先开票后退款",
                                 f"{DOC} 第七节 K5")


# ---------------------------------------------------------------- K1 下载校验订单归属

def require_owner(*, invoice_order_id: int | None, order_id: int | None, issued: bool) -> None:
    see = f"{DOC} 第七节 K1"
    if invoice_order_id is None or order_id is None or invoice_order_id != order_id:
        raise InvoiceCheckFailed("这张发票不是这一单的", "只能从自己这单的交付页（或付款结果页）下载", see)
    if not issued:
        raise InvoiceCheckFailed("这张发票现在不能下载（还没开好或已经作废）", "看页面上的发票进度；作废了的等重开", see)


# ---------------------------------------------------------------- K7 发票文件类型、大小

def sniff_kind(data: bytes) -> str:
    """按内容认：PDF（%PDF-）、OFD（zip 里有 OFD.xml）、XML（<?xml 或 < 开头）。认不出返回空。"""
    head = data[:2048].lstrip(b"\xef\xbb\xbf \t\r\n")
    if data[:5] == b"%PDF-":
        return "pdf"
    if data[:4] == b"PK\x03\x04":
        try:
            with zipfile.ZipFile(BytesIO(data)) as z:
                names = {n.lower() for n in z.namelist()}
        except zipfile.BadZipFile:
            return ""
        return "ofd" if "ofd.xml" in names else ""
    if head.startswith(b"<?xml") or (head.startswith(b"<") and not head[:20].lower().startswith((b"<!doctype html", b"<html"))):
        return "xml"
    return ""


def require_invoice_file(filename: str, data: bytes, *, allowed: list[str], max_mb: int) -> str:
    """K7：只收 PDF、OFD、XML（后缀和内容都要对上），单个不超过 max_mb。返回类型。"""
    see = f"{DOC} 第七节 K7"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in allowed:
        raise InvoiceCheckFailed(f"「{filename[:60]}」不是发票文件（后缀 {ext or '没有'}）", f"只收 {'、'.join(allowed).upper()}，从开票软件里下载原文件", see)
    if not data:
        raise InvoiceCheckFailed(f"「{filename[:60]}」是空文件", "重新下载一份再传", see)
    if len(data) > max_mb * 1024 * 1024:
        raise InvoiceCheckFailed(f"「{filename[:60]}」有 {len(data) / 1024 / 1024:.1f}MB，超过了 {max_mb}MB", "发票文件一般几百 KB；传开票软件给的原文件，别传截图或压缩包", see)
    kind = sniff_kind(data)
    if kind != ext:
        raise InvoiceCheckFailed(f"「{filename[:60]}」后缀是 {ext}，内容却不是（认成了 {kind or '别的东西'}）", "传开票软件导出的原文件，不要改后缀", see)
    return kind
