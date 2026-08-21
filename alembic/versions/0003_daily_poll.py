"""daily_polls — переименование weekly_polls под ежедневный цикл

Revision ID: 0003
Revises: 0002

Расширено сверх дословного кода из brief: миграция приводит БД в точное
соответствие с моделью DailyPoll:
- valid_status пересоздаётся с набором ('active','finalized','cancelled');
- индексы idx_weekly_polls_* переименовываются в idx_daily_polls_*;
- частичный индекс idx_weekly_polls_active дропается (в модели его нет);
- уникальный constraint weekly_polls_week_start_key переименовывается в
  daily_polls_poll_date_key (имя, которое сгенерировал бы SQLAlchemy).
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # снять FK и уникальный констрейнт до переименования
    op.drop_constraint("poll_questions_poll_id_fkey", "poll_questions", type_="foreignkey")
    op.drop_constraint("meeting_instances_poll_id_fkey", "meeting_instances", type_="foreignkey")
    op.drop_constraint("poll_responses_poll_id_fkey", "poll_responses", type_="foreignkey")
    op.drop_constraint("poll_slots_poll_id_fkey", "poll_slots", type_="foreignkey")

    # старый valid_status ('active','closed','cancelled') и недельные check'и
    op.drop_constraint("valid_status", "weekly_polls", type_="check")
    op.drop_constraint("valid_reminder_interval", "weekly_polls", type_="check")
    op.drop_constraint("valid_max_reminders", "weekly_polls", type_="check")

    # частичный индекс из недельного цикла — в модели DailyPoll его нет
    op.drop_index("idx_weekly_polls_active", table_name="weekly_polls")

    # недельные колонки -> ежедневные
    op.alter_column("weekly_polls", "week_start", new_column_name="poll_date")
    op.drop_column("weekly_polls", "reminder_interval_hours")
    op.drop_column("weekly_polls", "max_reminders")
    op.rename_table("weekly_polls", "daily_polls")
    op.execute("ALTER INDEX weekly_polls_pkey RENAME TO daily_polls_pkey")

    # индексы под новое имя таблицы/колонки
    op.execute("ALTER INDEX idx_weekly_polls_week RENAME TO idx_daily_polls_date")
    op.execute("ALTER INDEX idx_weekly_polls_status RENAME TO idx_daily_polls_status")
    op.execute("ALTER INDEX idx_weekly_polls_deadline RENAME TO idx_daily_polls_deadline")
    op.execute("ALTER TABLE daily_polls RENAME CONSTRAINT weekly_polls_week_start_key TO daily_polls_poll_date_key")

    # новый valid_status — DailyPoll: status IN ('active','finalized','cancelled')
    op.create_check_constraint(
        "valid_status",
        "daily_polls",
        "status IN ('active', 'finalized', 'cancelled')",
    )

    # вернуть FK на новое имя таблицы
    op.create_foreign_key("poll_slots_poll_id_fkey", "poll_slots", "daily_polls", ["poll_id"], ["id"])
    op.create_foreign_key("poll_responses_poll_id_fkey", "poll_responses", "daily_polls", ["poll_id"], ["id"])
    op.create_foreign_key("meeting_instances_poll_id_fkey", "meeting_instances", "daily_polls", ["poll_id"], ["id"])
    op.create_foreign_key("poll_questions_poll_id_fkey", "poll_questions", "daily_polls", ["poll_id"], ["id"])

    # config-ключи ежедневного цикла
    op.execute(
        """
        INSERT INTO config (key, value, description) VALUES
        ('daily_slots', '["15:00", "16:00", "17:00"]', 'Ежедневные слоты времени'),
        ('quorum_threshold', '3', 'Минимум участников для встречи'),
        ('poll_run_hour', '9', 'Час отправки ежедневного опроса'),
        ('poll_run_minute', '0', 'Минута отправки ежедневного опроса'),
        ('poll_deadline_hour', '14', 'Час дедлайна голосования'),
        ('poll_deadline_minute', '0', 'Минута дедлайна голосования'),
        ('poll_finalize_hour', '14', 'Час финализации'),
        ('poll_finalize_minute', '5', 'Минута финализации'),
        ('meeting_duration_minutes', '60', 'Длительность встречи')
        ON CONFLICT (key) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM config WHERE key IN ('daily_slots','quorum_threshold','poll_run_hour','poll_run_minute','poll_deadline_hour','poll_deadline_minute','poll_finalize_hour','poll_finalize_minute','meeting_duration_minutes')")
    op.drop_constraint("poll_questions_poll_id_fkey", "poll_questions", type_="foreignkey")
    op.drop_constraint("meeting_instances_poll_id_fkey", "meeting_instances", type_="foreignkey")
    op.drop_constraint("poll_responses_poll_id_fkey", "poll_responses", type_="foreignkey")
    op.drop_constraint("poll_slots_poll_id_fkey", "poll_slots", type_="foreignkey")

    # новый valid_status убираем, недельные вернём ниже
    op.drop_constraint("valid_status", "daily_polls", type_="check")

    # индексы обратно под weekly_polls
    op.execute("ALTER INDEX idx_daily_polls_date RENAME TO idx_weekly_polls_week")
    op.execute("ALTER INDEX idx_daily_polls_status RENAME TO idx_weekly_polls_status")
    op.execute("ALTER INDEX idx_daily_polls_deadline RENAME TO idx_weekly_polls_deadline")
    op.rename_table("daily_polls", "weekly_polls")
    op.execute("ALTER INDEX daily_polls_pkey RENAME TO weekly_polls_pkey")
    op.execute("ALTER TABLE weekly_polls RENAME CONSTRAINT daily_polls_poll_date_key TO weekly_polls_week_start_key")
    op.alter_column("weekly_polls", "poll_date", new_column_name="week_start")

    # вернуть недельные колонки и их check'и
    op.add_column("weekly_polls", sa.Column("reminder_interval_hours", sa.Integer(), server_default="24", nullable=False))
    op.add_column("weekly_polls", sa.Column("max_reminders", sa.Integer(), server_default="3", nullable=False))
    op.create_check_constraint("valid_reminder_interval", "weekly_polls", "reminder_interval_hours > 0")
    op.create_check_constraint("valid_max_reminders", "weekly_polls", "max_reminders > 0")
    op.create_check_constraint(
        "valid_status",
        "weekly_polls",
        "status IN ('active', 'closed', 'cancelled')",
    )
    op.create_index(
        "idx_weekly_polls_active",
        "weekly_polls",
        ["status", "voting_deadline"],
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_foreign_key("poll_slots_poll_id_fkey", "poll_slots", "weekly_polls", ["poll_id"], ["id"])
    op.create_foreign_key("poll_responses_poll_id_fkey", "poll_responses", "weekly_polls", ["poll_id"], ["id"])
    op.create_foreign_key("meeting_instances_poll_id_fkey", "meeting_instances", "weekly_polls", ["poll_id"], ["id"])
    op.create_foreign_key("poll_questions_poll_id_fkey", "poll_questions", "weekly_polls", ["poll_id"], ["id"])
