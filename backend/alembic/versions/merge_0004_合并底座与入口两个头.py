"""合并底座与入口两个头

Revision ID: merge_0004
Revises: channels_0001, core_0002
Create Date: 2026-11-18 14:06:28.306512
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'merge_0004'
down_revision: Union[str, Sequence[str], None] = ('channels_0001', 'core_0002')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
