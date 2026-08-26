"""lesson_sessions: add 'would_you_rather' and 'taboo' formats

Revision ID: 0021
Revises: 0020
Create Date: 2026-08-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0021"
down_revision: Union[str, Sequence[str], None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Расширить CHECK lesson_sessions.format: добавить два новых формата.
    op.drop_constraint("valid_lesson_format", "lesson_sessions", type_="check")
    op.create_check_constraint(
        "valid_lesson_format",
        "lesson_sessions",
        "format IN ('discussion', 'debate', 'four_hats', 'roleplay', 'ranking', "
        "'would_you_rather', 'story', 'taboo', 'dilemma', 'speed_dating')",
    )


def downgrade() -> None:
    op.drop_constraint("valid_lesson_format", "lesson_sessions", type_="check")
    op.create_check_constraint(
        "valid_lesson_format",
        "lesson_sessions",
        "format IN ('discussion', 'debate', 'four_hats', 'roleplay', 'ranking', "
        "'story', 'dilemma', 'speed_dating')",
    )
