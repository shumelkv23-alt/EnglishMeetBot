"""poll_responses.status — статус not_available вместо skipped

Revision ID: 0004
Revises: 0003

Ежедневная логика submit_poll ставит PollResponse.status = 'not_available',
когда участник отметил, что не может присутствовать. Расширяем CHECK
valid_status на таблице poll_responses: 'skipped' заменяется на 'not_available'.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("valid_status", "poll_responses", type_="check")
    op.create_check_constraint(
        "valid_status",
        "poll_responses",
        "status IN ('pending', 'responded', 'not_available')",
    )


def downgrade() -> None:
    op.drop_constraint("valid_status", "poll_responses", type_="check")
    op.create_check_constraint(
        "valid_status",
        "poll_responses",
        "status IN ('pending', 'responded', 'skipped')",
    )
