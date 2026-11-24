"""图库（模块 L）：改标签带「改成什么」和署名、审核结论、版权下架、叠在索引上的一层、搜索记录加来源

Revision ID: figures_0002
Revises: invoices_0001
Create Date: 2026-11-18 20:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'figures_0002'
down_revision: Union[str, Sequence[str], None] = 'invoices_0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('figure_feedback', schema=None) as b:
        b.add_column(sa.Column('proposed', sa.JSON(), nullable=False, server_default='{}'))
        b.add_column(sa.Column('credit', sa.String(length=40), nullable=False, server_default=''))
        b.add_column(sa.Column('decision', sa.String(length=16), nullable=False, server_default='new'))
        b.create_index(b.f('ix_figure_feedback_decision'), ['decision'], unique=False)
    with op.batch_alter_table('figure_submissions', schema=None) as b:
        b.add_column(sa.Column('decision', sa.String(length=16), nullable=False, server_default='new'))
        b.create_index(b.f('ix_figure_submissions_decision'), ['decision'], unique=False)
    with op.batch_alter_table('search_logs', schema=None) as b:
        b.add_column(sa.Column('caller', sa.String(length=8), nullable=False, server_default='web'))
        b.add_column(sa.Column('src', sa.String(length=32), nullable=False, server_default=''))
        b.add_column(sa.Column('visitor', sa.String(length=40), nullable=False, server_default=''))
        b.add_column(sa.Column('client', sa.String(length=60), nullable=False, server_default=''))
        b.create_index(b.f('ix_search_logs_caller'), ['caller'], unique=False)

    op.create_table('figure_takedowns',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ip', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('admin_note', sa.Text(), nullable=False),
    sa.Column('handled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('figure_ids', sa.JSON(), nullable=False),
    sa.Column('figures_text', sa.Text(), nullable=False),
    sa.Column('holder', sa.String(length=200), nullable=False),
    sa.Column('contact', sa.String(length=200), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('deadline_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('decision', sa.String(length=16), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_figure_takedowns'))
    )
    with op.batch_alter_table('figure_takedowns', schema=None) as b:
        b.create_index(b.f('ix_figure_takedowns_created_at'), ['created_at'], unique=False)
        b.create_index(b.f('ix_figure_takedowns_ip'), ['ip'], unique=False)
        b.create_index(b.f('ix_figure_takedowns_status'), ['status'], unique=False)
        b.create_index(b.f('ix_figure_takedowns_decision'), ['decision'], unique=False)

    op.create_table('figure_overrides',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('figure_id', sa.Integer(), nullable=False),
    sa.Column('field', sa.String(length=16), nullable=False),
    sa.Column('value', sa.JSON(), nullable=False),
    sa.Column('credit', sa.String(length=40), nullable=False),
    sa.Column('source_kind', sa.String(length=16), nullable=False),
    sa.Column('source_id', sa.Integer(), nullable=True),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_figure_overrides'))
    )
    with op.batch_alter_table('figure_overrides', schema=None) as b:
        b.create_index(b.f('ix_figure_overrides_figure_id'), ['figure_id'], unique=False)
        b.create_index(b.f('ix_figure_overrides_active'), ['active'], unique=False)


def downgrade() -> None:
    op.drop_table('figure_overrides')
    op.drop_table('figure_takedowns')
    with op.batch_alter_table('search_logs', schema=None) as b:
        b.drop_index(b.f('ix_search_logs_caller'))
        for c in ('client', 'visitor', 'src', 'caller'):
            b.drop_column(c)
    with op.batch_alter_table('figure_submissions', schema=None) as b:
        b.drop_index(b.f('ix_figure_submissions_decision'))
        b.drop_column('decision')
    with op.batch_alter_table('figure_feedback', schema=None) as b:
        b.drop_index(b.f('ix_figure_feedback_decision'))
        for c in ('decision', 'credit', 'proposed'):
            b.drop_column(c)
