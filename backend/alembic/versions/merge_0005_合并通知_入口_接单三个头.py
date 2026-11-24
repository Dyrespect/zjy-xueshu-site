"""合并通知、入口、接单三个头

Revision ID: merge_0005
Revises: channels_0002, core_0003, intake_0006
Create Date: 2026-11-19 08:02:13.659642
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'merge_0005'
down_revision: Union[str, Sequence[str], None] = ('channels_0002', 'core_0003', 'intake_0006')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
