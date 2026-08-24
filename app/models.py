# app/models.py
# Полная схема БД по спецификации «база данных.docx» — 10 таблиц.
# Время хранится в UTC: DateTime(timezone=True) → TIMESTAMPTZ.
# Денормализованные счётчики (poll_slots.votes_count,
# meeting_instances.participants_count) обновляются триггерами БД —
# см. initial-миграцию в alembic/versions/.
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Profile(Base):
    """Профиль участника (1. profiles)."""

    __tablename__ = "profiles"
    __table_args__ = (
        Index("idx_profiles_email", "user_email"),
        Index("idx_profiles_active", "is_active"),
        Index("idx_profiles_workspace", "workspace_user_id"),
        Index("idx_profiles_level", "english_level"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    user_name: Mapped[str | None] = mapped_column(String(255))
    workspace_user_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    chat_space_id: Mapped[str | None] = mapped_column(String(255))
    onboarding_completed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    onboarding_answers: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    english_level: Mapped[str | None] = mapped_column(String(50))
    interests: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    preferred_days: Mapped[list[str] | None] = mapped_column(ARRAY(String(100)))
    public_consent: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    anonymize_answers: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reminder_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    last_reminder_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DailyPoll(Base):
    """Ежедневный опрос (2. daily_polls). Один опрос = один день."""

    __tablename__ = "daily_polls"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'finalized', 'cancelled')", name="valid_status"),
        Index("idx_daily_polls_date", "poll_date"),
        Index("idx_daily_polls_status", "status"),
        Index("idx_daily_polls_deadline", "voting_deadline"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    poll_date: Mapped[date] = mapped_column(Date, unique=True, nullable=False)
    voting_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        String(50), default="active", server_default=text("'active'"), nullable=False
    )


class PollSlot(Base):
    """Слот времени и места в рамках опроса (3. poll_slots)."""

    __tablename__ = "poll_slots"
    __table_args__ = (
        CheckConstraint("slot_start < slot_end", name="valid_time_range"),
        CheckConstraint("priority >= 0", name="valid_priority"),
        CheckConstraint("votes_count >= 0", name="valid_votes_count"),
        Index("idx_poll_slots_poll", "poll_id"),
        Index("idx_poll_slots_start", "slot_start"),
        Index("idx_poll_slots_location", "location"),
        Index("idx_poll_slots_votes", "votes_count"),
        Index("idx_poll_slots_priority", "priority"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    poll_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("daily_polls.id"), nullable=False
    )
    slot_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    slot_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    location: Mapped[str] = mapped_column(String(255), nullable=False)
    priority: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    # Денормализация: обновляется триггером при добавлении/удалении голосов
    votes_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PollResponse(Base):
    """Статус ответа участника на опрос (4. poll_responses)."""

    __tablename__ = "poll_responses"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'responded', 'not_available')", name="valid_status"
        ),
        CheckConstraint("reminder_count >= 0", name="valid_reminder_count"),
        CheckConstraint(
            "(status = 'responded' AND responded_at IS NOT NULL) OR "
            "(status != 'responded' AND responded_at IS NULL)",
            name="valid_response",
        ),
        Index("idx_poll_responses_unique", "profile_id", "poll_id", unique=True),
        Index("idx_poll_responses_profile", "profile_id"),
        Index("idx_poll_responses_poll", "poll_id"),
        Index("idx_poll_responses_status", "status"),
        Index(
            "idx_poll_responses_next_reminder",
            "next_reminder_at",
            postgresql_where=text("status = 'pending' AND next_reminder_at IS NOT NULL"),
        ),
        Index("idx_poll_responses_reminder_count", "reminder_count"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("profiles.id"), nullable=False
    )
    poll_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("daily_polls.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(50), default="pending", server_default=text("'pending'"), nullable=False
    )
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    reminder_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    last_reminder_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_reminder_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PollVote(Base):
    """Голос участника за слот (5. poll_votes)."""

    __tablename__ = "poll_votes"
    __table_args__ = (
        # UNIQUE из спеки: один голос на пару (участник, слот)
        UniqueConstraint("profile_id", "poll_slot_id", name="unique_profile_slot_vote"),
        Index("idx_poll_votes_response", "poll_response_id"),
        Index("idx_poll_votes_profile", "profile_id"),
        Index("idx_poll_votes_slot", "poll_slot_id"),
        Index("idx_poll_votes_voted_at", "voted_at"),
        Index("idx_poll_votes_profile_slot", "profile_id", "poll_slot_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    poll_response_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("poll_responses.id"), nullable=False
    )
    # Денормализация для быстрых запросов без JOIN с poll_responses
    profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("profiles.id"), nullable=False
    )
    poll_slot_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("poll_slots.id"), nullable=False
    )
    voted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class MeetingInstance(Base):
    """Экземпляр встречи на основе выбранного слота (6. meeting_instances)."""

    __tablename__ = "meeting_instances"
    __table_args__ = (
        CheckConstraint("scheduled_start < scheduled_end", name="valid_time_range"),
        CheckConstraint(
            "status IN ('scheduled', 'completed', 'cancelled')", name="valid_status"
        ),
        CheckConstraint("participants_count >= 0", name="valid_participants_count"),
        Index("idx_meeting_poll", "poll_id"),
        Index("idx_meeting_slot", "selected_slot_id"),
        Index("idx_meeting_status", "status"),
        Index("idx_meeting_scheduled", "scheduled_start"),
        Index("idx_meeting_location", "location"),
        Index(
            "idx_meeting_completed",
            "completed_at",
            postgresql_where=text("status = 'completed'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    poll_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("daily_polls.id"), nullable=False
    )
    selected_slot_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("poll_slots.id"), nullable=False
    )
    scheduled_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scheduled_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    location: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), default="scheduled", server_default=text("'scheduled'"), nullable=False
    )
    activity_type: Mapped[str | None] = mapped_column(String(100))
    activity_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Денормализация: обновляется триггером из attendance
    participants_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Answer(Base):
    """Ответ участника на вопрос (7. answers). История, не перезапись."""

    __tablename__ = "answers"
    __table_args__ = (
        CheckConstraint(
            "(answer_text IS NOT NULL AND answer_choice IS NULL) OR "
            "(answer_text IS NULL AND answer_choice IS NOT NULL) OR "
            "(answer_text IS NOT NULL AND answer_choice IS NOT NULL)",
            name="valid_answer",
        ),
        Index("idx_answers_profile", "profile_id"),
        Index("idx_answers_meeting", "meeting_instance_id"),
        Index("idx_answers_week", "week_start"),
        Index(
            "idx_answers_public", "is_public", postgresql_where=text("is_public = true")
        ),
        Index("idx_answers_rotation", "question_rotation_id"),
        Index("idx_answers_profile_week", "profile_id", "week_start"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("profiles.id"), nullable=False
    )
    meeting_instance_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("meeting_instances.id")
    )
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    answer_text: Mapped[str | None] = mapped_column(Text)
    answer_choice: Mapped[str | None] = mapped_column(String(255))
    is_public: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )
    answered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    question_rotation_id: Mapped[int | None] = mapped_column(Integer)


class Attendance(Base):
    """Учёт посещаемости встречи (8. attendance)."""

    __tablename__ = "attendance"
    __table_args__ = (
        CheckConstraint("source IN ('self_checkin', 'manual')", name="valid_source"),
        CheckConstraint(
            "status IN ('pending', 'present', 'absent')", name="valid_status"
        ),
        CheckConstraint(
            "(source = 'self_checkin' AND checkin_attempted_at IS NOT NULL) OR "
            "(source = 'manual' AND checkin_attempted_at IS NULL)",
            name="valid_checkin",
        ),
        CheckConstraint(
            "(source = 'self_checkin' AND is_within_window IS NOT NULL) OR "
            "(source = 'manual' AND is_within_window IS NULL)",
            name="valid_window",
        ),
        CheckConstraint(
            "(source = 'manual' AND checked_in_by IS NOT NULL) OR "
            "(source = 'self_checkin' AND checked_in_by IS NULL)",
            name="valid_checked_in_by",
        ),
        Index("idx_attendance_unique", "profile_id", "meeting_instance_id", unique=True),
        Index("idx_attendance_profile", "profile_id"),
        Index("idx_attendance_meeting", "meeting_instance_id"),
        Index("idx_attendance_status", "status"),
        Index("idx_attendance_source", "source"),
        Index(
            "idx_attendance_checkin",
            "checkin_attempted_at",
            postgresql_where=text("source = 'self_checkin'"),
        ),
        Index(
            "idx_attendance_window",
            "is_within_window",
            postgresql_where=text("is_within_window = true"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("profiles.id"), nullable=False
    )
    meeting_instance_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("meeting_instances.id"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), default="pending", server_default=text("'pending'"), nullable=False
    )
    checkin_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_within_window: Mapped[bool | None] = mapped_column(Boolean)
    checked_in_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("profiles.id"))
    notes: Mapped[str | None] = mapped_column(Text)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class LeaderboardLedger(Base):
    """Идемпотентный журнал начислений баллов (9. leaderboard_ledger)."""

    __tablename__ = "leaderboard_ledger"
    __table_args__ = (
        UniqueConstraint(
            "profile_id", "meeting_instance_id", "event_type", name="unique_ledger_entry"
        ),
        CheckConstraint(
            "event_type IN ('attendance', 'answer', 'streak', 'mvp', 'bonus')",
            name="valid_event_type",
        ),
        CheckConstraint("points != 0", name="valid_points"),
        Index("idx_ledger_profile", "profile_id"),
        Index("idx_ledger_meeting", "meeting_instance_id"),
        Index("idx_ledger_event_type", "event_type"),
        Index("idx_ledger_event_date", "event_date"),
        Index("idx_ledger_profile_date", "profile_id", "event_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("profiles.id"), nullable=False
    )
    meeting_instance_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("meeting_instances.id")
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    # Колонка metadata в БД; атрибут event_metadata — чтобы не конфликтовать
    # с DeclarativeBase.metadata
    event_metadata: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)
    event_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Config(Base):
    """Системные настройки ключ-значение (10. config)."""

    __tablename__ = "config"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PollQuestion(Base):
    """Сгенерированный LLM-вопрос для конкретного участника недельного опроса (11. poll_questions).

    Только для LLM-вопросов (персональных). Банковский вопрос в БД не хранится:
    он детерминирован по ISO-номеру недели (см. app/services/question_bank.py).
    """

    __tablename__ = "poll_questions"
    __table_args__ = (
        UniqueConstraint("poll_id", "profile_id", name="unique_poll_profile_question"),
        Index("idx_poll_questions_poll", "poll_id"),
        Index("idx_poll_questions_profile", "profile_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    poll_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("daily_polls.id"), nullable=False
    )
    profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("profiles.id"), nullable=False
    )
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
