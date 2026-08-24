"""snake_oil: поле round_message_name у snake_games — карточка раунда в группе
(обновляется на месте через messages.patch, чтобы не плодить сообщения каждый раунд)

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0008"
down_revision: Union[str, Sequence[str], None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "snake_games",
        sa.Column("round_message_name", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("snake_games", "round_message_name")
