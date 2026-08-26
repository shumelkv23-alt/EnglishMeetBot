"""millionaire: game_type 'millionaire' + millionaire_scores + config seed

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: Union[str, Sequence[str], None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Расширить CHECK game_sessions.game_type: добавить «Кто хочет стать миллионером».
    op.drop_constraint("valid_game_type", "game_sessions", type_="check")
    op.create_check_constraint(
        "valid_game_type",
        "game_sessions",
        "game_type IN ('who_am_i', 'quiplash', 'hangman', 'millionaire')",
    )

    # Отдельный рейтинг «Миллионера» (не общий leaderboard_ledger), как у «Виселицы».
    # points — сумма баллов за полные прохождения (см. millionaire.py).
    op.create_table(
        "millionaire_scores",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("completed", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("best_level", sa.Integer(), server_default=sa.text("0"), nullable=False),
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
        sa.UniqueConstraint("profile_id", name="unique_millionaire_score_profile"),
    )
    op.create_index("idx_millionaire_scores_points", "millionaire_scores", ["points"])

    # Сидинг config: параметры «Миллионера».
    op.execute(
        """
        INSERT INTO config (key, value, description) VALUES
        ('millionaire_completion_points', '15', 'Очки в рейтинг «Миллионера» за полное прохождение'),
        ('millionaire_total_questions', '15', 'Число вопросов в партии «Миллионера»')
        ON CONFLICT (key) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM config WHERE key IN ('millionaire_completion_points', 'millionaire_total_questions')"
    )
    op.drop_index("idx_millionaire_scores_points", table_name="millionaire_scores")
    op.drop_table("millionaire_scores")
    op.drop_constraint("valid_game_type", "game_sessions", type_="check")
    op.create_check_constraint(
        "valid_game_type",
        "game_sessions",
        "game_type IN ('who_am_i', 'quiplash', 'hangman')",
    )
