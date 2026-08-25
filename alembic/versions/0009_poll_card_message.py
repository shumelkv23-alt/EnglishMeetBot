"""опрос недели: card_message_name у daily_polls (для обновления карточки на месте)

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0009"
down_revision: Union[str, Sequence[str], None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "daily_polls",
        sa.Column("card_message_name", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("daily_polls", "card_message_name")
