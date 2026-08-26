"""wordle: game_type 'wordle' + wordle_scores + config seed

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: Union[str, Sequence[str], None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Расширить CHECK game_sessions.game_type: добавить игру Wordle.
    op.drop_constraint("valid_game_type", "game_sessions", type_="check")
    op.create_check_constraint(
        "valid_game_type",
        "game_sessions",
        "game_type IN ('who_am_i', 'quiplash', 'hangman', 'millionaire', 'wordle')",
    )

    # Отдельный рейтинг Wordle (не общий leaderboard_ledger), как у «Виселицы».
    # points — сумма баллов за победы (6..1); best_guesses — минимум попыток (0, если нет побед).
    op.create_table(
        "wordle_scores",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("games_played", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("wins", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("points", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("best_guesses", sa.Integer(), server_default=sa.text("0"), nullable=False),
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
        sa.UniqueConstraint("profile_id", name="unique_wordle_score_profile"),
    )
    op.create_index("idx_wordle_scores_points", "wordle_scores", ["points"])

    # Сидинг config: параметры Wordle.
    op.execute(
        """
        INSERT INTO config (key, value, description) VALUES
        ('wordle_max_guesses', '6', 'Максимум попыток в партии Wordle'),
        ('wordle_word_length', '5', 'Длина загадываемого слова в Wordle')
        ON CONFLICT (key) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM config WHERE key IN ('wordle_max_guesses', 'wordle_word_length')"
    )
    op.drop_index("idx_wordle_scores_points", table_name="wordle_scores")
    op.drop_table("wordle_scores")
    op.drop_constraint("valid_game_type", "game_sessions", type_="check")
    op.create_check_constraint(
        "valid_game_type",
        "game_sessions",
        "game_type IN ('who_am_i', 'quiplash', 'hangman', 'millionaire')",
    )
