"""需求卡（intake_briefs：一单一张，客人点选的需求、确认卡、谁确认的、什么时候、代确认的依据；docs/任务单/09_需求引导_方案.md）

只加一张新表，不改订单表、不加状态（「没确认不开工」靠流程里的闸口节点 gate.brief_confirmed）。
接在 main 唯一的头 merge_0004 后面。

Revision ID: intake_0005
Revises: merge_0004
Create Date: 2026-11-19 01:20:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'intake_0005'
down_revision: Union[str, Sequence[str], None] = 'merge_0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'intake_briefs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('order_id', sa.Integer(), nullable=False),
        sa.Column('answers', sa.JSON(), nullable=False),
        sa.Column('version', sa.Integer(), server_default='0', nullable=False),
        sa.Column('updated_by', sa.String(length=16), server_default='', nullable=False),
        sa.Column('confirmed_version', sa.Integer(), nullable=True),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('confirm_method', sa.String(length=16), server_default='', nullable=False),
        sa.Column('confirmed_by', sa.String(length=16), server_default='', nullable=False),
        sa.Column('confirm_note', sa.String(length=256), server_default='', nullable=False),
        sa.Column('card_text', sa.Text(), server_default='', nullable=False),
        sa.Column('sent_back_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('sent_back_note', sa.String(length=256), server_default='', nullable=False),
        sa.Column('remind_from', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reminded_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['order_id'], ['intake_orders.id'], name=op.f('fk_intake_briefs_order_id_intake_orders')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_intake_briefs')),
    )
    with op.batch_alter_table('intake_briefs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_intake_briefs_order_id'), ['order_id'], unique=True)


def downgrade() -> None:
    with op.batch_alter_table('intake_briefs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_intake_briefs_order_id'))
    op.drop_table('intake_briefs')
