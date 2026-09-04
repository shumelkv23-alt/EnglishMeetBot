"""APScheduler: ежедневный опрос — рассылка в 9:00, финализация в 14:05.

Джобы ENG-7 (напоминания, check-in окно) добавляются из app/services/invites.py
и app/services/checkin.py — сюда они не зашиты.
"""
import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime, timedelta, timezone

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.services.chat_sender import send_message as send_space_message

logger = logging.getLogger(__name__)

scheduler: AsyncIOScheduler | None = None


async def _run_weekly_poll() -> None:
    """Джоб в понедельник — создать опрос недели (день+время) и отправить карточку в группу."""
    from app.services.weekly_poll import ensure_weekly_poll, send_weekly_poll_card

    async with AsyncSessionLocal() as db:
        poll = await ensure_weekly_poll(db)
        await send_weekly_poll_card(db, poll)
        logger.info("weekly_poll_job sent poll=%s", poll.id)


async def _check_today_quorum() -> None:
    """Ежедневный джоб — если сегодняшний день набрал квоту, создать встречу и уведомить."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.services.invites import handle_time_finalized
    from app.services.weekly_poll import DAYS, active_weekly_poll, finalize_day

    async with AsyncSessionLocal() as db:
        poll = await active_weekly_poll(db)
        if poll is None:
            logger.info("quorum_check_job no_active_poll")
            return
        dow = datetime.now(ZoneInfo(get_settings().app_timezone)).weekday()
        result = await finalize_day(db, poll, dow)
        if result is None:
            return
        meeting, time_str = result
        await handle_time_finalized(
            db, meeting.id, DAYS[dow], time_str, scheduled_start=meeting.scheduled_start,
        )
        logger.info("quorum_check_job notified day=%s time=%s", DAYS[dow], time_str)


async def _close_today_poll() -> None:
    """Джоб в 14:00 — пометить сегодняшний день в расписании как «passed» (обновить карточку)."""
    from app.services.weekly_poll import active_weekly_poll, refresh_poll_card

    async with AsyncSessionLocal() as db:
        poll = await active_weekly_poll(db)
        if poll is None:
            logger.info("day_close_job no_active_poll")
            return
        await refresh_poll_card(db, poll)
        logger.info("day_close_job refreshed poll=%s", poll.id)


async def _send_day_confirmations(now: datetime | None = None) -> None:
    """Ежедневный вечерний джоб — подтверждение явки на завтра тем, кто проголосовал.

    now — опционально, чтобы вручную симулировать «сейчас вечер понедельника».
    """
    from datetime import timedelta
    from zoneinfo import ZoneInfo

    from app.services.chat_sender import find_user_dm_space, send_message as send_space_message
    from app.services.weekly_poll import (
        active_weekly_poll,
        build_confirmation_card,
        day_voter_profiles,
    )

    if now is None:
        now = datetime.now(ZoneInfo(get_settings().app_timezone))
    tomorrow_dow = (now + timedelta(days=1)).weekday()
    if tomorrow_dow == 0:  # понедельник следующей недели — не в текущем опросе
        return

    async with AsyncSessionLocal() as db:
        poll = await active_weekly_poll(db)
        if poll is None:
            return
        voters = await day_voter_profiles(db, poll.id, tomorrow_dow)
        card = build_confirmation_card(tomorrow_dow, get_settings().chat_app_audience)
        sent = 0
        for p in voters:
            dm = await asyncio.to_thread(find_user_dm_space, p.workspace_user_id or "")
            if not dm:
                continue
            try:
                await asyncio.to_thread(send_space_message, dm, cards_v2=card["cardsV2"])
                sent += 1
            except Exception:
                logger.exception("day_confirmation_send_failed profile=%s", p.id)
    logger.info("day_confirmations_sent day=%s count=%s", tomorrow_dow, sent)


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
            await asyncio.to_thread(send_message, ws, MessagePayload(text="Hi! Fill in a short form 🙌", card=_onboarding_card("friend")))
        if plan["mention"]:
            mentions = " ".join(f"<{m}>" for m in plan["mention"])
            await asyncio.to_thread(send_text, space_id, f"{mentions} — DM me to fill in the form 👋")


async def _run_inactivity_reminder() -> None:
    """Джоб: напомнить неактивным участникам о встречах."""
    from app.services.inactivity import remind_inactive

    async with AsyncSessionLocal() as db:
        sent = await remind_inactive(db)
        logger.info("inactivity_reminder_job sent=%s", sent)


async def _run_close_stale_games() -> None:
    """Джоб каждые 30 сек — закрыть просроченные фазы игр (Quiplash/«Кто я?»)."""
    from app.services.games.party_games import close_stale_games

    await close_stale_games()


async def _run_cleanup() -> None:
    """Ежедневный джоб очистки — старые опросы и внутренности сыгранных игр."""
    from app.services.cleanup import run_cleanup

    async with AsyncSessionLocal() as db:
        summary = await run_cleanup(db)
        await db.commit()
        logger.info("cleanup_job summary=%s", summary)


async def _run_fast_cycle(step_seconds: int) -> None:
    """Джоб fast_cycle: одиночный прогон полного цикла (каждый этап один раз)."""
    from app.services.fast_cycle import run_cycle

    await run_cycle(step_seconds)


async def init_scheduler() -> None:
    """Создать и запустить шедулер; время джобов — из config."""
    global scheduler
    if scheduler is not None:
        return
    from app.services.weekly_poll import DAY_CLOSE_HOUR, get_or_create_config

    async with AsyncSessionLocal() as db:
        run_h = int((await get_or_create_config(db, "poll_run_hour", 9)).value or 9)
        run_m = int((await get_or_create_config(db, "poll_run_minute", 0)).value or 0)
        check_h = int((await get_or_create_config(db, "quorum_check_hour", 10)).value or 10)
        confirm_h = int((await get_or_create_config(db, "confirm_hour", 18)).value or 18)
        weekly_day = str((await get_or_create_config(db, "weekly_poll_day", "sun")).value or "sun")
        weekly_hour = int((await get_or_create_config(db, "weekly_poll_hour", 11)).value or 11)
        rem_h = int((await get_or_create_config(db, "inactivity_reminder_hour", 11)).value or 11)

    scheduler = AsyncIOScheduler(timezone=get_settings().app_timezone)
    scheduler.add_job(
        _run_weekly_poll, "cron", day_of_week="mon", hour=run_h, minute=run_m,
        id="weekly-poll", replace_existing=True, misfire_grace_time=3600,
    )
    scheduler.add_job(
        _check_today_quorum, "cron", hour=check_h, minute=0,
        id="daily-quorum-check", replace_existing=True, misfire_grace_time=3600,
    )
    scheduler.add_job(
        _send_day_confirmations, "cron", hour=confirm_h, minute=0,
        id="day-confirmations", replace_existing=True, misfire_grace_time=3600,
    )
    scheduler.add_job(
        _close_today_poll, "cron", hour=DAY_CLOSE_HOUR, minute=0,
        id="day-close", replace_existing=True, misfire_grace_time=3600,
    )
    scheduler.add_job(
        _run_weekly_questions, "cron", day_of_week=weekly_day, hour=weekly_hour, minute=0,
        id="weekly-questions", replace_existing=True, misfire_grace_time=3600,
    )
    scheduler.add_job(
        _poll_new_members, "interval", minutes=10,
        id="onboarding-poll", replace_existing=True,
    )
    scheduler.add_job(
        _run_inactivity_reminder, "cron", hour=rem_h, minute=0,
        id="inactivity-reminder", replace_existing=True, misfire_grace_time=3600,
    )

    scheduler.add_job(
        _run_close_stale_games,
        "interval",
        seconds=30,
        id="close-stale-games",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=60,
    )

    scheduler.add_job(
        _run_cleanup,
        "cron",
        hour=4,
        minute=0,
        id="cleanup",
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


def unschedule_meeting_jobs(instance_id: int | str) -> None:
    """Снять джобы напоминания/check-in/карточки для встречи (при её отмене).

    Без этого запланированные джобы «выстрелят» позже по уже отменённой встрече
    и пошлют в группу вводящие в заблуждение сообщения («встреча через час»).
    """
    from app.cards.service import card_job_id
    from app.services.checkin import job_ids as checkin_job_ids
    from app.services.reminders import reminder_job_id

    if scheduler is None:
        return
    job_ids = [
        reminder_job_id(str(instance_id)),
        checkin_job_ids(str(instance_id))["open"],
        checkin_job_ids(str(instance_id))["close"],
        card_job_id(str(instance_id)),
    ]
    for jid in job_ids:
        try:
            scheduler.remove_job(jid)
        except Exception:
            logger.debug("unschedule_meeting_jobs no job %s", jid)


def schedule_fast_cycle(step_seconds: int) -> None:
    """Поставить одиночный date-джоб прогона цикла (при добавлении бота в группу)."""
    if scheduler is None:
        logger.warning("fast_cycle_no_scheduler")
        return
    scheduler.add_job(
        _run_fast_cycle, "date",
        run_date=datetime.now(timezone.utc) + timedelta(seconds=5),
        args=[step_seconds],
        id="fast-cycle",
        replace_existing=True,
        max_instances=3,
        coalesce=False,
    )
    logger.info("fast_cycle_scheduled step_seconds=%s", step_seconds)
