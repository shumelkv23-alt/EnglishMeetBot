"""APScheduler: еженедельная рассылка опросов.

Джобы ENG-7 (напоминания, check-in окно) добавляются из app/services/invites.py
и app/services/checkin.py — сюда они не зашиты.
"""
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime, timezone

from app.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

scheduler: AsyncIOScheduler | None = None


async def _run_weekly_poll() -> None:
    from app.services.weekly_poll import send_weekly_polls

    async with AsyncSessionLocal() as db:
        result = await send_weekly_polls(db, datetime.now(timezone.utc))
        logger.info("weekly_poll_job done result=%s", result)


def init_scheduler() -> None:
    """Создать и запустить шедулер с еженедельным джобом опроса."""
    global scheduler
    if scheduler is not None:
        return
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        _run_weekly_poll,
        "cron",
        day_of_week="mon",
        hour=10,
        minute=0,
        id="weekly-poll",
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