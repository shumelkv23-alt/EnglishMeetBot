# app/scheduler.py
"""APScheduler: ежедневное голосование «в тот же день» (по будням).

Джобы (время в config.app_tz, часы читаются из config-таблицы):
  - пн-пт 9:00   daily_invite    — опрос на сегодня + карточка «придёшь?» в DM
  - пн-пт 13:00  daily_finalize  — слоты с кворумом -> встречи, анонс в группу,
                                    расписание напоминаний за час
  - пн-пт 18:00  daily_checkin   — отметить встречи completed, чек-ин в DM

Напоминания ставятся одноразовой date-джобой за meeting_reminder_hours до
начала встречи. При старте приложения незакрытые напоминания восстанавливаются
из meeting_instances (иначе рестарт их бы потерял).
"""
import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import MeetingInstance
from app.services.poll_logic import APP_TZ, MeetingPlan, Slot, plan_meeting_messages
from app.services.poll_store import (
    _attendee_ids_for_slot,
    config_value,
    create_daily_poll_and_broadcast,
    finalize_today,
    send_daily_checkins,
)
from app.timeutil import app_now

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone=get_settings().app_tz)


async def _job_daily_invite() -> None:
    """Пн-пт 9:00 (config.app_tz): опрос дня + рассылка «придёшь сегодня?»."""
    async with AsyncSessionLocal() as db:
        result = await create_daily_poll_and_broadcast(db)
    logger.info("job_daily_invite done %s", result)


async def _job_daily_finalize() -> None:
    """Пн-пт 13:00 (config.app_tz): финализация + расписание напоминаний."""
    now = app_now()
    async with AsyncSessionLocal() as db:
        outcome = await finalize_today(db, now)

    for reminder in outcome["reminders"]:
        _schedule_reminder(reminder.send_at, list(reminder.recipients), reminder.text)
    logger.info(
        "job_daily_finalize done meetings=%s reminders=%s",
        len(outcome["meetings"]), len(outcome["reminders"]),
    )


async def _job_daily_checkin() -> None:
    """Пн-пт 18:00 (config.app_tz): чек-ин участникам встреч дня."""
    now = app_now()
    async with AsyncSessionLocal() as db:
        sent = await send_daily_checkins(db, now)
    logger.info("job_daily_checkin done sent=%s", sent)


# ---------------------------------------------------------------------
# Напоминания о зафиксированной встрече
# ---------------------------------------------------------------------

def _schedule_reminder(send_at: datetime, recipients: list[str], text: str) -> bool:
    """Поставить одноразовую джобу напоминания на send_at."""
    if send_at <= app_now():
        logger.warning("reminder_in_past_skipped send_at=%s", send_at.isoformat())
        return False
    scheduler.add_job(
        _send_reminder_messages,
        trigger="date",
        run_date=send_at,
        args=[recipients, text],
        id=f"reminder:{send_at.isoformat()}",
        replace_existing=True,
    )
    logger.info(
        "reminder_scheduled at=%s recipients=%s", send_at.isoformat(), len(recipients)
    )
    return True


async def _send_reminder_messages(recipients: list[str], text: str) -> None:
    """Доставка REMINDER в DM получателям."""
    from app.services.poll_store import _deliver_to_users, send_to_group

    delivered = await _deliver_to_users(tuple(recipients), text)
    group_sent = send_to_group(text)
    logger.info(
        "reminder_delivered sent=%s of=%s group=%s", delivered, len(recipients), group_sent
    )


async def rebuild_pending_reminders() -> int:
    """При старте: восстановить reminder-jobs для незакрытых встреч.

    Для каждой meeting_instances со status='scheduled' и стартом в будущем —
    джоба за meeting_reminder_hours до начала (если время ещё не прошло).
    """
    now = app_now()
    restored = 0
    async with AsyncSessionLocal() as db:
        reminder_hours = int(await config_value(db, "meeting_reminder_hours", 1) or 1)
        meetings = (
            await db.execute(
                select(MeetingInstance).where(MeetingInstance.status == "scheduled")
            )
        ).scalars().all()
        for m in meetings:
            if m.scheduled_start <= now:
                continue
            slot = Slot(
                slot_key=f"meeting-{m.id}",
                day=m.scheduled_start.astimezone(APP_TZ).date(),
                start=m.scheduled_start,
                end=m.scheduled_end,
                location=m.location,
            )
            plan = MeetingPlan(day=slot.day, slot=slot)
            recipients = await _attendee_ids_for_slot(db, m.selected_slot_id)
            plans = plan_meeting_messages(plan, recipients, reminder_hours)
            reminders = [p for p in plans if p.kind == "REMINDER"]
            if not reminders or reminders[0].send_at <= now:
                continue
            if _schedule_reminder(
                reminders[0].send_at, recipients, reminders[0].text
            ):
                restored += 1
    if restored:
        logger.info("reminders_restored count=%s", restored)
    return restored


# ---------------------------------------------------------------------
# Жизненный цикл
# ---------------------------------------------------------------------

async def start_scheduler() -> None:
    """Настроить и запустить планировщик (вызов из lifespan)."""
    async with AsyncSessionLocal() as db:
        invite_hour = int(await config_value(db, "daily_poll_hour", 9) or 9)
        close_hour = int(await config_value(db, "daily_poll_close_hour", 13) or 13)
        checkin_hour = int(await config_value(db, "daily_checkin_hour", 18) or 18)

    scheduler.add_job(
        _job_daily_invite,
        trigger="cron",
        day_of_week="mon-fri",
        hour=invite_hour,
        minute=0,
        id="daily_invite",
        replace_existing=True,
    )
    scheduler.add_job(
        _job_daily_finalize,
        trigger="cron",
        day_of_week="mon-fri",
        hour=close_hour,
        minute=0,
        id="daily_finalize",
        replace_existing=True,
    )
    scheduler.add_job(
        _job_daily_checkin,
        trigger="cron",
        day_of_week="mon-fri",
        hour=checkin_hour,
        minute=0,
        id="daily_checkin",
        replace_existing=True,
    )

    try:
        await rebuild_pending_reminders()
    except Exception:
        # БД может быть недоступна при старте — не мешаем подъёму приложения
        logger.exception("rebuild_pending_reminders_failed")

    scheduler.start()
    logger.info(
        "scheduler_started jobs=%s", [j.id for j in scheduler.get_jobs()]
    )


def shutdown_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("scheduler_stopped")
