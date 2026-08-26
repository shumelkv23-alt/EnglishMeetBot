"""spy/guesspionage: game_type 'spy' and 'guesspionage'

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0019"
down_revision: Union[str, Sequence[str], None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Расширить CHECK game_sessions.game_type: добавить «Spy» и «Guesspionage».
    # Очки идут в общий leaderboard_ledger (event_type 'game') — отдельных таблиц
    # рейтинга и config-сидов не требуется.
    op.drop_constraint("valid_game_type", "game_sessions", type_="check")
    op.create_check_constraint(
        "valid_game_type",
        "game_sessions",
        "game_type IN ('who_am_i', 'quiplash', 'hangman', 'millionaire', 'wordle', 'two_truths', 'word_puzzle', 'translation', 'words_of_wonders', 'riddles', 'spy', 'guesspionage')",
    )


def downgrade() -> None:
    op.drop_constraint("valid_game_type", "game_sessions", type_="check")
    op.create_check_constraint(
        "valid_game_type",
        "game_sessions",
        "game_type IN ('who_am_i', 'quiplash', 'hangman', 'millionaire', 'wordle', 'two_truths', 'word_puzzle', 'translation', 'words_of_wonders', 'riddles')",
    )
