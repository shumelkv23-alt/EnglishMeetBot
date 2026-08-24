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
    return (_as_utc(now) - _as_utc(base)).days >= days


def should_remind(profile, now: datetime, interval_days: int, max_reminders: int) -> bool:
    """Нужно ли слать напоминание: лимит не исчерпан и интервал выдержан."""
    if profile.reminder_count >= max_reminders:
        return False
    if profile.last_reminder_at is None:
        return True
    return (_as_utc(now) - _as_utc(profile.last_reminder_at)).days >= interval_days


from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.messaging import send_message
from app.models import Profile
from app.schemas import MessagePayload

DEFAULT_DAYS = 7
DEFAULT_INTERVAL_DAYS = 3
DEFAULT_MAX_REMINDERS = 3


def _config_int(raw: object, default: int) -> int:
    """Прочитать целое из config-значения; при мусоре — fallback на default."""
    if not raw:  # None/""/0 → default (как и было: `value or default`)
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        logger.warning("config_invalid_int value=%r fallback=%s", raw, default)
        return default


async def remind_inactive(db: AsyncSession) -> int:
    """Найти неактивных активных участников и отправить им напоминание в DM."""
    from app.services.weekly_poll import get_or_create_config

    days = _config_int(
        (await get_or_create_config(db, "inactivity_reminder_days", DEFAULT_DAYS)).value,
        DEFAULT_DAYS,
    )
    interval = _config_int(
        (await get_or_create_config(db, "inactivity_reminder_interval_days", DEFAULT_INTERVAL_DAYS)).value,
        DEFAULT_INTERVAL_DAYS,
    )
    max_reminders = _config_int(
        (await get_or_create_config(db, "inactivity_max_reminders", DEFAULT_MAX_REMINDERS)).value,
        DEFAULT_MAX_REMINDERS,
    )

    now = datetime.now(timezone.utc)
    profiles = (
        await db.execute(
            select(Profile).where(
                Profile.is_active.is_(True),
                Profile.chat_space_id.isnot(None),
            )
        )
    ).scalars().all()

    sent = 0
    for p in profiles:
        if not is_inactive(p, now, days):
            continue
        if not should_remind(p, now, interval, max_reminders):
            continue
        send_message(p.workspace_user_id, MessagePayload(text=REMINDER_TEXT))
        p.reminder_count += 1
        p.last_reminder_at = now
        sent += 1

    if sent:
        await db.commit()
    logger.info("inactivity_reminders_sent sent=%s", sent)
    return sent
