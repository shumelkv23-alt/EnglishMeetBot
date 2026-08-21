"""initial schema — полная схема по спеке «база данных.docx» (10 таблиц)

Revision ID: 0001
Revises:
Create Date: 2026-08-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. profiles
    op.create_table(
        "profiles",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("user_email", sa.String(length=255), nullable=False),
        sa.Column("user_name", sa.String(length=255), nullable=True),
        sa.Column("workspace_user_id", sa.String(length=255), nullable=True),
        sa.Column("chat_space_id", sa.String(length=255), nullable=True),
        sa.Column(
            "onboarding_completed",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("onboarding_answers", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("english_level", sa.String(length=50), nullable=True),
        sa.Column("interests", sa.dialects.postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column(
            "preferred_days",
            sa.dialects.postgresql.ARRAY(sa.String(length=100)),
            nullable=True,
        ),
        sa.Column(
            "public_consent", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "anonymize_answers", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_email"),
        sa.UniqueConstraint("workspace_user_id"),
    )
    op.create_index("idx_profiles_email", "profiles", ["user_email"])
    op.create_index("idx_profiles_active", "profiles", ["is_active"])
    op.create_index("idx_profiles_workspace", "profiles", ["workspace_user_id"])
    op.create_index("idx_profiles_level", "profiles", ["english_level"])

    # 2. weekly_polls
    op.create_table(
        "weekly_polls",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("voting_deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "reminder_interval_hours",
            sa.Integer(),
            server_default=sa.text("24"),
            nullable=False,
        ),
        sa.Column("max_reminders", sa.Integer(), server_default=sa.text("3"), nullable=False),
        sa.Column(
            "status",
            sa.String(length=50),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("week_start"),
        sa.CheckConstraint("status IN ('active', 'closed', 'cancelled')", name="valid_status"),
        sa.CheckConstraint("reminder_interval_hours > 0", name="valid_reminder_interval"),
        sa.CheckConstraint("max_reminders > 0", name="valid_max_reminders"),
    )
    op.create_index("idx_weekly_polls_week", "weekly_polls", ["week_start"])
    op.create_index("idx_weekly_polls_status", "weekly_polls", ["status"])
    op.create_index("idx_weekly_polls_deadline", "weekly_polls", ["voting_deadline"])
    op.create_index(
        "idx_weekly_polls_active",
        "weekly_polls",
        ["status", "voting_deadline"],
        postgresql_where=sa.text("status = 'active'"),
    )

    # 3. poll_slots
    op.create_table(
        "poll_slots",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("poll_id", sa.BigInteger(), nullable=False),
        sa.Column("slot_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("slot_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("location", sa.String(length=255), nullable=False),
        sa.Column("priority", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("votes_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["poll_id"], ["weekly_polls.id"]),
        sa.CheckConstraint("slot_start < slot_end", name="valid_time_range"),
        sa.CheckConstraint("priority >= 0", name="valid_priority"),
        sa.CheckConstraint("votes_count >= 0", name="valid_votes_count"),
    )
    op.create_index("idx_poll_slots_poll", "poll_slots", ["poll_id"])
    op.create_index("idx_poll_slots_start", "poll_slots", ["slot_start"])
    op.create_index("idx_poll_slots_location", "poll_slots", ["location"])
    op.create_index("idx_poll_slots_votes", "poll_slots", ["votes_count"])
    op.create_index("idx_poll_slots_priority", "poll_slots", ["priority"])

    # 4. poll_responses
    op.create_table(
        "poll_responses",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("poll_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=50),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("reminder_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_reminder_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_reminder_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"]),
        sa.ForeignKeyConstraint(["poll_id"], ["weekly_polls.id"]),
        sa.CheckConstraint(
            "status IN ('pending', 'responded', 'skipped')", name="valid_status"
        ),
        sa.CheckConstraint("reminder_count >= 0", name="valid_reminder_count"),
        sa.CheckConstraint(
            "(status = 'responded' AND responded_at IS NOT NULL) OR "
            "(status != 'responded' AND responded_at IS NULL)",
            name="valid_response",
        ),
    )
    op.create_index(
        "idx_poll_responses_unique", "poll_responses", ["profile_id", "poll_id"], unique=True
    )
    op.create_index("idx_poll_responses_profile", "poll_responses", ["profile_id"])
    op.create_index("idx_poll_responses_poll", "poll_responses", ["poll_id"])
    op.create_index("idx_poll_responses_status", "poll_responses", ["status"])
    op.create_index(
        "idx_poll_responses_next_reminder",
        "poll_responses",
        ["next_reminder_at"],
        postgresql_where=sa.text("status = 'pending' AND next_reminder_at IS NOT NULL"),
    )
    op.create_index(
        "idx_poll_responses_reminder_count", "poll_responses", ["reminder_count"]
    )

    # 5. poll_votes
    op.create_table(
        "poll_votes",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("poll_response_id", sa.BigInteger(), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("poll_slot_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "voted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["poll_response_id"], ["poll_responses.id"]),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"]),
        sa.ForeignKeyConstraint(["poll_slot_id"], ["poll_slots.id"]),
        sa.UniqueConstraint("profile_id", "poll_slot_id", name="unique_profile_slot_vote"),
    )
    op.create_index("idx_poll_votes_response", "poll_votes", ["poll_response_id"])
    op.create_index("idx_poll_votes_profile", "poll_votes", ["profile_id"])
    op.create_index("idx_poll_votes_slot", "poll_votes", ["poll_slot_id"])
    op.create_index("idx_poll_votes_voted_at", "poll_votes", ["voted_at"])
    op.create_index(
        "idx_poll_votes_profile_slot", "poll_votes", ["profile_id", "poll_slot_id"]
    )

    # 6. meeting_instances
    op.create_table(
        "meeting_instances",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("poll_id", sa.BigInteger(), nullable=False),
        sa.Column("selected_slot_id", sa.BigInteger(), nullable=False),
        sa.Column("scheduled_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scheduled_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("location", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.String(length=50),
            server_default=sa.text("'scheduled'"),
            nullable=False,
        ),
        sa.Column("activity_type", sa.String(length=100), nullable=True),
        sa.Column("activity_data", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column(
            "participants_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["poll_id"], ["weekly_polls.id"]),
        sa.ForeignKeyConstraint(["selected_slot_id"], ["poll_slots.id"]),
        sa.CheckConstraint("scheduled_start < scheduled_end", name="valid_time_range"),
        sa.CheckConstraint(
            "status IN ('scheduled', 'completed', 'cancelled')", name="valid_status"
        ),
        sa.CheckConstraint("participants_count >= 0", name="valid_participants_count"),
    )
    op.create_index("idx_meeting_poll", "meeting_instances", ["poll_id"])
    op.create_index("idx_meeting_slot", "meeting_instances", ["selected_slot_id"])
    op.create_index("idx_meeting_status", "meeting_instances", ["status"])
    op.create_index("idx_meeting_scheduled", "meeting_instances", ["scheduled_start"])
    op.create_index("idx_meeting_location", "meeting_instances", ["location"])
    op.create_index(
        "idx_meeting_completed",
        "meeting_instances",
        ["completed_at"],
        postgresql_where=sa.text("status = 'completed'"),
    )

    # 7. answers
    op.create_table(
        "answers",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("meeting_instance_id", sa.BigInteger(), nullable=True),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=True),
        sa.Column("answer_choice", sa.String(length=255), nullable=True),
        sa.Column("is_public", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "answered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("question_rotation_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"]),
        sa.ForeignKeyConstraint(["meeting_instance_id"], ["meeting_instances.id"]),
        sa.CheckConstraint(
            "(answer_text IS NOT NULL AND answer_choice IS NULL) OR "
            "(answer_text IS NULL AND answer_choice IS NOT NULL) OR "
            "(answer_text IS NOT NULL AND answer_choice IS NOT NULL)",
            name="valid_answer",
        ),
    )
    op.create_index("idx_answers_profile", "answers", ["profile_id"])
    op.create_index("idx_answers_meeting", "answers", ["meeting_instance_id"])
    op.create_index("idx_answers_week", "answers", ["week_start"])
    op.create_index(
        "idx_answers_public",
        "answers",
        ["is_public"],
        postgresql_where=sa.text("is_public = true"),
    )
    op.create_index("idx_answers_rotation", "answers", ["question_rotation_id"])
    op.create_index("idx_answers_profile_week", "answers", ["profile_id", "week_start"])

    # 8. attendance
    op.create_table(
        "attendance",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("meeting_instance_id", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column(
            "status",
            sa.String(length=50),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("checkin_attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_within_window", sa.Boolean(), nullable=True),
        sa.Column("checked_in_by", sa.BigInteger(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"]),
        sa.ForeignKeyConstraint(["meeting_instance_id"], ["meeting_instances.id"]),
        sa.ForeignKeyConstraint(["checked_in_by"], ["profiles.id"]),
        sa.CheckConstraint("source IN ('self_checkin', 'manual')", name="valid_source"),
        sa.CheckConstraint(
            "status IN ('pending', 'present', 'absent')", name="valid_status"
        ),
        sa.CheckConstraint(
            "(source = 'self_checkin' AND checkin_attempted_at IS NOT NULL) OR "
            "(source = 'manual' AND checkin_attempted_at IS NULL)",
            name="valid_checkin",
        ),
        sa.CheckConstraint(
            "(source = 'self_checkin' AND is_within_window IS NOT NULL) OR "
            "(source = 'manual' AND is_within_window IS NULL)",
            name="valid_window",
        ),
        sa.CheckConstraint(
            "(source = 'manual' AND checked_in_by IS NOT NULL) OR "
            "(source = 'self_checkin' AND checked_in_by IS NULL)",
            name="valid_checked_in_by",
        ),
    )
    op.create_index(
        "idx_attendance_unique",
        "attendance",
        ["profile_id", "meeting_instance_id"],
        unique=True,
    )
    op.create_index("idx_attendance_profile", "attendance", ["profile_id"])
    op.create_index("idx_attendance_meeting", "attendance", ["meeting_instance_id"])
    op.create_index("idx_attendance_status", "attendance", ["status"])
    op.create_index("idx_attendance_source", "attendance", ["source"])
    op.create_index(
        "idx_attendance_checkin",
        "attendance",
        ["checkin_attempted_at"],
        postgresql_where=sa.text("source = 'self_checkin'"),
    )
    op.create_index(
        "idx_attendance_window",
        "attendance",
        ["is_within_window"],
        postgresql_where=sa.text("is_within_window = true"),
    )

    # 9. leaderboard_ledger
    op.create_table(
        "leaderboard_ledger",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("meeting_instance_id", sa.BigInteger(), nullable=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("metadata", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("event_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"]),
        sa.ForeignKeyConstraint(["meeting_instance_id"], ["meeting_instances.id"]),
        sa.UniqueConstraint(
            "profile_id", "meeting_instance_id", "event_type", name="unique_ledger_entry"
        ),
        sa.CheckConstraint(
            "event_type IN ('attendance', 'answer', 'streak', 'mvp', 'bonus')",
            name="valid_event_type",
        ),
        sa.CheckConstraint("points != 0", name="valid_points"),
    )
    op.create_index("idx_ledger_profile", "leaderboard_ledger", ["profile_id"])
    op.create_index("idx_ledger_meeting", "leaderboard_ledger", ["meeting_instance_id"])
    op.create_index("idx_ledger_event_type", "leaderboard_ledger", ["event_type"])
    op.create_index("idx_ledger_event_date", "leaderboard_ledger", ["event_date"])
    op.create_index(
        "idx_ledger_profile_date", "leaderboard_ledger", ["profile_id", "event_date"]
    )

    # 10. config
    op.create_table(
        "config",
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("value", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key"),
    )

    # Триггер: пересчёт poll_slots.votes_count при добавлении/удалении голосов
    op.execute(
        """
        CREATE OR REPLACE FUNCTION update_poll_slot_votes_count() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                UPDATE poll_slots
                SET votes_count = (
                    SELECT COUNT(*) FROM poll_votes WHERE poll_slot_id = NEW.poll_slot_id
                )
                WHERE id = NEW.poll_slot_id;
            ELSE
                UPDATE poll_slots
                SET votes_count = (
                    SELECT COUNT(*) FROM poll_votes WHERE poll_slot_id = OLD.poll_slot_id
                )
                WHERE id = OLD.poll_slot_id;
            END IF;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_poll_votes_votes_count
        AFTER INSERT OR DELETE ON poll_votes
        FOR EACH ROW EXECUTE FUNCTION update_poll_slot_votes_count();
        """
    )

    # Триггер: пересчёт meeting_instances.participants_count из attendance
    op.execute(
        """
        CREATE OR REPLACE FUNCTION update_meeting_participants_count() RETURNS trigger AS $$
        BEGIN
            UPDATE meeting_instances
            SET participants_count = (
                SELECT COUNT(*) FROM attendance
                WHERE meeting_instance_id = NEW.meeting_instance_id
                  AND status = 'present'
            )
            WHERE id = NEW.meeting_instance_id;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_attendance_participants_count
        AFTER INSERT OR UPDATE OF status ON attendance
        FOR EACH ROW EXECUTE FUNCTION update_meeting_participants_count();
        """
    )

    # Сидинг config дефолтами из раздела 10 спеки
    op.execute(
        """
        INSERT INTO config (key, value, description) VALUES
        ('poll_creation_day', '1', 'День недели для создания опроса (0=воскресенье, 1=понедельник)'),
        ('poll_creation_hour', '10', 'Время создания опроса (часы, 0-23)'),
        ('poll_creation_minute', '0', 'Время создания опроса (минуты, 0-59)'),
        ('voting_deadline_offset_hours', '72', 'Через сколько часов после создания опроса закрыть голосование'),
        ('quorum_threshold', '3', 'Минимальное количество участников для встречи'),
        ('max_slots_per_poll', '10', 'Максимальное количество слотов в одном опросе'),
        ('default_slots', '[]', 'Слоты по умолчанию, если организатор не задал свои'),
        ('poll_reminder_start_hours', '48', 'Через сколько часов после создания опроса отправить первое напоминание'),
        ('poll_reminder_interval_hours', '24', 'Интервал между напоминаниями (часы)'),
        ('poll_max_reminders', '3', 'Максимальное количество напоминаний на участника'),
        ('meeting_reminder_hours', '1', 'За сколько часов до встречи отправить напоминание'),
        ('checkin_window_minutes', '15', 'Окно для self-check-in (± минут от начала встречи)'),
        ('checkin_button_active_minutes', '30', 'Сколько минут активна кнопка "Я на встрече"'),
        ('points_attendance', '10', 'Баллы за посещение встречи'),
        ('points_answer', '5', 'Баллы за ответ на еженедельный вопрос'),
        ('points_streak', '5', 'Бонусные баллы за streak (серию посещений)'),
        ('points_mvp', '15', 'Баллы за MVP встречи'),
        ('streak_weeks_required', '3', 'Сколько недель подряд нужно для получения streak-бонуса'),
        ('available_locations', '["Conference Room A"]', 'Список доступных мест для встреч'),
        ('default_location', '"Conference Room A"', 'Место по умолчанию, если не указано другое'),
        ('onboarding_reminder_days', '3', 'Через сколько дней напомнить о завершении онбординга'),
        ('max_inactive_days', '30', 'Через сколько дней без активности автоматически деактивировать участника'),
        ('leaderboard_top_count', '10', 'Количество участников в топе лидерборда'),
        ('leaderboard_reset_interval', '"quarterly"', 'Период сброса лидерборда: weekly, monthly, quarterly'),
        ('activity_types_active', '["digest", "guess_colleague"]', 'Активные типы активностей на текущий момент')
        ON CONFLICT (key) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_attendance_participants_count ON attendance")
    op.execute("DROP TRIGGER IF EXISTS trg_poll_votes_votes_count ON poll_votes")
    op.execute("DROP FUNCTION IF EXISTS update_meeting_participants_count()")
    op.execute("DROP FUNCTION IF EXISTS update_poll_slot_votes_count()")
    op.drop_table("config")
    op.drop_table("leaderboard_ledger")
    op.drop_table("attendance")
    op.drop_table("answers")
    op.drop_table("meeting_instances")
    op.drop_table("poll_votes")
    op.drop_table("poll_responses")
    op.drop_table("poll_slots")
    op.drop_table("weekly_polls")
    op.drop_table("profiles")
