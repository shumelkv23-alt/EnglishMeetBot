"""Напоминания о неактивности: определение и сброс «последней активности»."""
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

REMINDER_TEXT = (
    "Привет! 👋 Давно тебя не было. У нас каждый день короткие встречи по английскому — "
    "заглядывай, если будет минутка. Если формат не зашёл — просто напиши, подстроимся."
)


def touch_activity(profile, now: datetime) -> None:
    """Зафиксировать активность: обновить время и сбросить счётчик напоминаний."""
    profile.last_activity_at = now
    profile.reminder_count = 0
    profile.last_reminder_at = None


def _as_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def is_inactive(profile, now: datetime, days: int) -> bool:
    """Неактивен ли профиль: с последней активности прошло >= days.
    Если last_activity_at не задан — точкой отсчёта служит created_at."""
    base = profile.last_activity_at or profile.created_at
    if base is None:
        return False
    return (now - _as_utc(base)).days >= days


def should_remind(profile, now: datetime, interval_days: int, max_reminders: int) -> bool:
    """Нужно ли слать напоминание: лимит не исчерпан и интервал выдержан."""
    if profile.reminder_count >= max_reminders:
        return False
    if profile.last_reminder_at is None:
        return True
    return (now - _as_utc(profile.last_reminder_at)).days >= interval_days
