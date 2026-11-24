"""待发加「到点才发」（intake_outbox.send_after）：接待机器人模拟真人回复节奏（docs/任务单/12_接待机器人_设计.md 第六节）

只加一列（可空，空 = 批了就发），不改别的。接在 intake_0005 后面。

Revision ID: intake_0006
Revises: intake_0005
Create Date: 2026-11-19 09:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'intake_0006'
down_revision: Union[str, Sequence[str], None] = 'intake_0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('intake_outbox') as batch:
        batch.add_column(sa.Column('send_after', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('intake_outbox') as batch:
        batch.drop_column('send_after')
