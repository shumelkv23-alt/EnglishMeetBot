"""poll_questions — сгенерированные LLM-вопросы недельного опроса

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "poll_questions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("poll_id", sa.BigInteger(), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["poll_id"], ["weekly_polls.id"]),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("poll_id", "profile_id", name="unique_poll_profile_question"),
    )
    op.create_index("idx_poll_questions_poll", "poll_questions", ["poll_id"])
    op.create_index("idx_poll_questions_profile", "poll_questions", ["profile_id"])


def downgrade() -> None:
    op.drop_index("idx_poll_questions_profile", table_name="poll_questions")
    op.drop_index("idx_poll_questions_poll", table_name="poll_questions")
    op.drop_table("poll_questions")