"""inactivity reminders — last_activity_at / reminder_count / last_reminder_at в profiles

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "profiles",
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "profiles",
        sa.Column("reminder_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "profiles",
        sa.Column("last_reminder_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """
        INSERT INTO config (key, value, description) VALUES
        ('inactivity_reminder_days', '7', 'Порог неактивности до первого напоминания, дней'),
        ('inactivity_reminder_interval_days', '3', 'Интервал между повторными напоминаниями, дней'),
        ('inactivity_max_reminders', '3', 'Максимум напоминаний подряд на участника'),
        ('inactivity_reminder_hour', '11', 'Час запуска джоба напоминаний')
        ON CONFLICT (key) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM config WHERE key IN "
        "('inactivity_reminder_days','inactivity_reminder_interval_days',"
        "'inactivity_max_reminders','inactivity_reminder_hour')"
    )
    op.drop_column("profiles", "last_reminder_at")
    op.drop_column("profiles", "reminder_count")
    op.drop_column("profiles", "last_activity_at")
