"""订单中枢（11-18）：订单在付款时建、状态 = 流程步骤（flow_key / flow_step / stage）、货号（时长档 × 篇数档 + 加购）、
平台字段、作废和暂停、认领记录表；会话加记忆列；激活码按货号；成品加页码；改稿逐页。

旧数据怎么迁（不丢）：
- 订单：旧 status → 流程步骤。付过的（核销过码、后台标了已付 / 先做后付）按进度放：没开工 → 收资料，开工 → 制作中，
  交过 → 已交水印版，改稿中 → 修改中，完成 → 已交付，取消 → 作废；没付过、没开工的是「旧草稿」（flow_step 空），
  它们的消息和材料解开挂回会话（认领新码时再挂到新订单上）。旧档位 lit / res 这类挪进 sku = legacy-<旧档>。
  terms_sent_at 挪到会话上；cancelled_at 改名 voided_at。
- 激活码：tier_key → sku = legacy-<旧档>，平台记 fk（发卡站）；用过的补一行认领记录。

Revision ID: intake_0004
Revises: intake_0003
Create Date: 2026-11-18 02:35:27.144600
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'intake_0004'
down_revision: Union[str, Sequence[str], None] = 'intake_0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 旧 status → (flow_step, stage)；付过的才进流程
STATUS_TO_STEP = {
    "new": "collecting", "collecting": "collecting", "confirming": "collecting", "awaiting_payment": "collecting",
    "queued": "collecting", "in_production": "making", "ready": "making", "delivered": "watermarked",
    "revising": "revising", "done": "delivered", "cancelled": "void",
}
STEP_TO_STATUS = {
    "": "collecting", "paid": "confirming", "claimed": "confirming", "collecting": "confirming", "gate": "confirming",
    "making": "in_production", "proofing": "in_production", "publish": "in_production", "watermarked": "delivered",
    "revising": "revising", "revising_after": "revising", "confirm": "done", "completed": "done", "delivered": "done",
    "void": "cancelled",
}


def upgrade() -> None:
    bind = op.get_bind()

    # ---- 认领记录（新表）
    op.create_table('intake_code_redemptions',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('code', sa.String(length=16), nullable=False),
    sa.Column('code_id', sa.Integer(), nullable=False),
    sa.Column('order_id', sa.Integer(), nullable=True),
    sa.Column('customer_id', sa.Integer(), nullable=False),
    sa.Column('channel', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_intake_code_redemptions')),
    sa.UniqueConstraint('code', name=op.f('uq_intake_code_redemptions_code'))
    )
    with op.batch_alter_table('intake_code_redemptions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_intake_code_redemptions_customer_id'), ['customer_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_intake_code_redemptions_order_id'), ['order_id'], unique=False)

    # ---- 会话：记忆列、条款发过没
    with op.batch_alter_table('intake_customers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('terms_sent_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('person_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('memory_brief', sa.Text(), server_default='', nullable=False))
        batch_op.add_column(sa.Column('handoff_brief', sa.Text(), server_default='', nullable=False))
        batch_op.create_index(batch_op.f('ix_intake_customers_person_id'), ['person_id'], unique=False)

    # ---- 激活码：先加列、填 sku，再删 tier_key
    with op.batch_alter_table('intake_activation_codes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('sku', sa.String(length=48), server_default='', nullable=False))
        batch_op.add_column(sa.Column('addons', sa.JSON(), server_default='[]', nullable=False))
        batch_op.add_column(sa.Column('platform', sa.String(length=16), server_default='fk', nullable=False))
        batch_op.add_column(sa.Column('platform_order_id', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('buyer_id', sa.String(length=128), server_default='', nullable=False))
        batch_op.add_column(sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('paid_amount', sa.String(length=16), server_default='', nullable=False))
    bind.execute(sa.text("UPDATE intake_activation_codes SET sku = 'legacy-' || tier_key WHERE tier_key != ''"))
    with op.batch_alter_table('intake_activation_codes', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_intake_activation_codes_tier_key'))
        batch_op.create_index(batch_op.f('ix_intake_activation_codes_sku'), ['sku'], unique=False)
        batch_op.create_unique_constraint(batch_op.f('uq_intake_activation_codes_platform'), ['platform', 'platform_order_id'])
        batch_op.drop_column('tier_key')

    # ---- 成品页码、改稿逐页
    with op.batch_alter_table('intake_files', schema=None) as batch_op:
        batch_op.add_column(sa.Column('page_no', sa.Integer(), nullable=True))
    with op.batch_alter_table('intake_revisions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('items', sa.JSON(), server_default='[]', nullable=False))
        batch_op.add_column(sa.Column('based_on_round', sa.Integer(), server_default='0', nullable=False))

    # ---- 订单：先加新列
    with op.batch_alter_table('intake_orders', schema=None) as batch_op:
        batch_op.add_column(sa.Column('flow_key', sa.String(length=32), server_default='paid_custom', nullable=False))
        batch_op.add_column(sa.Column('flow_step', sa.String(length=32), server_default='', nullable=False))
        batch_op.add_column(sa.Column('stage', sa.String(length=16), server_default='', nullable=False))
        batch_op.add_column(sa.Column('stage_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('voided_from', sa.String(length=16), server_default='', nullable=False))
        batch_op.add_column(sa.Column('void_reason', sa.String(length=16), server_default='', nullable=False))
        batch_op.add_column(sa.Column('hold_reason', sa.String(length=64), server_default='', nullable=False))
        batch_op.add_column(sa.Column('hold_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('platform', sa.String(length=16), server_default='', nullable=False))
        batch_op.add_column(sa.Column('source', sa.String(length=64), server_default='', nullable=False))
        batch_op.add_column(sa.Column('platform_order_id', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('buyer_id', sa.String(length=128), server_default='', nullable=False))
        batch_op.add_column(sa.Column('paid_amount', sa.String(length=16), server_default='', nullable=False))
        batch_op.add_column(sa.Column('sku', sa.String(length=48), server_default='', nullable=False))
        batch_op.add_column(sa.Column('band_key', sa.String(length=16), server_default='', nullable=False))
        batch_op.add_column(sa.Column('addons', sa.JSON(), server_default='[]', nullable=False))
        batch_op.add_column(sa.Column('wechat_external_userid', sa.String(length=128), server_default='', nullable=False))
        batch_op.add_column(sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('paper_count', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('page_count', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('due_hours', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('platform_completed_at', sa.DateTime(timezone=True), nullable=True))

    # ---- 订单：搬数据
    rows = bind.execute(sa.text(
        "SELECT id, customer_id, status, tier_key, code_id, paid, pay_later, paid_at, redeemed_at, cancelled_at, "
        "terms_sent_at, updated_at, delivered_at FROM intake_orders")).mappings().all()
    for r in rows:
        paid_like = bool(r["code_id"]) or bool(r["paid"]) or bool(r["pay_later"])
        status = r["status"] or "new"
        started = status in ("in_production", "ready", "delivered", "revising", "done")
        if status == "cancelled":
            step = "void"
        elif paid_like or started:
            step = STATUS_TO_STEP.get(status, "collecting")
        else:
            step = ""  # 旧草稿：没付款就建的单
        tier = r["tier_key"] or ""
        bind.execute(sa.text(
            "UPDATE intake_orders SET flow_step = :step, stage = :stage, stage_at = :at, platform = :platform, "
            "sku = :sku, tier_key = '', claimed_at = :claimed, voided_from = :vfrom, void_reason = :vreason "
            "WHERE id = :id"), {
            "step": step, "stage": step, "at": r["updated_at"], "platform": "legacy" if (paid_like or started) else "",
            "sku": f"legacy-{tier}" if tier else "", "claimed": r["redeemed_at"] or r["paid_at"],
            "vfrom": "" if step != "void" else "collecting", "vreason": "return" if step == "void" else "", "id": r["id"],
        })
        if r["terms_sent_at"] is not None:
            bind.execute(sa.text(
                "UPDATE intake_customers SET terms_sent_at = :t WHERE id = :c AND terms_sent_at IS NULL"),
                {"t": r["terms_sent_at"], "c": r["customer_id"]})
        if step == "":  # 旧草稿的消息、材料解开挂回会话，认领新码时挂到新订单上
            bind.execute(sa.text("UPDATE intake_messages SET order_id = NULL WHERE order_id = :id"), {"id": r["id"]})
            bind.execute(sa.text("UPDATE intake_files SET order_id = NULL WHERE order_id = :id AND role IN ('material', 'voice')"),
                         {"id": r["id"]})
    bind.execute(sa.text("UPDATE intake_orders SET finished_at = COALESCE(finished_at, updated_at) WHERE flow_step = 'delivered'"))

    # ---- 订单：删旧列、改名、customer_id 可空
    with op.batch_alter_table('intake_orders', schema=None) as batch_op:
        batch_op.alter_column('cancelled_at', new_column_name='voided_at', existing_type=sa.DateTime(timezone=True),
                              existing_nullable=True)
        batch_op.alter_column('customer_id', existing_type=sa.INTEGER(), nullable=True)
        batch_op.drop_index(batch_op.f('ix_intake_orders_status'))
        batch_op.create_index(batch_op.f('ix_intake_orders_platform'), ['platform'], unique=False)
        batch_op.create_index(batch_op.f('ix_intake_orders_platform_order_id'), ['platform_order_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_intake_orders_stage'), ['stage'], unique=False)
        batch_op.drop_column('status')
        batch_op.drop_column('terms_sent_at')
        batch_op.drop_column('pay_later')
        batch_op.drop_column('paid')

    # ---- 用过的码补认领记录
    used = bind.execute(sa.text(
        "SELECT a.id, a.code, a.order_id, a.customer_id, a.used_at, a.created_at, c.channel FROM intake_activation_codes a "
        "LEFT JOIN intake_customers c ON c.id = a.customer_id WHERE a.status = 'used' AND a.customer_id IS NOT NULL")).mappings().all()
    for u in used:
        bind.execute(sa.text(
            "INSERT INTO intake_code_redemptions (code, code_id, order_id, customer_id, channel, created_at) "
            "VALUES (:code, :cid, :oid, :cust, :ch, :at)"), {
            "code": u["code"], "cid": u["id"], "oid": u["order_id"], "cust": u["customer_id"],
            "ch": u["channel"] or "web", "at": u["used_at"] or u["created_at"]})


def downgrade() -> None:
    bind = op.get_bind()
    with op.batch_alter_table('intake_orders', schema=None) as batch_op:
        batch_op.add_column(sa.Column('status', sa.String(length=24), server_default='new', nullable=False))
        batch_op.add_column(sa.Column('paid', sa.Boolean(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('pay_later', sa.Boolean(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('terms_sent_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.alter_column('voided_at', new_column_name='cancelled_at', existing_type=sa.DateTime(timezone=True),
                              existing_nullable=True)
    for r in bind.execute(sa.text("SELECT id, flow_step, sku, code_id, platform FROM intake_orders")).mappings().all():
        sku = r["sku"] or ""
        bind.execute(sa.text(
            "UPDATE intake_orders SET status = :st, tier_key = :tier, pay_later = :pl WHERE id = :id"), {
            "st": STEP_TO_STATUS.get(r["flow_step"] or "", "collecting"),
            "tier": sku.removeprefix("legacy-") if sku.startswith("legacy-") else "",
            "pl": 1 if r["platform"] == "manual" else 0, "id": r["id"]})
    bind.execute(sa.text("DELETE FROM intake_orders WHERE customer_id IS NULL"))  # 旧结构里订单必须有客户
    with op.batch_alter_table('intake_orders', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_intake_orders_stage'))
        batch_op.drop_index(batch_op.f('ix_intake_orders_platform_order_id'))
        batch_op.drop_index(batch_op.f('ix_intake_orders_platform'))
        batch_op.create_index(batch_op.f('ix_intake_orders_status'), ['status'], unique=False)
        batch_op.alter_column('customer_id', existing_type=sa.INTEGER(), nullable=False)
        for col in ('platform_completed_at', 'completed_at', 'due_hours', 'page_count', 'paper_count', 'claimed_at',
                    'wechat_external_userid', 'addons', 'band_key', 'sku', 'paid_amount', 'buyer_id', 'platform_order_id',
                    'source', 'platform', 'hold_at', 'hold_reason', 'void_reason', 'voided_from', 'stage_at', 'stage',
                    'flow_step', 'flow_key'):
            batch_op.drop_column(col)
    with op.batch_alter_table('intake_revisions', schema=None) as batch_op:
        batch_op.drop_column('based_on_round')
        batch_op.drop_column('items')
    with op.batch_alter_table('intake_files', schema=None) as batch_op:
        batch_op.drop_column('page_no')
    with op.batch_alter_table('intake_customers', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_intake_customers_person_id'))
        batch_op.drop_column('handoff_brief')
        batch_op.drop_column('memory_brief')
        batch_op.drop_column('person_id')
        batch_op.drop_column('terms_sent_at')
    with op.batch_alter_table('intake_activation_codes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('tier_key', sa.String(length=32), server_default='', nullable=False))
    bind.execute(sa.text("UPDATE intake_activation_codes SET tier_key = CASE WHEN sku LIKE 'legacy-%' "
                         "THEN substr(sku, 8) ELSE sku END"))
    with op.batch_alter_table('intake_activation_codes', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('uq_intake_activation_codes_platform'), type_='unique')
        batch_op.drop_index(batch_op.f('ix_intake_activation_codes_sku'))
        batch_op.create_index(batch_op.f('ix_intake_activation_codes_tier_key'), ['tier_key'], unique=False)
        for col in ('paid_amount', 'paid_at', 'buyer_id', 'platform_order_id', 'platform', 'addons', 'sku'):
            batch_op.drop_column(col)
    with op.batch_alter_table('intake_code_redemptions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_intake_code_redemptions_order_id'))
        batch_op.drop_index(batch_op.f('ix_intake_code_redemptions_customer_id'))
    op.drop_table('intake_code_redemptions')
