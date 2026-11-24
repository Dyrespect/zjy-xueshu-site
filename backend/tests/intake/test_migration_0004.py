"""迁移 intake_0004（订单中枢）：旧订单、旧码、旧设置迁过去不丢；能降回 intake_0003。

做法：库升到 intake_0003 → 用 SQL 灌几条 11-15 结构的旧数据（没付款的草稿、核销过码在排队的、做好了的、取消的）
→ 升到最新 → 查迁过来的值 → 再降回去。
"""

from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import command

from app.core.migrate import alembic_config

T = datetime(2026, 11, 15, 8, 0, tzinfo=timezone.utc).isoformat(sep=" ")


def _old_data(conn) -> None:
    ex = lambda sql, **kw: conn.execute(sa.text(sql), kw)  # noqa: E731
    for cid, key in ((1, "key-a"), (2, "key-b"), (3, "key-c"), (4, "key-d")):
        ex("INSERT INTO intake_customers (id, channel, external_id, open_kfid, nickname, source, human_takeover, note, "
           "last_activity_at, bot_seen_msg_id, created_at) VALUES (:id, 'web', :k, '', :n, '', 0, '', :t, 0, :t)",
           id=cid, k=key, n=f"客户{cid}", t=T)
    cols = ("id, customer_id, status, occasion, title, duration_default, duration_confirmed, present_date_text, school, language, "
            "structure_req, requirement_quotes, tier_key, quoted_price, terms_sent_at, code_id, redeemed_at, extra_revisions, "
            "paid, pay_later, rush, needs_edison, handoff_folder, delivery_round, revision_used, delivery_token, created_at, "
            "updated_at, cancelled_at, finished_at, delivered_at")
    rows = [
        # 没付款的草稿（收集中）
        (1, 1, "collecting", "组会文献", None, None, 0, "", "tok-1", None, None),
        # 核销过码、在排队
        (2, 2, "queued", "开题", "lit", T, 1, "", "tok-2", None, None),
        # 做好了（完成）
        (3, 3, "done", "会议", "res", T, 2, "", "tok-3", None, T),
        # 取消了
        (4, 4, "cancelled", "组会文献", "", None, None, "", "tok-4", T, None),
    ]
    for oid, cid, status, occ, tier, terms, code_id, _, tok, cancelled, finished in rows:
        ex(f"INSERT INTO intake_orders ({cols}) VALUES (:id, :cid, :st, :occ, '', 0, 0, '', '', '', '', '[]', :tier, '19.9', "
           ":terms, :code, :red, 0, 0, 0, 0, '[]', '', :round, 0, :tok, :t, :t, :canc, :fin, :deliv)",
           id=oid, cid=cid, st=status, occ=occ, tier=tier or "", terms=terms, code=code_id, red=T if code_id else None,
           round=1 if status == "done" else 0, tok=tok, t=T, canc=cancelled, fin=finished, deliv=T if status == "done" else None)
    ex("INSERT INTO intake_messages (id, customer_id, order_id, direction, sender, kind, text, asset, created_at) "
       "VALUES (1, 1, 1, 'in', 'customer', 'text', '我想做组会 PPT', '', :t)", t=T)
    ex("INSERT INTO intake_files (id, customer_id, order_id, role, filename, size, content_type, storage_key, purpose, note, round, created_at) "
       "VALUES (1, 1, 1, 'material', 'paper.pdf', 3, 'application/pdf', 'intake/1/paper.pdf', '论文', '', 0, :t)", t=T)
    for code_id, code, tier, status, order_id, cust in ((1, "PSY-AAAAAAAA2", "lit", "used", 2, 2), (2, "PSY-AAAAAAAA3", "res", "used", 3, 3),
                                                         (3, "PSY-AAAAAAAA4", "res_rush", "unused", None, None)):
        ex("INSERT INTO intake_activation_codes (id, code, tier_key, status, batch, note, order_id, customer_id, used_at, created_at) "
           "VALUES (:id, :c, :tier, :st, '20261115-1', '', :o, :cu, :used, :t)",
           id=code_id, c=code, tier=tier, st=status, o=order_id, cu=cust, used=T if order_id else None, t=T)
    ex("INSERT INTO intake_kv (key, value, updated_at) VALUES ('config', :v, :t)",
       v='{"schema_version": 2, "daily_quota": 4, "tiers": [{"key": "lit", "name": "文献·标准", "price": "19.9"}], '
         '"prices_tbd": true, "deliver_text": "我自己改过的交付说明"}', t=T)


def test_upgrade_keeps_old_data_then_downgrade(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = alembic_config(url)
    command.upgrade(cfg, "intake_0003")
    engine = sa.create_engine(url)
    with engine.begin() as conn:
        _old_data(conn)
    command.upgrade(cfg, "heads")
    with engine.connect() as conn:
        o = {r.id: r for r in conn.execute(sa.text(
            "SELECT id, flow_step, stage, platform, sku, tier_key, customer_id, voided_at, void_reason, finished_at FROM intake_orders"))}
        assert (o[1].flow_step, o[1].stage, o[1].platform) == ("", "", "")  # 没付款：旧草稿
        assert (o[2].flow_step, o[2].stage, o[2].platform, o[2].sku, o[2].tier_key) == ("collecting", "collecting", "legacy", "legacy-lit", "")
        assert (o[3].stage, o[3].sku) == ("delivered", "legacy-res") and o[3].finished_at is not None
        assert (o[4].stage, o[4].void_reason) == ("void", "return") and o[4].voided_at is not None  # cancelled_at → voided_at
        # 旧草稿的消息、材料解开挂回会话（认领新码时挂到新订单上）
        assert conn.execute(sa.text("SELECT order_id FROM intake_messages WHERE id = 1")).scalar() is None
        assert conn.execute(sa.text("SELECT order_id FROM intake_files WHERE id = 1")).scalar() is None
        # 条款发过没挪到会话上
        assert conn.execute(sa.text("SELECT terms_sent_at FROM intake_customers WHERE id = 2")).scalar() is not None
        codes = {r.code: r for r in conn.execute(sa.text("SELECT code, sku, platform, status FROM intake_activation_codes"))}
        assert codes["PSY-AAAAAAAA2"].sku == "legacy-lit" and codes["PSY-AAAAAAAA4"].sku == "legacy-res_rush"
        assert {c.platform for c in codes.values()} == {"fk"}
        reds = conn.execute(sa.text("SELECT code, order_id, customer_id, channel FROM intake_code_redemptions ORDER BY code")).all()
        assert [(r.code, r.order_id, r.customer_id, r.channel) for r in reds] == [("PSY-AAAAAAAA2", 2, 2, "web"), ("PSY-AAAAAAAA3", 3, 3, "web")]
        cols = {r[1] for r in conn.execute(sa.text("PRAGMA table_info(intake_orders)"))}
        assert {"status", "paid", "pay_later", "terms_sent_at", "cancelled_at"}.isdisjoint(cols)
    # 旧设置：文字和名额照留，档位换新默认
    from app.core.db import Database
    from app.intake.config_store import load_config

    db = Database(url)
    with db.session() as s:
        c = load_config(s)
        assert c.daily_quota == 4 and c.deliver_text == "我自己改过的交付说明"
        assert [t.name for t in c.duration_tiers] == ["轻量", "常规", "长", "超长"]
    db.dispose()
    command.downgrade(cfg, "intake_0003")
    with engine.connect() as conn:
        o = {r.id: r for r in conn.execute(sa.text("SELECT id, status, tier_key, cancelled_at FROM intake_orders"))}
        assert o[2].status == "confirming" and o[2].tier_key == "lit" and o[3].status == "done" and o[4].status == "cancelled"
        assert conn.execute(sa.text("SELECT tier_key FROM intake_activation_codes WHERE id = 3")).scalar() == "res_rush"
    engine.dispose()
