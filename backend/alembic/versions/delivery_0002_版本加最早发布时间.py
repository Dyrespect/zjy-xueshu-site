"""交付版本加「最早几点发给客人」（delivery_versions.release_at）：不加急的单第一版压到加急承诺时长之后再发
（Edison 11-19；docs/任务单/12_接待机器人_设计.md 第十五节）

只加一列（可空，空 = 不压），不改别的。接在 main 唯一的头 merge_0005 后面。

Revision ID: delivery_0002
Revises: merge_0005
Create Date: 2026-11-19 18:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'delivery_0002'
down_revision: Union[str, Sequence[str], None] = 'merge_0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('delivery_versions') as batch:
        batch.add_column(sa.Column('release_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('delivery_versions') as batch:
        batch.drop_column('release_at')
