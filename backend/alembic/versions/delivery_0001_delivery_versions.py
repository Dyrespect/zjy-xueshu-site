"""交付（模块 E）：版本表 delivery_versions（一版一行：用了哪些文件、出图到哪一步、出图参数、什么时候发布）。

生产没上线过，本机只有测试单，没有旧数据要迁。

Revision ID: delivery_0001
Revises: intake_0004
Create Date: 2026-11-18 12:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'delivery_0001'
down_revision: Union[str, Sequence[str], None] = 'intake_0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'delivery_versions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('order_id', sa.Integer(), nullable=False),
        sa.Column('round', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('source', sa.String(length=16), nullable=False),
        sa.Column('note', sa.String(length=2000), nullable=False),
        sa.Column('revision_id', sa.Integer(), nullable=True),
        sa.Column('slide_count', sa.Integer(), nullable=False),
        sa.Column('page_count', sa.Integer(), nullable=False),
        sa.Column('page_file_ids', sa.JSON(), nullable=False),
        sa.Column('final_file_ids', sa.JSON(), nullable=False),
        sa.Column('proof_file_ids', sa.JSON(), nullable=False),
        sa.Column('page_sha256', sa.JSON(), nullable=False),
        sa.Column('watermark_spec', sa.JSON(), nullable=False),
        sa.Column('error', sa.Text(), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('next_try_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('rendered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['order_id'], ['intake_orders.id'], name=op.f('fk_delivery_versions_order_id_intake_orders')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_delivery_versions')),
        sa.UniqueConstraint('order_id', 'round', name='uq_delivery_versions_order_round'),
    )
    with op.batch_alter_table('delivery_versions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_delivery_versions_order_id'), ['order_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_delivery_versions_status'), ['status'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('delivery_versions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_delivery_versions_status'))
        batch_op.drop_index(batch_op.f('ix_delivery_versions_order_id'))
    op.drop_table('delivery_versions')
