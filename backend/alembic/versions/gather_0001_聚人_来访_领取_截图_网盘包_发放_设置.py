"""科研绘图聚人（模块 L）：来访、领取（gather_figures 流程的对象）、截图、网盘包、发链接留痕、聚人设置

Revision ID: gather_0001
Revises: figures_0002
Create Date: 2026-11-18 20:10:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'gather_0001'
down_revision: Union[str, Sequence[str], None] = 'figures_0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('funnel_visits',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('visitor', sa.String(length=40), nullable=False),
    sa.Column('src', sa.String(length=32), nullable=False),
    sa.Column('share_code', sa.String(length=12), nullable=True),
    sa.Column('share_counted', sa.Boolean(), nullable=False),
    sa.Column('landing', sa.String(length=300), nullable=False),
    sa.Column('referrer_host', sa.String(length=100), nullable=False),
    sa.Column('ip', sa.String(length=64), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_funnel_visits'))
    )
    with op.batch_alter_table('funnel_visits', schema=None) as b:
        for c in ('created_at', 'visitor', 'src', 'share_code', 'ip'):
            b.create_index(b.f(f'ix_funnel_visits_{c}'), [c], unique=False)

    op.create_table('figure_unlocks',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('flow_key', sa.String(length=32), nullable=False),
    sa.Column('flow_step', sa.String(length=32), nullable=False),
    sa.Column('stage', sa.String(length=16), nullable=False),
    sa.Column('stage_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('visitor', sa.String(length=40), nullable=False),
    sa.Column('share_code', sa.String(length=12), nullable=False),
    sa.Column('src', sa.String(length=32), nullable=False),
    sa.Column('tier', sa.String(length=8), nullable=False),
    sa.Column('verifiers', sa.JSON(), nullable=False),
    sa.Column('verifier', sa.String(length=32), nullable=False),
    sa.Column('verdict_reason', sa.String(length=300), nullable=False),
    sa.Column('door', sa.String(length=16), nullable=False),
    sa.Column('channel_user', sa.String(length=80), nullable=False),
    sa.Column('share_visits', sa.Integer(), nullable=False),
    sa.Column('passed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ip', sa.String(length=64), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_figure_unlocks')),
    sa.UniqueConstraint('share_code', name=op.f('uq_figure_unlocks_share_code'))
    )
    with op.batch_alter_table('figure_unlocks', schema=None) as b:
        for c in ('created_at', 'flow_step', 'stage', 'visitor', 'channel_user'):
            b.create_index(b.f(f'ix_figure_unlocks_{c}'), [c], unique=False)

    op.create_table('figure_unlock_evidence',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('unlock_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('file', sa.String(length=500), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('visitor', sa.String(length=40), nullable=False),
    sa.Column('admin_mark', sa.String(length=8), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_figure_unlock_evidence'))
    )
    with op.batch_alter_table('figure_unlock_evidence', schema=None) as b:
        for c in ('unlock_id', 'sha256', 'visitor'):
            b.create_index(b.f(f'ix_figure_unlock_evidence_{c}'), [c], unique=False)

    op.create_table('figure_packs',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('version', sa.String(length=16), nullable=False),
    sa.Column('tier', sa.String(length=8), nullable=False),
    sa.Column('provider', sa.String(length=16), nullable=False),
    sa.Column('url', sa.String(length=500), nullable=False),
    sa.Column('extract_code', sa.String(length=16), nullable=False),
    sa.Column('count', sa.Integer(), nullable=False),
    sa.Column('size_mb', sa.Float(), nullable=False),
    sa.Column('manifest_sha256', sa.String(length=64), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('note', sa.String(length=200), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_figure_packs')),
    sa.UniqueConstraint('version', 'tier', name='uq_figure_packs_version_tier')
    )
    with op.batch_alter_table('figure_packs', schema=None) as b:
        b.create_index(b.f('ix_figure_packs_active'), ['active'], unique=False)

    op.create_table('figure_pack_grants',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('unlock_id', sa.Integer(), nullable=True),
    sa.Column('pack_id', sa.Integer(), nullable=False),
    sa.Column('tier', sa.String(length=8), nullable=False),
    sa.Column('door', sa.String(length=16), nullable=False),
    sa.Column('channel_user', sa.String(length=80), nullable=False),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('resend_count', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_figure_pack_grants'))
    )
    with op.batch_alter_table('figure_pack_grants', schema=None) as b:
        for c in ('unlock_id', 'pack_id', 'channel_user'):
            b.create_index(b.f(f'ix_figure_pack_grants_{c}'), [c], unique=False)

    op.create_table('gather_settings',
    sa.Column('key', sa.String(length=48), nullable=False),
    sa.Column('value', sa.JSON(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('note', sa.Text(), nullable=False),
    sa.PrimaryKeyConstraint('key', name=op.f('pk_gather_settings'))
    )


def downgrade() -> None:
    for t in ('gather_settings', 'figure_pack_grants', 'figure_packs', 'figure_unlock_evidence', 'figure_unlocks',
              'funnel_visits'):
        op.drop_table(t)
