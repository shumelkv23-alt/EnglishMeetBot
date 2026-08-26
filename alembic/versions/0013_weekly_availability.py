"""weekly availability: weekly_polls + weekly_availability + config seed

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: Union[str, Sequence[str], None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Недельный опрос доступности: одна запись = одна неделя (пн–пт).
    # Висит в группе всю неделю, голоса складываются в weekly_availability.
    op.create_table(
        "weekly_polls",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("status", sa.String(50), server_default=sa.text("'active'"), nullable=False),
        sa.Column("poll_message_name", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("week_start", name="unique_weekly_poll_week"),
        sa.CheckConstraint("status IN ('active', 'finalized')", name="valid_weekly_status"),
    )
    op.create_index("idx_weekly_polls_week", "weekly_polls", ["week_start"])
    op.create_index("idx_weekly_polls_status", "weekly_polls", ["status"])

    # Голос за (день, время) в недельном опросе. UNIQUE(poll, profile, day)
    # = нельзя проголосовать за два времени в один день.
    op.create_table(
        "weekly_availability",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("poll_id", sa.BigInteger(), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("day", sa.String(10), nullable=False),
        sa.Column("time", sa.String(10), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["poll_id"], ["weekly_polls.id"]),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"]),
        sa.UniqueConstraint(
            "poll_id", "profile_id", "day", name="unique_weekly_day_vote"
        ),
    )
    op.create_index("idx_weekly_availability_poll", "weekly_availability", ["poll_id"])
    op.create_index("idx_weekly_availability_profile", "weekly_availability", ["profile_id"])
    op.create_index(
        "idx_weekly_availability_day_time",
        "weekly_availability",
        ["poll_id", "day", "time"],
    )

    # Сидинг config: рабочие дни недельного опроса доступности.
    # Время воскресной рассылки (10:00) и ежедневной проверки (15:00) зашито
    # в cron джобах scheduler (см. init_scheduler).
    op.execute(
        """
        INSERT INTO config (key, value, description) VALUES
        ('weekly_days', '["mon", "tue", "wed", "thu", "fri"]', 'Рабочие дни недельного опроса доступности')
        ON CONFLICT (key) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM config WHERE key = 'weekly_days'")
    op.drop_index("idx_weekly_availability_day_time", table_name="weekly_availability")
    op.drop_index("idx_weekly_availability_profile", table_name="weekly_availability")
    op.drop_index("idx_weekly_availability_poll", table_name="weekly_availability")
    op.drop_table("weekly_availability")
    op.drop_index("idx_weekly_polls_status", table_name="weekly_polls")
    op.drop_index("idx_weekly_polls_week", table_name="weekly_polls")
    op.drop_table("weekly_polls")
