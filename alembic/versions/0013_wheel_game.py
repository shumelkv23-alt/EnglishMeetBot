# alembic/versions/0013_wheel_game.py
"""game_sessions: add 'wheel' game type (Поле чудес / Wheel of Fortune)

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-26
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0013"
down_revision: Union[str, Sequence[str], None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("valid_game_type", "game_sessions", type_="check")
    op.create_check_constraint(
        "valid_game_type",
        "game_sessions",
        "game_type IN ('who_am_i', 'quiplash', 'hangman', 'millionaire', 'wordle', 'two_truths', "
        "'word_puzzle', 'translation', 'words_of_wonders', 'riddles', 'wheel')",
    )


def downgrade() -> None:
    op.drop_constraint("valid_game_type", "game_sessions", type_="check")
    op.create_check_constraint(
        "valid_game_type",
        "game_sessions",
        "game_type IN ('who_am_i', 'quiplash', 'hangman', 'millionaire', 'wordle', 'two_truths', "
        "'word_puzzle', 'translation', 'words_of_wonders', 'riddles')",
    )
