"""Partial unique index для leaderboard_ledger при NULL meeting_instance_id.

Fix П.10: Postgres NULL ≠ NULL в UNIQUE, поэтому on_conflict_do_nothing по
(profile_id, meeting_instance_id, event_type) не ловит дубли при
meeting_instance_id IS NULL. Частичный индекс закрывает этот случай.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: Union[str, Sequence[str], None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Дедуплицировать уже накопившиеся NULL-дубли (оставить первую запись группы),
    # иначе создание уникального индекса упадёт на существующих данных.
    op.execute(
        """
        DELETE FROM leaderboard_ledger
        WHERE meeting_instance_id IS NULL
          AND id NOT IN (
            SELECT MIN(id) FROM leaderboard_ledger
            WHERE meeting_instance_id IS NULL
            GROUP BY profile_id, event_type
          )
        """
    )
    op.create_index(
        "uq_leaderboard_null_meeting",
        "leaderboard_ledger",
        ["profile_id", "event_type"],
        unique=True,
        postgresql_where=sa.text("meeting_instance_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_leaderboard_null_meeting", table_name="leaderboard_ledger")
