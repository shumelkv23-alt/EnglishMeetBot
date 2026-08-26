"""callready_progress + 'learning' event_type

Revision ID: 0023
Revises: 0022
Create Date: 2026-08-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0023"
down_revision: Union[str, Sequence[str], None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 29. callready_progress — прогресс курса «Survival English for Calls» в личке.
    # Одна строка на профиль; живое состояние курса в JSONB state (текущий модуль,
    # завершённые модули, верные грамматические ответы, просмотренный фразбук).
    op.create_table(
        "callready_progress",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"]),
        sa.UniqueConstraint("profile_id", name="unique_callready_progress_profile"),
    )
    op.create_index("idx_callready_progress_profile", "callready_progress", ["profile_id"])

    # Начисление баллов за обучение в общий лидерборд: расширить CHECK event_type
    # на leaderboard_ledger, добавив 'learning'.
    op.drop_constraint("valid_event_type", "leaderboard_ledger", type_="check")
    op.create_check_constraint(
        "valid_event_type",
        "leaderboard_ledger",
        "event_type IN ('attendance', 'answer', 'streak', 'mvp', 'bonus', 'game', 'learning')",
    )


def downgrade() -> None:
    op.drop_constraint("valid_event_type", "leaderboard_ledger", type_="check")
    op.create_check_constraint(
        "valid_event_type",
        "leaderboard_ledger",
        "event_type IN ('attendance', 'answer', 'streak', 'mvp', 'bonus', 'game')",
    )
    op.drop_index("idx_callready_progress_profile", table_name="callready_progress")
    op.drop_table("callready_progress")
