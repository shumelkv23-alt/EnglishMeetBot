"""weekly_questions — история заданных участникам вопросов недели

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "weekly_questions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column(
            "asked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_weekly_questions_profile", "weekly_questions", ["profile_id"])
    op.create_index("idx_weekly_questions_asked_at", "weekly_questions", ["asked_at"])
    op.create_index(
        "idx_weekly_questions_profile_week",
        "weekly_questions",
        ["profile_id", "week_start"],
    )


def downgrade() -> None:
    op.drop_index("idx_weekly_questions_profile_week", table_name="weekly_questions")
    op.drop_index("idx_weekly_questions_asked_at", table_name="weekly_questions")
    op.drop_index("idx_weekly_questions_profile", table_name="weekly_questions")
    op.drop_table("weekly_questions")
