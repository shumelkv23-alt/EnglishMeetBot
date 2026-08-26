"""Приглашения: персональные, пост в Space, эскалация организатору (REQ-5, REQ-9.5)."""
from app.schemas import Activity


def _theme_from_activity(activity: Activity | None) -> str | None:
    """Тема встречи из Activity (ENG-8) или None."""
    if activity is None:
        return None
    content = activity.content or {}
    title = content.get("title") or content.get("kind")
    return title if isinstance(title, str) and title else None


def build_invite_text(day: str, time: str, theme: str | None) -> str:
    """Персональное приглашение: время + тема (REQ-5.1)."""
    base = f"English meetup: {day} at {time} 📅"
    if theme:
        return f"{base}\n\nMeetup topic: {theme}"
    return base


def build_escalation_text() -> str:
    """Сообщение организатору при не набранном кворуме (REQ-9.5, REQ-3.5)."""
    return (
        "Couldn't pick a meetup time this week: quorum not met. "
        "Decide manually or set new slots, please. 🙏"
    )


# --- БД-часть ---
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.messaging import send_message
from app.services.chat_sender import send_message as send_space_message, send_text
from app.models import Config, MeetingInstance as MeetingORM
from app.schemas import MessagePayload
from app.services.checkin import checkin_window, build_checkin_card, job_ids as checkin_job_ids
from app.services.invites import _theme_from_activity  # noqa: F401  (переэкспорт для API)
from app.services.reminders import reminder_at, reminder_job_id

logger = logging.getLogger(__name__)


async def _config_value(db: AsyncSession, key: str, default=None):
    cfg = (await db.execute(select(Config).where(Config.key == key))).scalar_one_or_none()
    return cfg.value if cfg is not None else default


def _scheduler() -> object | None:
    from app.scheduler import scheduler

    return scheduler


async def handle_time_finalized(
    db: AsyncSession, instance_id: int, day: str, time: str,
    activity: Activity | None = None, scheduled_start: datetime | None = None,
) -> dict:
    """При TIME_FINALIZED: пост в Space (время встречи) + джобы напоминания и check-in окна.

    Личные приглашения в DM не шлём — только уведомление в общую группу.
    """
    theme_text = _theme_from_activity(activity)
    text = build_invite_text(day, time, theme_text)

    space_id = await _config_value(db, "space_id", "")
    if space_id:
        send_text(space_id, f"🗓️ {text}")

    sch = _scheduler()
    if scheduled_start is not None and sch is not None:
        lead_hours = int(await _config_value(db, "meet_reminder_hours", 1) or 1)
        sch.add_job(
            _send_reminder, "date",
            run_date=reminder_at(scheduled_start, lead_hours),
            id=reminder_job_id(str(instance_id)),
            replace_existing=True,
            args=[str(instance_id)],
        )
        duration = int(await _config_value(db, "meeting_duration_minutes", 60) or 60)
        open_at, close_at = checkin_window(scheduled_start, scheduled_start + timedelta(minutes=duration))
        sch.add_job(
            _open_checkin, "date", run_date=open_at,
            id=checkin_job_ids(str(instance_id))["open"], replace_existing=True,
            args=[space_id, build_checkin_card(str(instance_id), action_url=get_settings().chat_app_audience)],
        )
        sch.add_job(
            _close_checkin, "date", run_date=close_at,
            id=checkin_job_ids(str(instance_id))["close"], replace_existing=True,
        )
        # Карточка занятия (движок разнообразия) — отдельный модуль app/cards
        from app.cards.service import schedule_card_for_meeting

        await schedule_card_for_meeting(db, instance_id, scheduled_start)

    logger.info("time_finalized_handled instance=%s", instance_id)
    return {"invited": 0}


async def handle_escalated(db: AsyncSession, instance_id: int) -> dict:
    """При ESCALATED: одно сообщение организатору, участникам ничего (REQ-9.5, REQ-3.5)."""
    organizer = await _config_value(db, "organizer_user_id", "")
    if not organizer:
        logger.warning("escalated_no_organizer instance=%s", instance_id)
        return {"notified": False}
    send_message(organizer, MessagePayload(text=build_escalation_text()))
    logger.info("escalated_notified instance=%s", instance_id)
    return {"notified": True}


async def _send_reminder(instance_id: str) -> None:
    """Напоминание за lead_hours до встречи — в общий Space (REQ-9.2)."""
    async with AsyncSessionLocal() as db:
        meeting = (
            await db.execute(select(MeetingORM).where(MeetingORM.id == int(instance_id)))
        ).scalar_one_or_none()
        if meeting is None:
            logger.warning("reminder_no_meeting instance=%s", instance_id)
            return
        text = build_invite_text(
            meeting.scheduled_start.strftime("%a"),
            meeting.scheduled_start.strftime("%H:%M"),
            None,
        )
        space_id = await _config_value(db, "space_id", "")
        if space_id:
            send_text(space_id, f"⏰ English meetup in an hour!\n\n{text}")
        logger.info("reminder_sent instance=%s", instance_id)


def _open_checkin(space_id: str, card: dict) -> None:
    """Открытие окна: карточка с кнопкой «Я на встрече» в общий Space."""
    if space_id:
        send_space_message(space_id, text="The meetup is starting — check in! ✅", cards_v2=card.get("cardsV2"))


def _close_checkin() -> None:
    """Закрытие окна: ничего не шлём (REQ-9.6 — вне окна кнопка не работает)."""
    logger.info("checkin_window_closed")