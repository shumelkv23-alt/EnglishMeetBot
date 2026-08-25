"""недельный опрос: day_of_week у poll_slots (0=Пн .. 6=Вс)

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007"
down_revision: Union[str, Sequence[str], None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "poll_slots",
        sa.Column("day_of_week", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("poll_slots", "day_of_week")
