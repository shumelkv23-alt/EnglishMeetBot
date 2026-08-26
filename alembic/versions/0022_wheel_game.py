"""game_sessions: add 'wheel' game type (Поле чудес / Wheel of Fortune)

Revision ID: 0022
Revises: 0021
Create Date: 2026-08-26

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0022"
down_revision: Union[str, Sequence[str], None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("valid_game_type", "game_sessions", type_="check")
    op.create_check_constraint(
        "valid_game_type",
        "game_sessions",
        "game_type IN ('who_am_i', 'quiplash', 'hangman', 'millionaire', 'wordle', 'two_truths', "
        "'word_puzzle', 'translation', 'words_of_wonders', 'riddles', 'spy', 'guesspionage', 'wheel')",
    )


def downgrade() -> None:
    op.drop_constraint("valid_game_type", "game_sessions", type_="check")
    op.create_check_constraint(
        "valid_game_type",
        "game_sessions",
        "game_type IN ('who_am_i', 'quiplash', 'hangman', 'millionaire', 'wordle', 'two_truths', "
        "'word_puzzle', 'translation', 'words_of_wonders', 'riddles', 'spy', 'guesspionage')",
    )
