"""lesson_sessions: generated lesson cards for meetups

Revision ID: 0020
Revises: 0019
Create Date: 2026-08-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0020"
down_revision: Union[str, Sequence[str], None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 28. lesson_sessions — сгенерированные «занятие-карточки» для встреч.
    # Одна строка = одна тема + план (LLM или банк). message_name — имя
    # сообщения в группе (для update на месте при reroll). Использованные
    # темы — это строки таблицы, по ним дедуплицируем.
    op.create_table(
        "lesson_sessions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("meeting_instance_id", sa.BigInteger(), nullable=True),
        sa.Column("topic", sa.String(255), nullable=False),
        sa.Column("format", sa.String(50), nullable=False),
        sa.Column("level", sa.String(50), nullable=False),
        sa.Column("content", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("message_name", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["meeting_instance_id"], ["meeting_instances.id"]),
        sa.CheckConstraint(
            "format IN ('discussion', 'debate', 'four_hats', 'roleplay', 'ranking', "
            "'story', 'dilemma', 'speed_dating')",
            name="valid_lesson_format",
        ),
    )
    op.create_index("idx_lesson_sessions_meeting", "lesson_sessions", ["meeting_instance_id"])
    op.create_index("idx_lesson_sessions_topic", "lesson_sessions", ["topic"])
    op.create_index("idx_lesson_sessions_created", "lesson_sessions", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_lesson_sessions_created", table_name="lesson_sessions")
    op.drop_index("idx_lesson_sessions_topic", table_name="lesson_sessions")
    op.drop_index("idx_lesson_sessions_meeting", table_name="lesson_sessions")
    op.drop_table("lesson_sessions")
