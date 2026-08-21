"""daily polling — ежедневное голосование «в тот же день»

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-21

Меняем недельную схему (выбор дня недели) на ежедневную (в тот же день, будни).
Переиспользуем таблицы weekly_polls/poll_slots/poll_responses/poll_votes —
теперь «опрос» = один день (week_start = дата дня, voting_deadline = 13:00).

Изменения:
  - poll_responses.will_attend BOOLEAN — «да/нет» участника.
  - config.quorum_threshold 3 -> 4.
  - новые ключи config: daily_poll_hour (9), daily_poll_close_hour (13),
    daily_checkin_hour (18).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. poll_responses.will_attend — «да/нет» участника (NULL = ещё не ответил)
    op.add_column(
        "poll_responses",
        sa.Column("will_attend", sa.Boolean(), nullable=True),
    )

    # 2. кворум: 3 -> 4
    op.execute(
        "UPDATE config SET value = '4'::jsonb, updated_at = now() "
        "WHERE key = 'quorum_threshold';"
    )

    # 3. новые ключи ежедневного расписания (часы в таймзоне бота)
    op.execute(
        """
        INSERT INTO config (key, value, description) VALUES
        ('daily_poll_hour', '9', 'Час рассылки «Сможешь сегодня прийти?» (по будням)'),
        ('daily_poll_close_hour', '13', 'Час финализации голосования (кворум -> встречи)'),
        ('daily_checkin_hour', '18', 'Час рассылки чек-ина «ты был(а) на встрече?» (конец дня)')
        ON CONFLICT (key) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM config WHERE key IN "
        "('daily_poll_hour', 'daily_poll_close_hour', 'daily_checkin_hour');"
    )
    op.execute(
        "UPDATE config SET value = '3'::jsonb, updated_at = now() "
        "WHERE key = 'quorum_threshold';"
    )
    op.drop_column("poll_responses", "will_attend")
