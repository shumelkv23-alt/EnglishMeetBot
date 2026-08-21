# app/scheduler.py
"""APScheduler: еженедельное создание опросов и ежедневное решение «на завтра».

Джобы (время UTC, часы читаются из config-таблицы):
  - вс 10:00  create_weekly_poll_and_broadcast — опрос на след. неделю + карточки
  - ежедневно 20:00  decide_tomorrow + finalize_expired_weeks
При фиксации встречи ставится date-job напоминания за meeting_reminder_hours
до начала. При старте приложения незакрытые напоминания восстанавливаются
из meeting_instances (иначе рестарт их бы потерял).
"""
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import MeetingInstance, WeeklyPoll
from app.services.poll_logic import MeetingPlan, Slot, plan_week_messages
from app.services.poll_store import (
    config_value,
    create_weekly_poll_and_broadcast,
    decide_tomorrow,
    finalize_expired_weeks,
)

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="utc")

# config.poll_creation_day использует crontab-семантику (0=воскресенье),
# APScheduler — имена дней; маппим явно, чтобы не зависеть от его нумерации
_DOW_NAMES = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")


async def _job_create_weekly_poll() -> None:
    """Вс 10:00 UTC: опрос следующей недели + рассылка карточек."""
    async with AsyncSessionLocal() as db:
        result = await create_weekly_poll_and_broadcast(db)
    logger.info("job_create_weekly_poll done %s", result)


async def _job_daily_decision() -> None:
    """Ежедневно 20:00 UTC: решение по завтрашнему дню + финал истёкших недель."""
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        outcome = await decide_tomorrow(db, now)
        cancelled = await finalize_expired_weeks(db, now)

    decision = outcome["decision"]
    reminder = outcome["reminder"]
    if decision is not None:
        logger.info(
            "job_daily_decision kind=%s day=%s voters=%s",
            decision.kind,
            str(decision.day),
            decision.voters,
        )
    if reminder is not None:
        _schedule_reminder(reminder.send_at, list(reminder.recipients), reminder.text)
    if cancelled:
        logger.info("job_daily_decision cancelled_weeks=%s", cancelled)


# ---------------------------------------------------------------------
# Напоминания о зафиксированной встрече
# ---------------------------------------------------------------------

def _schedule_reminder(send_at: datetime, recipients: list[str], text: str) -> bool:
    """Поставить одноразовую джобу напоминания на send_at."""
    if send_at <= datetime.now(timezone.utc):
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
    """Доставка REMINDER в DM получателям (из MessagePlan).

    Корутина: AsyncIOScheduler выполняет её в главном event loop,
    общий движок БД не трогается из чужих потоков.
    """
    from app.services.poll_store import _deliver_to_users

    delivered = await _deliver_to_users(tuple(recipients), text)
    logger.info("reminder_delivered sent=%s of=%s", delivered, len(recipients))


async def rebuild_pending_reminders() -> int:
    """При старте: восстановить reminder-jobs для незакрытых встреч.

    Для каждой meeting_instances со status='scheduled' и стартом в будущем —
    джоба за meeting_reminder_hours до начала (если время ещё не прошло).
    """
    now = datetime.now(timezone.utc)
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
                day=m.scheduled_start.date(),
                start=m.scheduled_start,
                end=m.scheduled_end,
                location=m.location,
            )
            # Фиктивный получатель: plan_week_messages при [] возвращает [],
            # а здесь нужны только текст и время напоминания
            plans = plan_week_messages(
                MeetingPlan(day=m.scheduled_start.date(), slot=slot),
                recipients=["__rebuild__"],
                reminder_hours=reminder_hours,
            )
            reminders = [p for p in plans if p.kind == "REMINDER"]
            if not reminders or reminders[0].send_at <= now:
                continue
            recipients = await _recipients_for_meeting(db, m.id)
            if _schedule_reminder(
                reminders[0].send_at, recipients, reminders[0].text
            ):
                restored += 1
    if restored:
        logger.info("reminders_restored count=%s", restored)
    return restored


async def _recipients_for_meeting(db, meeting_id: int) -> list[str]:
    """Проголосовавшие за слот зафиксированной встречи."""
    from app.models import PollSlot, PollVote, Profile

    rows = (
        await db.execute(
            select(Profile.workspace_user_id)
            .join(PollVote, PollVote.profile_id == Profile.id)
            .join(PollSlot, PollVote.poll_slot_id == PollSlot.id)
            .join(MeetingInstance, MeetingInstance.selected_slot_id == PollSlot.id)
            .where(MeetingInstance.id == meeting_id)
            .distinct()
        )
    ).scalars().all()
    return [r for r in rows if r]


# ---------------------------------------------------------------------
# Жизненный цикл
# ---------------------------------------------------------------------

async def start_scheduler() -> None:
    """Настроить и запустить планировщик (вызов из lifespan)."""
    async with AsyncSessionLocal() as db:
        creation_day = int(await config_value(db, "poll_creation_day", 0) or 0)
        creation_hour = int(await config_value(db, "poll_creation_hour", 10) or 10)
        creation_minute = int(await config_value(db, "poll_creation_minute", 0) or 0)

    scheduler.add_job(
        _job_create_weekly_poll,
        trigger="cron",
        day_of_week=_DOW_NAMES[creation_day % 7],
        hour=creation_hour,
        minute=creation_minute,
        id="create_weekly_poll",
        replace_existing=True,
    )
    scheduler.add_job(
        _job_daily_decision,
        trigger="cron",
        hour=20,
        minute=0,
        id="daily_decision",
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
