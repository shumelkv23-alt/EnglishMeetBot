"""games: game_sessions + 'game' event_type + config seed

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: Union[str, Sequence[str], None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 22. game_sessions — активные игровые сессии («Кто я?» / Quiplash)
    op.create_table(
        "game_sessions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("meeting_instance_id", sa.BigInteger(), nullable=True),
        sa.Column("space_name", sa.String(length=255), nullable=False),
        sa.Column("game_type", sa.String(length=50), nullable=False),
        sa.Column(
            "status",
            sa.String(length=50),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column("topic", sa.String(length=255), nullable=True),
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
        sa.ForeignKeyConstraint(["meeting_instance_id"], ["meeting_instances.id"]),
        sa.CheckConstraint("game_type IN ('who_am_i', 'quiplash')", name="valid_game_type"),
        sa.CheckConstraint(
            "status IN ('active', 'finished', 'cancelled')", name="valid_game_status"
        ),
    )
    op.create_index(
        "idx_game_sessions_space_status", "game_sessions", ["space_name", "status"]
    )
    op.create_index("idx_game_sessions_meeting", "game_sessions", ["meeting_instance_id"])

    # Расширить CHECK leaderboard_ledger: добавить тип события 'game' (очки игр)
    op.drop_constraint("valid_event_type", "leaderboard_ledger", type_="check")
    op.create_check_constraint(
        "valid_event_type",
        "leaderboard_ledger",
        "event_type IN ('attendance', 'answer', 'streak', 'mvp', 'bonus', 'game')",
    )

    # Сидинг config: параметры игр
    op.execute(
        """
        INSERT INTO config (key, value, description) VALUES
        ('quiplash_rounds', '10', 'Количество раундов в Quiplash'),
        ('quiplash_winner_points', '3', 'Очки победителю раунда Quiplash'),
        ('quiplash_second_points', '1', 'Очки второму месту раунда Quiplash'),
        ('who_am_i_guess_points', '2', 'Очки за угаданную сущность в «Кто я?»'),
        ('quiplash_answer_timeout_seconds', '300', 'Секунд на ответы в раунде Quiplash'),
        ('quiplash_vote_timeout_seconds', '120', 'Секунд на голосование в раунде Quiplash'),
        ('who_am_i_turn_timeout_seconds', '600', 'Секунд на ход угадывающего в «Кто я?»')
        ON CONFLICT (key) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM config WHERE key IN ('quiplash_rounds', 'quiplash_winner_points', 'quiplash_second_points', 'who_am_i_guess_points', 'quiplash_answer_timeout_seconds', 'quiplash_vote_timeout_seconds', 'who_am_i_turn_timeout_seconds')"
    )
    op.drop_constraint("valid_event_type", "leaderboard_ledger", type_="check")
    op.create_check_constraint(
        "valid_event_type",
        "leaderboard_ledger",
        "event_type IN ('attendance', 'answer', 'streak', 'mvp', 'bonus')",
    )
    op.drop_index("idx_game_sessions_meeting", table_name="game_sessions")
    op.drop_index("idx_game_sessions_space_status", table_name="game_sessions")
    op.drop_table("game_sessions")
