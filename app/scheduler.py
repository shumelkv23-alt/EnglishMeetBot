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
        now = datetime.now(timezone.utc)
        poll = await ensure_daily_poll(db, now)
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
    """Джоб 14:05 — подвести итог опроса дня и оповестить группу."""
    from app.services.weekly_poll import active_daily_poll, finalize_daily_poll

    async with AsyncSessionLocal() as db:
        poll = await active_daily_poll(db, datetime.now(timezone.utc).date())
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
            for t in result["meetings"]:
                send_space_message(space_id, text=f"Встреча сегодня в {t} 🎉")
            for choice, target in result["suggest_to"].items():
                send_space_message(space_id, text=f"Тем, кто выбрал {choice} — встреча также в {target}")
        else:
            send_space_message(space_id, text="Сегодня встреча не набирается — отмена")
        logger.info("daily_finalize_job done poll=%s status=%s", poll.id, poll.status)


def init_scheduler() -> None:
    """Создать и запустить шедулер с ежедневными джобами опроса."""
    global scheduler
    if scheduler is not None:
        return
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        _run_daily_poll,
        "cron",
        hour=9,
        minute=0,
        id="daily-poll",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        _finalize_daily_poll,
        "cron",
        hour=14,
        minute=5,
        id="daily-finalize",
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
