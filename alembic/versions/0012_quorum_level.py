# alembic/versions/0012_quorum_level.py
"""Кворум недельного опроса 3 -> 4: обновить засиженное значение config.

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-26
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0012"
down_revision: Union[str, Sequence[str], None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE config SET value = '4'::jsonb WHERE key = 'quorum_threshold'")


def downgrade() -> None:
    op.execute("UPDATE config SET value = '3'::jsonb WHERE key = 'quorum_threshold'")
