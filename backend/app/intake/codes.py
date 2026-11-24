"""激活码（付款凭证）：生成、规范化、原子领取、防撞库、退回、作废。认领的业务规则在 orders.claim（order.claim 节点）。

- 码长这样：`PSY-` + 9 位，字符表去掉了容易看错的 0 O 1 I L（31 个字符），用 secrets 随机（≈ 2^44.6）。
  Edison 11-18 定：保留现有格式。
- 每枚码有货号（sku）：基础货号对应一单，加购货号挂到一单上；同一笔带的加购写在 addons。
- 客户发来的码不区分大小写，带空格、横线、全角、夹在一句话里都认（`normalize_code`）。
- 领取第一条语句就是带条件的 UPDATE（没用、没过期、货号这时候能收 → 用了），rowcount 是 1 才算成：
  两个人同时拿同一个码，只有一个成。没成再查是哪种原因。成了以后订单中枢再插一行认领记录（code 唯一）。
- 防撞库：同一个会话 1 小时内错 5 次（码不对 / 用过了 / 作废了 / 过期了），锁 1 小时。货号对不上、旧码不算错。
"""

from __future__ import annotations

import re
import secrets
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.events import record_event
from app.intake import clock
from app.intake.models import ActivationCode, CodeAttempt, CodeRedemption

ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # 没有 0 O 1 I L
CODE_LEN = 9
PREFIX = "PSY-"
FAIL_LIMIT = 5
FAIL_WINDOW = timedelta(hours=1)
LOCK_FOR = timedelta(hours=1)
COUNTED = ("not_found", "used", "void", "expired")

_SEPARATORS = re.compile(r"[\s\-‐‑‒–—―−_·・.,，。:：;；'\"“”‘’()（）\[\]【】<>《》#/\\|]+")
_WITH_PREFIX = re.compile(rf"PSY([{ALPHABET}]{{{CODE_LEN}}})(?![{ALPHABET}])")
_BARE = re.compile(rf"[{ALPHABET}]{{{CODE_LEN}}}")

REASON_TEXT = {
    "not_found": "码不对（没有这个码）",
    "used": "这个码已经用过了",
    "void": "这个码已经作废了",
    "expired": "这个码过期了",
    "wrong": "这个码现在用不上",
    "legacy": "这是旧档位的码",
    "locked": "错太多次，锁住了",
}


def generate_code() -> str:
    return PREFIX + "".join(secrets.choice(ALPHABET) for _ in range(CODE_LEN))


def normalize_code(text: str) -> str | None:
    """客户发来的话 → 规范写法 PSY-XXXXXXXXX；认不出来返回 None。"""
    if not text:
        return None
    t = unicodedata.normalize("NFKC", text).upper()
    t = _SEPARATORS.sub("", t)
    m = _WITH_PREFIX.search(t)
    if m:
        return PREFIX + m.group(1)
    if _BARE.fullmatch(t):
        return PREFIX + t
    return None


def _unique_code(db: Session, taken: set[str]) -> str:
    while True:
        code = generate_code()
        if code in taken or db.scalar(select(func.count()).select_from(ActivationCode).where(ActivationCode.code == code)):
            continue
        taken.add(code)
        return code


def new_code(db: Session, *, sku: str, addons: list[str] | tuple[str, ...] = (), platform: str = "fk",
             platform_order_id: str | None = None, buyer_id: str = "", paid_at: datetime | None = None,
             paid_amount: str = "", batch: str = "", note: str = "", expires_at: datetime | None = None) -> ActivationCode:
    row = ActivationCode(code=_unique_code(db, set()), sku=sku, addons=list(addons), platform=platform,
                         platform_order_id=platform_order_id or None, buyer_id=buyer_id[:128], paid_at=paid_at,
                         paid_amount=paid_amount[:16], status="unused", batch=batch or next_batch_id(db),
                         note=note[:256], expires_at=expires_at, created_at=utcnow())
    db.add(row)
    db.flush()
    return row


def generate_batch(db: Session, *, sku: str, count: int, addons: list[str] | tuple[str, ...] = (), platform: str = "fk",
                   note: str = "", expires_at: datetime | None = None, by: str = "edison") -> tuple[str, list[ActivationCode]]:
    """按货号批量生成（码池：发卡站、闲鱼自动发货）。返回（批次号，码）。撞了已有的码就重抽。"""
    if not 1 <= count <= 2000:
        raise ValueError("一次生成 1 到 2000 个")
    batch = next_batch_id(db)
    taken: set[str] = set()
    rows = [ActivationCode(code=_unique_code(db, taken), sku=sku, addons=list(addons), platform=platform, status="unused",
                           batch=batch, note=note[:256], expires_at=expires_at, created_at=utcnow()) for _ in range(count)]
    db.add_all(rows)
    db.flush()
    record_event(db, "intake.code_generated", f"batch:{batch}",
                 {"sku": sku, "addons": list(addons), "count": count, "platform": platform, "note": note[:100], "by": by})
    return batch, rows


def next_batch_id(db: Session) -> str:
    """批次号：北京时间的日期 + 当天第几批，如 20261115-1（导出的文件名里带它）。"""
    day = clock.today().strftime("%Y%m%d")
    used = set(db.scalars(select(ActivationCode.batch).where(ActivationCode.batch.like(f"{day}-%")).distinct()))
    n = 1
    while f"{day}-{n}" in used:
        n += 1
    return f"{day}-{n}"


def export_csv(codes_: list[str]) -> str:
    """发卡站 Dujiao-Next 的卡密导入格式：UTF-8（不带 BOM），第一行表头只有一列 secret，下面一行一个码。"""
    return "secret\n" + "".join(f"{c}\n" for c in codes_)


def locked_until(db: Session, customer_id: int, now: datetime | None = None) -> datetime | None:
    """1 小时内错满 5 次：锁到第 5 次错之后 1 小时。没锁返回 None。"""
    now = now or utcnow()
    fails = list(db.scalars(
        select(CodeAttempt.created_at).where(
            CodeAttempt.customer_id == customer_id, CodeAttempt.counts.is_(True),
            CodeAttempt.created_at >= now - FAIL_WINDOW - LOCK_FOR,
        ).order_by(CodeAttempt.created_at)
    ))
    for i in range(len(fails) - FAIL_LIMIT + 1):
        window = fails[i:i + FAIL_LIMIT]
        if window[-1] - window[0] <= FAIL_WINDOW:
            until = window[-1] + LOCK_FOR
            if until > now:
                return until
    return None


def record_attempt(db: Session, customer_id: int, order_id: int | None, given: str, result: str) -> None:
    db.add(CodeAttempt(customer_id=customer_id, order_id=order_id, given=given[:64], result=result,
                       counts=result in COUNTED, created_at=utcnow()))


def fails_left(db: Session, customer_id: int, now: datetime | None = None) -> int:
    now = now or utcnow()
    fails = db.scalar(select(func.count()).select_from(CodeAttempt).where(
        CodeAttempt.customer_id == customer_id, CodeAttempt.counts.is_(True), CodeAttempt.created_at >= now - FAIL_WINDOW))
    return max(0, FAIL_LIMIT - (fails or 0))


@dataclass
class Taken:
    ok: bool
    row: ActivationCode | None
    code: str  # 规范写法；认不出来是空
    reason: str = ""  # 没领到：not_found | used | void | expired | wrong | legacy


def take(db: Session, *, given: str, customer_id: int, base_ok: bool, addon_skus: list[str]) -> Taken:
    """原子领取一枚码：没用、没过期、货号这时候能收（基础码 base_ok；加购码在 addon_skus 里）→ 用了。

    调用方负责提交事务，并且在这个会话里先别查别的：第一条语句就是带条件的 UPDATE（SQLite 上并发时
    后来的那个会等前一个提交再判断，不会读到旧的「没用」）。没领到再查原因。
    """
    now = utcnow()
    code = normalize_code(given)
    if code and (base_ok or addon_skus):
        accept = []
        if base_ok:
            accept.append(and_(~ActivationCode.sku.like("addon-%"), ~ActivationCode.sku.like("legacy-%")))
        if addon_skus:
            accept.append(ActivationCode.sku.in_(addon_skus))
        res = db.execute(
            update(ActivationCode)
            .where(ActivationCode.code == code, ActivationCode.status == "unused", or_(*accept),
                   (ActivationCode.expires_at.is_(None)) | (ActivationCode.expires_at > now))
            .values(status="used", customer_id=customer_id, used_at=now)
            .execution_options(synchronize_session=False)
        )
        if res.rowcount == 1:
            row = db.scalar(select(ActivationCode).where(ActivationCode.code == code))
            db.refresh(row)
            return Taken(True, row, code)
    row = db.scalar(select(ActivationCode).where(ActivationCode.code == code)) if code else None
    if row is None:
        return Taken(False, None, code or "", "not_found")
    if row.status == "void":
        return Taken(False, row, code, "void")
    if row.status == "used":
        return Taken(False, row, code, "used")
    if row.expires_at is not None and row.expires_at <= now:
        return Taken(False, row, code, "expired")
    if row.sku.startswith("legacy-"):
        return Taken(False, row, code, "legacy")
    return Taken(False, row, code, "wrong")


def redemption_of(db: Session, code: str) -> CodeRedemption | None:
    return db.scalar(select(CodeRedemption).where(CodeRedemption.code == code))


def return_code(db: Session, row: ActivationCode, *, why: str, by: str) -> None:
    """撤单退码：退回「没用」，解开会话（还能再用）；认领记录删掉，事件里留痕。"""
    if row.status == "used":
        row.status = "unused"
        row.customer_id = None
        row.used_at = None
        row.order_id = None  # 原来那单作废了；再认领时按码上的平台信息另建一单
    db.execute(delete(CodeRedemption).where(CodeRedemption.code == row.code))
    record_event(db, "intake.code_returned", f"code:{row.id}", {"code": row.code, "why": why[:200], "by": by})


def void_for_refund(db: Session, row: ActivationCode, *, why: str, by: str) -> None:
    """退款：码作废（不管用没用过）。"""
    if row.status != "void":
        row.status = "void"
        row.voided_at = utcnow()
    record_event(db, "admin.code_voided", f"code:{row.id}", {"code": row.code, "why": why[:200], "by": by})


def void(db: Session, row: ActivationCode, *, by: str = "edison") -> ActivationCode:
    """后台手动作废：只有没用的能作废（用了的跟着订单作废走）。"""
    if row.status != "unused":
        raise ValueError(f"这个码现在是「{'用了' if row.status == 'used' else '作废'}」，只有没用的能作废")
    row.status = "void"
    row.voided_at = utcnow()
    record_event(db, "admin.code_voided", f"code:{row.id}", {"code": row.code, "why": "后台手动作废", "by": by})
    return row
