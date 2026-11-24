"""激活码（不调模型）：按货号生成、格式（PSY- + 9 位）、规范化、认领原子性（并发两次只成一次）、用过 / 作废 / 过期 /
用不上 / 旧码、防撞库锁、发卡站 CSV。认领的业务规则在 orders.claim。"""

from __future__ import annotations

import re
import threading
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.db import utcnow
from app.intake import codes, orders, service
from app.intake.models import ActivationCode, CodeAttempt, CodeRedemption, Order
from tests.intake.helpers import make_ctx

CODE_RE = re.compile(r"^PSY-[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{9}$")


@pytest.fixture
def ctx(tmp_path, notifier):
    return make_ctx(tmp_path, notifier)


def _codes(database, n=1, sku="regular-p1", **kw) -> list[str]:
    with database.session() as db:
        _, rows = codes.generate_batch(db, sku=sku, count=n, **kw)
        return [r.code for r in rows]


def _customer(database, name="甲") -> int:
    with database.session() as db:
        return service.get_or_create_customer(db, "web", f"key-{name}-0123456789", nickname=name).id


def _claim(database, ctx, cid, code):
    from app.intake.models import Customer

    with database.session() as db:
        return orders.claim(db, ctx, db.get(Customer, cid), code, channel="web")


def test_generate_format_sku_and_batch_ids(database):
    with database.session() as db:
        b1, rows = codes.generate_batch(db, sku="regular-p1", count=200, note="发卡站第一批")
        b2, rows2 = codes.generate_batch(db, sku="addon-rush", count=3, platform="xy")
    assert all(CODE_RE.match(r.code) for r in rows)
    assert not any(ch in r.code[4:] for r in rows for ch in "0O1IL")
    assert len({r.code for r in rows}) == 200
    day = b1.split("-")[0]
    assert re.fullmatch(r"\d{8}", day) and b1 == f"{day}-1" and b2 == f"{day}-2"
    assert {r.status for r in rows} == {"unused"} and rows[0].note == "发卡站第一批" and rows[0].sku == "regular-p1"
    assert rows2[0].platform == "xy"


@pytest.mark.parametrize(
    "given,expect",
    [
        ("PSY-K7QM4XWDR", "PSY-K7QM4XWDR"),
        ("psy-k7qm4xwdr", "PSY-K7QM4XWDR"),
        ("psy k7qm 4xwdr", "PSY-K7QM4XWDR"),
        ("ＰＳＹ－Ｋ７ＱＭ　４ＸＷＤＲ", "PSY-K7QM4XWDR"),
        ("我的激活码是 psy—k7qm—4xwdr，麻烦核销一下", "PSY-K7QM4XWDR"),
        ("k7qm4xwdr", "PSY-K7QM4XWDR"),
        ("PSY-K7QM4XWD", None),
        ("PSY-K7QM4XWDRA", None),
        ("PSY-K7QM4XWD0", None),
        ("还没买码", None),
        ("", None),
    ],
)
def test_normalize(given, expect):
    assert codes.normalize_code(given) == expect


def test_concurrent_claim_only_one_wins(database, ctx):
    """两个会话同时拿同一个码：第一条语句就是带条件的 UPDATE，只有一个成；认领记录只有一行。"""
    a, b = _customer(database, "甲"), _customer(database, "乙")
    (code,) = _codes(database)
    barrier = threading.Barrier(2)
    results: dict[str, orders.ClaimResult] = {}
    errors: list[BaseException] = []

    def worker(tag, cid):
        try:
            barrier.wait()
            results[tag] = _claim(database, ctx, cid, code)
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=("a", a)), threading.Thread(target=worker, args=("b", b))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert not errors
    oks = [k for k, r in results.items() if r.ok]
    assert len(oks) == 1
    loser = "b" if oks == ["a"] else "a"
    assert results[loser].result == "used"
    with database.session() as db:
        assert len(list(db.scalars(select(CodeRedemption)))) == 1
        row = db.scalar(select(ActivationCode).where(ActivationCode.code == code))
        assert sum(1 for o in db.scalars(select(Order)) if o.code_id == row.id) == 1


def test_used_void_expired_legacy_wrong(database, ctx):
    cid = _customer(database)
    used, void, old = _codes(database, 3)
    other = _customer(database, "别人")
    assert _claim(database, ctx, other, used).ok
    with database.session() as db:
        codes.void(db, db.scalar(select(ActivationCode).where(ActivationCode.code == void)))
        db.scalar(select(ActivationCode).where(ActivationCode.code == old)).expires_at = utcnow() - timedelta(days=1)
        legacy = ActivationCode(code="PSY-HHHHHHHHH", sku="legacy-lit", status="unused", batch="old", created_at=utcnow())
        db.add(legacy)
    assert _claim(database, ctx, cid, used).result == "used"
    assert _claim(database, ctx, cid, void).result == "void"
    assert _claim(database, ctx, cid, old).result == "expired"
    r = _claim(database, ctx, cid, "PSY-HHHHHHHHH")
    assert r.result == "legacy" and "旧档" in r.detail
    (addon,) = _codes(database, sku="addon-revision")
    r = _claim(database, ctx, cid, addon)
    assert r.result == "wrong" and "先认领基础档" in r.detail
    with database.session() as db:
        attempts = [(a.result, a.counts) for a in db.scalars(select(CodeAttempt).where(CodeAttempt.customer_id == cid)
                                                               .order_by(CodeAttempt.id))]
        assert attempts == [("used", True), ("void", True), ("expired", True), ("legacy", False), ("wrong", False)]


def test_five_fails_in_an_hour_locks_for_an_hour(database, ctx):
    cid = _customer(database)
    for i in range(4):
        r = _claim(database, ctx, cid, f"PSY-AAAAAAA{i + 2}")
        assert r.result == "not_found" and r.locked_until is None
    assert r.fails_left == 1
    r = _claim(database, ctx, cid, "PSY-BBBBBBBBB")
    assert r.locked_until is not None and timedelta(minutes=59) < r.locked_until - utcnow() <= timedelta(hours=1)
    with database.session() as db:
        assert codes.locked_until(db, cid) is not None
        for a in db.scalars(select(CodeAttempt)):
            a.created_at = a.created_at - timedelta(hours=2, minutes=1)
        db.flush()
        assert codes.locked_until(db, cid) is None
        other = service.get_or_create_customer(db, "web", "key-other-0123456789")
        assert codes.locked_until(db, other.id) is None


def test_export_csv_is_dujiao_format():
    text = codes.export_csv(["PSY-K7QM4XWD", "PSY-23456789"])
    assert text == "secret\nPSY-K7QM4XWD\nPSY-23456789\n"
    assert codes.export_csv([]) == "secret\n"
