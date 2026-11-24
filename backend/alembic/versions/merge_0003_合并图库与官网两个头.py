"""合并 gather 与 website 两个头

Revision ID: merge_0003
Revises: gather_0001, website_0001
Create Date: 2026-11-18 13:23:19.989756
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'merge_0003'
down_revision: Union[str, Sequence[str], None] = ('gather_0001', 'website_0001')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
