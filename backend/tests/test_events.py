from datetime import timezone

import pytest

from app.core.events import Event, list_events, record_event


def test_record_and_read_back(database):
    with database.session() as db:
        ev = record_event(db, "intake.message_received", "customer:wx_1", {"text": "老师要 15 分钟", "n": 1})
        assert ev.id is not None
    with database.session() as db:
        got = db.get(Event, ev.id)
        assert got.type == "intake.message_received"
        assert got.subject == "customer:wx_1"
        assert got.content == {"text": "老师要 15 分钟", "n": 1}
        assert got.created_at.tzinfo is not None
        assert got.created_at.utcoffset() == timezone.utc.utcoffset(None)


def test_record_does_not_commit_by_itself(database):
    db = database.sessionmaker()
    record_event(db, "test.rollback", "x:1")
    db.rollback()
    db.close()
    with database.session() as db2:
        assert list_events(db2, type="test.rollback") == []


def test_list_events_filters_and_order(database):
    with database.session() as db:
        for i in range(3):
            record_event(db, "t.a", "order:1", {"i": i})
        record_event(db, "t.b", "order:2")
    with database.session() as db:
        evs = list_events(db, subject="order:1")
        assert [e.content["i"] for e in evs] == [2, 1, 0]
        assert len(list_events(db, type="t.b")) == 1
        assert len(list_events(db, limit=2)) == 2


def test_chinese_stored_readably(database):
    """JSON 里的中文按原样存（不转成 \\uXXXX），直接看库也读得懂。"""
    from sqlalchemy import Text, cast, select

    with database.session() as db:
        record_event(db, "t.zh", "", {"话": "你好"})
    with database.engine.connect() as conn:  # 按文本读出来（PG 的驱动会把 json 列直接解析成 dict）
        raw = conn.execute(select(cast(Event.content, Text)).where(Event.type == "t.zh")).scalar_one()
    assert "你好" in raw


@pytest.mark.parametrize("bad_type", ["", "x" * 65])
def test_bad_type_rejected(database, bad_type):
    with database.session() as db, pytest.raises(ValueError):
        record_event(db, bad_type)
