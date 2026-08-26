"""words_of_wonders: game_type 'words_of_wonders'

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0017"
down_revision: Union[str, Sequence[str], None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Расширить CHECK game_sessions.game_type: добавить игру «Words of Wonders».
    # Очки не ведутся — отдельной таблицы рейтинга и config-сидов не требуется.
    op.drop_constraint("valid_game_type", "game_sessions", type_="check")
    op.create_check_constraint(
        "valid_game_type",
        "game_sessions",
        "game_type IN ('who_am_i', 'quiplash', 'hangman', 'millionaire', 'wordle', 'two_truths', 'word_puzzle', 'translation', 'words_of_wonders')",
    )


def downgrade() -> None:
    op.drop_constraint("valid_game_type", "game_sessions", type_="check")
    op.create_check_constraint(
        "valid_game_type",
        "game_sessions",
        "game_type IN ('who_am_i', 'quiplash', 'hangman', 'millionaire', 'wordle', 'two_truths', 'word_puzzle', 'translation')",
    )
