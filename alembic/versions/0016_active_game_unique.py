"""Partial unique index: одна активная сессия на space (защита от двойного старта).

Fix П.8: двойной клик по кнопке игры мог создать две сессии status='active'
в одном space — get_active_game падал с MultipleResultsFound, и space «умирал».
Уникальный индекс по (space_name) WHERE status='active' делает вторую вставку
невозможной на уровне БД.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: Union[str, Sequence[str], None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "uq_game_sessions_active_space",
        "game_sessions",
        ["space_name"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index("uq_game_sessions_active_space", table_name="game_sessions")
