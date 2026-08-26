"""соло-игры: расширение game_type + таблицы счёта (hangman, millionaire, wordle)

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0011"
down_revision: Union[str, Sequence[str], None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Расширить CHECK game_sessions.game_type на 8 соло-игр.
    op.drop_constraint("valid_game_type", "game_sessions", type_="check")
    op.create_check_constraint(
        "valid_game_type",
        "game_sessions",
        "game_type IN ('who_am_i', 'quiplash', 'hangman', 'millionaire', 'wordle', "
        "'two_truths', 'word_puzzle', 'translation', 'words_of_wonders', 'riddles')",
    )

    op.create_table(
        "hangman_scores",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("wins", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("losses", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("points", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"]),
        sa.UniqueConstraint("profile_id", name="unique_hangman_score_profile"),
    )
    op.create_index("idx_hangman_scores_points", "hangman_scores", ["points"])

    op.create_table(
        "millionaire_scores",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("completed", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("best_level", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("points", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"]),
        sa.UniqueConstraint("profile_id", name="unique_millionaire_score_profile"),
    )
    op.create_index("idx_millionaire_scores_points", "millionaire_scores", ["points"])

    op.create_table(
        "wordle_scores",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("games_played", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("wins", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("points", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("best_guesses", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"]),
        sa.UniqueConstraint("profile_id", name="unique_wordle_score_profile"),
    )
    op.create_index("idx_wordle_scores_points", "wordle_scores", ["points"])


def downgrade() -> None:
    op.drop_index("idx_wordle_scores_points", table_name="wordle_scores")
    op.drop_table("wordle_scores")
    op.drop_index("idx_millionaire_scores_points", table_name="millionaire_scores")
    op.drop_table("millionaire_scores")
    op.drop_index("idx_hangman_scores_points", table_name="hangman_scores")
    op.drop_table("hangman_scores")

    op.drop_constraint("valid_game_type", "game_sessions", type_="check")
    op.create_check_constraint(
        "valid_game_type",
        "game_sessions",
        "game_type IN ('who_am_i', 'quiplash')",
    )
