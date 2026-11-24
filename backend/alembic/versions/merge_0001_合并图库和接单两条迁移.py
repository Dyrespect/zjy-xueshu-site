"""合并图库和接单两条迁移

Revision ID: merge_0001
Revises: figures_0001, intake_0001
Create Date: 2026-11-14 17:25:56.917148
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'merge_0001'
down_revision: Union[str, Sequence[str], None] = ('figures_0001', 'intake_0001')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
