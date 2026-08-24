"""APScheduler: ежедневный опрос — рассылка в 9:00, финализация в 14:05.

Джобы ENG-7 (напоминания, check-in окно) добавляются из app/services/invites.py
и app/services/checkin.py — сюда они не зашиты.
"""
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime, timezone

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.services.chat_sender import send_message as send_space_message

logger = logging.getLogger(__name__)

scheduler: AsyncIOScheduler | None = None


async def _run_daily_poll() -> None:
    """Джоб 9:00 — создать опрос дня и отправить карточку в группу."""
    from app.services.weekly_poll import (
        build_daily_poll_card,
        ensure_daily_poll,
        get_or_create_config,
    )

    async with AsyncSessionLocal() as db:
        poll = await ensure_daily_poll(db)
        space_id = (await get_or_create_config(db, "space_id", "")).value or ""
        if poll is not None and space_id:
            slots = ["15:00", "16:00", "17:00"]
            card = build_daily_poll_card(slots, get_settings().chat_app_audience)
            send_space_message(
                space_id,
                text="Кто сегодня и во сколько? 🗓️",
                cards_v2=card.get("cardsV2"),
            )
            logger.info("daily_poll_job sent poll=%s space=%s", poll.id, space_id)
        else:
            logger.info("daily_poll_job skipped poll=%s space_id=%r", poll.id if poll else None, space_id)


async def _finalize_daily_poll() -> None:
    """Джоб финализации: подвести итог, создать встречи, запустить ENG-7."""
    from sqlalchemy import select

    from app.models import MeetingInstance
    from app.services.invites import handle_time_finalized
    from app.services.weekly_poll import active_daily_poll, finalize_daily_poll, today

    async with AsyncSessionLocal() as db:
        poll = await active_daily_poll(db, today())
        if poll is None:
            logger.info("daily_finalize_job no_active_poll")
            return
        outcome = await finalize_daily_poll(db, poll)
        result = outcome["result"]
        space_id = outcome.get("space_id") or ""
        if not space_id:
            logger.info("daily_finalize_job done poll=%s status=%s (space_id не задан)",
                        poll.id, poll.status)
            return
        if result["meetings"]:
            meetings = (
                await db.execute(select(MeetingInstance).where(MeetingInstance.poll_id == poll.id))
            ).scalars().all()
            for m in meetings:
                await handle_time_finalized(
                    db, m.id,
                    m.scheduled_start.strftime("%a"),
                    m.scheduled_start.strftime("%H:%M"),
                    scheduled_start=m.scheduled_start,
                )
            for choice, target in result["suggest_to"].items():
                send_space_message(space_id, text=f"Тем, кто выбрал {choice} — встреча также в {target}")
        else:
            send_space_message(space_id, text="Сегодня встреча не набирается — отмена")
        logger.info("daily_finalize_job done poll=%s status=%s", poll.id, poll.status)


async def _run_weekly_questions() -> None:
    """Джоб воскресенье 11:00 — рассылка еженедельных вопросов."""
    from app.services.weekly_questions import send_weekly_questions

    async with AsyncSessionLocal() as db:
        await send_weekly_questions(db)


async def _poll_new_members() -> None:
    """Джоб поллинга: пригласить новых участников группы в онбординг."""
    from app.api.google_chat import _onboarding_card
    from app.messaging import send_message
    from app.schemas import MessagePayload
    from app.services.chat_sender import send_text
    from app.services.space_onboarding import check_new_members
    from app.services.weekly_poll import get_or_create_config

    async with AsyncSessionLocal() as db:
        space_id = (await get_or_create_config(db, "space_id", "")).value or ""
        if not space_id:
            return
        plan = await check_new_members(db, space_id)
        for ws in plan["dm"]:
            send_message(ws, MessagePayload(text="Привет! Заполни короткую анкету 🙌", card=_onboarding_card("друг")))
        if plan["mention"]:
            mentions = " ".join(f"<{m}>" for m in plan["mention"])
            send_text(space_id, f"{mentions} — напишите мне в личку, чтобы пройти анкету 👋")


async def _run_inactivity_reminder() -> None:
    """Джоб: напомнить неактивным участникам о встречах."""
    from app.services.inactivity import remind_inactive

    async with AsyncSessionLocal() as db:
        sent = await remind_inactive(db)
        logger.info("inactivity_reminder_job sent=%s", sent)


async def init_scheduler() -> None:
    """Создать и запустить шедулер; время джобов — из config."""
    global scheduler
    if scheduler is not None:
        return
    from app.services.weekly_poll import get_or_create_config

    async with AsyncSessionLocal() as db:
        run_h = int((await get_or_create_config(db, "poll_run_hour", 9)).value or 9)
        run_m = int((await get_or_create_config(db, "poll_run_minute", 0)).value or 0)
        fin_h = int((await get_or_create_config(db, "poll_finalize_hour", 14)).value or 14)
        fin_m = int((await get_or_create_config(db, "poll_finalize_minute", 5)).value or 5)
        weekly_day = str((await get_or_create_config(db, "weekly_poll_day", "sun")).value or "sun")
        weekly_hour = int((await get_or_create_config(db, "weekly_poll_hour", 11)).value or 11)
        rem_h = int((await get_or_create_config(db, "inactivity_reminder_hour", 11)).value or 11)

    scheduler = AsyncIOScheduler(timezone=get_settings().app_timezone)
    scheduler.add_job(
        _run_daily_poll,
        "cron",
        hour=run_h,
        minute=run_m,
        id="daily-poll",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        _finalize_daily_poll,
        "cron",
        hour=fin_h,
        minute=fin_m,
        id="daily-finalize",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        _run_weekly_questions,
        "cron",
        day_of_week=weekly_day,
        hour=weekly_hour,
        minute=0,
        id="weekly-questions",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        _poll_new_members,
        "interval",
        minutes=10,
        id="onboarding-poll",
        replace_existing=True,
    )
    scheduler.add_job(
        _run_inactivity_reminder,
        "cron",
        hour=rem_h,
        minute=0,
        id="inactivity-reminder",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.start()
    logger.info("scheduler_started")


def shutdown_scheduler() -> None:
    global scheduler
    if scheduler is not None:
        scheduler.shutdown(wait=False)
        scheduler = None
        logger.info("scheduler_stopped")
