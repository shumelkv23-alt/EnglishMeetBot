"""hangman: game_type 'hangman' + hangman_scores + config seed

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: Union[str, Sequence[str], None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Расширить CHECK game_sessions.game_type: добавить игру «Виселица» (ДМ-игра).
    op.drop_constraint("valid_game_type", "game_sessions", type_="check")
    op.create_check_constraint(
        "valid_game_type",
        "game_sessions",
        "game_type IN ('who_am_i', 'quiplash', 'hangman')",
    )

    # Отдельный лидерборд «Виселицы» (не общий leaderboard_ledger).
    # points = wins*win_points - losses*lose_points (см. hangman.py).
    op.create_table(
        "hangman_scores",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("wins", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("losses", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("points", sa.Integer(), server_default=sa.text("0"), nullable=False),
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
        sa.UniqueConstraint("profile_id", name="unique_hangman_score_profile"),
    )
    op.create_index("idx_hangman_scores_points", "hangman_scores", ["points"])

    # Сидинг config: параметры «Виселицы».
    op.execute(
        """
        INSERT INTO config (key, value, description) VALUES
        ('hangman_max_wrong', '6', 'Максимум неверных попыток в «Виселице»'),
        ('hangman_win_points', '2', 'Очки в рейтинг «Виселицы» за победу'),
        ('hangman_lose_points', '3', 'Очки в рейтинг «Виселицы» за поражение (вычитаются)')
        ON CONFLICT (key) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM config WHERE key IN ('hangman_max_wrong', 'hangman_win_points', 'hangman_lose_points')"
    )
    op.drop_index("idx_hangman_scores_points", table_name="hangman_scores")
    op.drop_table("hangman_scores")
    op.drop_constraint("valid_game_type", "game_sessions", type_="check")
    op.create_check_constraint(
        "valid_game_type",
        "game_sessions",
        "game_type IN ('who_am_i', 'quiplash')",
    )
