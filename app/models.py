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
from sqlalchemy.ext.mutable import MutableDict
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
            "event_type IN ('attendance', 'answer', 'streak', 'mvp', 'bonus', 'game')",
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


class WeeklyQuestion(Base):
    """Заданный участнику вопрос недели (12. weekly_questions).

    История вопросов, чтобы не повторять одни и те же формулировки одному
    участнику. Пишется при каждой отправке вопросов (LLM и банк).
    """

    __tablename__ = "weekly_questions"
    __table_args__ = (
        Index("idx_weekly_questions_profile", "profile_id"),
        Index("idx_weekly_questions_asked_at", "asked_at"),
        Index("idx_weekly_questions_profile_week", "profile_id", "week_start"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("profiles.id"), nullable=False
    )
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    asked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Game(Base):
    """Игровая сессия (13. games). Одна запись = одна партия игры-активности.

    Сейчас используется для игры Alias (командная игра в слова).
    """

    __tablename__ = "games"
    __table_args__ = (
        CheckConstraint("status IN ('setup', 'active', 'finished')", name="valid_game_status"),
        Index("idx_games_space", "space_id"),
        Index("idx_games_status", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), default="setup", server_default=text("'setup'"), nullable=False
    )
    target_score: Mapped[int] = mapped_column(
        Integer, default=15, server_default=text("15"), nullable=False
    )
    round_seconds: Mapped[int] = mapped_column(
        Integer, default=60, server_default=text("60"), nullable=False
    )
    # Имя сообщения со счётом в группе (для обновления на месте через messages.patch)
    scoreboard_message_name: Mapped[str | None] = mapped_column(String(255))
    # Победитель — просто id команды (без FK, чтобы не плодить циклическую связь)
    winner_team_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class GameTeam(Base):
    """Команда в рамках игровой сессии (14. game_teams)."""

    __tablename__ = "game_teams"
    __table_args__ = (
        Index("idx_game_teams_game", "game_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    game_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("games.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    emoji: Mapped[str] = mapped_column(String(20), nullable=False)
    score: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class GamePlayer(Base):
    """Участник игровой сессии и его команда (15. game_players)."""

    __tablename__ = "game_players"
    __table_args__ = (
        UniqueConstraint("game_id", "profile_id", name="unique_game_player"),
        Index("idx_game_players_game", "game_id"),
        Index("idx_game_players_team", "team_id"),
        Index("idx_game_players_profile", "profile_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    game_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("games.id"), nullable=False
    )
    team_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("game_teams.id"), nullable=False
    )
    profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("profiles.id"), nullable=False
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class GameRound(Base):
    """Раунд игры (16. game_rounds). Один раунд = ход одной команды (60 сек)."""

    __tablename__ = "game_rounds"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'time_up', 'confirming', 'confirmed')",
            name="valid_round_status",
        ),
        Index("idx_game_rounds_game", "game_id"),
        Index("idx_game_rounds_team", "team_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    game_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("games.id"), nullable=False
    )
    team_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("game_teams.id"), nullable=False
    )
    explainer_profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("profiles.id"), nullable=False
    )
    # Слово, которое сейчас на столе (нужно для «последнего слова» после таймера)
    current_word: Mapped[str | None] = mapped_column(String(100))
    # Имя DM-сообщения объясняющего с карточкой слова (для patch при таймере)
    word_message_name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(
        String(50), default="active", server_default=text("'active'"), nullable=False
    )
    # Ручная правка итога раунда (кнопки «+1 / −1» на подтверждении)
    points_adjustment: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GameWordEvent(Base):
    """Одно слово в раунде и его исход (17. game_word_events).

    Лог для разбора раунда и подтверждения счёта объясняющим.
    """

    __tablename__ = "game_word_events"
    __table_args__ = (
        Index("idx_game_word_events_round", "round_id"),
        Index("idx_game_word_events_team", "team_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    round_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("game_rounds.id"), nullable=False
    )
    word: Mapped[str] = mapped_column(String(100), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)  # 'guessed' | 'skipped'
    points: Mapped[int] = mapped_column(Integer, nullable=False)  # +1 или -1
    team_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("game_teams.id"), nullable=False
    )
    is_last: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SnakeGame(Base):
    """Сессия игры Snake Oil / «Змеиное масло» (18. snake_games)."""

    __tablename__ = "snake_games"
    __table_args__ = (
        CheckConstraint(
            "status IN ('setup', 'active', 'finished')", name="valid_snake_game_status"
        ),
        Index("idx_snake_games_space", "space_id"),
        Index("idx_snake_games_status", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), default="setup", server_default=text("'setup'"), nullable=False
    )
    target_score: Mapped[int] = mapped_column(
        Integer, default=3, server_default=text("3"), nullable=False
    )
    # Имя сообщения со счётом в группе (для обновления на месте через messages.patch)
    scoreboard_message_name: Mapped[str | None] = mapped_column(String(255))
    # Имя сообщения с карточкой текущего раунда (тоже патчится на месте, а не шлётся заново)
    round_message_name: Mapped[str | None] = mapped_column(String(255))
    # Победитель — id профиля (без FK, чтобы не плодить циклическую связь)
    winner_profile_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SnakePlayer(Base):
    """Участник игры Snake Oil и его счёт (19. snake_players)."""

    __tablename__ = "snake_players"
    __table_args__ = (
        UniqueConstraint("game_id", "profile_id", name="unique_snake_player"),
        Index("idx_snake_players_game", "game_id"),
        Index("idx_snake_players_profile", "profile_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    game_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("snake_games.id"), nullable=False
    )
    profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("profiles.id"), nullable=False
    )
    score: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SnakeRound(Base):
    """Раунд игры Snake Oil: покупатель, роль, проблема, победитель (20. snake_rounds)."""

    __tablename__ = "snake_rounds"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'finished')", name="valid_snake_round_status"),
        Index("idx_snake_rounds_game", "game_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    game_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("snake_games.id"), nullable=False
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    customer_profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("profiles.id"), nullable=False
    )
    persona: Mapped[str] = mapped_column(String(100), nullable=False)
    problem: Mapped[str] = mapped_column(String(255), nullable=False)
    winner_profile_id: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(
        String(50), default="active", server_default=text("'active'"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SnakeOffer(Base):
    """Предложение продавца в раунде: пара слов для товара (21. snake_offers)."""

    __tablename__ = "snake_offers"
    __table_args__ = (
        UniqueConstraint("round_id", "seller_profile_id", name="unique_snake_offer"),
        Index("idx_snake_offers_round", "round_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    round_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("snake_rounds.id"), nullable=False
    )
    seller_profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("profiles.id"), nullable=False
    )
    word1: Mapped[str] = mapped_column(String(100), nullable=False)
    word2: Mapped[str] = mapped_column(String(100), nullable=False)


class GameSession(Base):
    """Активная игровая сессия (22. game_sessions) — игры «Кто я?» / Quiplash.

    Живое состояние (раунд, ответы, голоса, очки, секреты) хранится в JSONB `state`,
    поэтому переживает рестарты приложения. Очки подбиваются в leaderboard_ledger
    при завершении игры (event_type 'game').
    """

    __tablename__ = "game_sessions"
    __table_args__ = (
        CheckConstraint("game_type IN ('who_am_i', 'quiplash')", name="valid_game_type"),
        CheckConstraint(
            "status IN ('active', 'finished', 'cancelled')", name="valid_game_status"
        ),
        Index("idx_game_sessions_space_status", "space_name", "status"),
        Index("idx_game_sessions_meeting", "meeting_instance_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    meeting_instance_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("meeting_instances.id")
    )
    space_name: Mapped[str] = mapped_column(String(255), nullable=False)
    game_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), default="active", server_default=text("'active'"), nullable=False
    )
    topic: Mapped[str | None] = mapped_column(String(255))
    state: Mapped[dict[str, Any] | None] = mapped_column(MutableDict.as_mutable(JSONB))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
