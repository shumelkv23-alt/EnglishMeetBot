"""Одиночный прогон полного цикла бота (fast_cycle): этапы с паузами, реальная отправка.

В отличие от interval-джобов, каждый этап выполняется РОВНО ОДИН раз —
имитация разворачивания «дня» за один прогон, без повторов/спама.

Запускается из scheduler при config['fast_cycle']=true.
"""
import asyncio
import logging
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import Attendance, MeetingInstance

logger = logging.getLogger(__name__)

# Один тестовый аккаунт для авто-голоса: реальные участники (3 чел.) голосуют сами,
# бот накручивает один голос, чтобы кворум 4 набрался.
TEST_USER = "users/test_cycle_4"


async def run_cycle(step_seconds: int) -> None:
    """Прогнать один цикл: опрос → вопросы → голоса → кворум → напоминание → карточка → чек-ин."""
    from app.services.onboarding import get_or_create_profile
    from app.services.weekly_poll import (
        DAYS,
        active_weekly_poll,
        ensure_weekly_poll,
        finalize_day,
        get_or_create_config,
        send_weekly_poll_card,
        submit_poll,
    )

    tz = ZoneInfo(get_settings().app_timezone)
    today_dow = datetime.now(tz).weekday()
    voters = [TEST_USER]

    async def pause() -> None:
        if step_seconds > 0:
            await asyncio.sleep(step_seconds)

    # 1. Опрос недели
    async with AsyncSessionLocal() as db:
        poll = await ensure_weekly_poll(db)
        await send_weekly_poll_card(db, poll)
        logger.info("fast_cycle step=опрос poll=%s", poll.id)
    await pause()

    # 2. Вопросы недели
    async with AsyncSessionLocal() as db:
        from app.services.weekly_questions import send_weekly_questions

        sent_q = await send_weekly_questions(db)
        logger.info("fast_cycle step=вопросы sent=%s", sent_q)
    await pause()

    # 3. Голосование (бот накручивает 1 голос за сегодня, слот 15:00)
    async with AsyncSessionLocal() as db:
        form = {
            "day": {"stringInputs": {"value": [str(today_dow)]}},
            "time": {"stringInputs": {"value": ["15:00"]}},
        }
        for uid in voters:
            profile = await get_or_create_profile(db, workspace_user_id=uid)
            res = await submit_poll(db, profile, form)
            if not res.get("ok"):
                logger.warning("fast_cycle vote_failed user=%s res=%s", uid, res)
        logger.info("fast_cycle step=голосование day=%s", today_dow)
    await pause()

    # 4. Кворум — ждём, пока 3 реальных проголосуют (бот уже накрутил 1 голос).
    meeting_id = None
    deadline = datetime.now(timezone.utc) + timedelta(minutes=8)
    while meeting_id is None and datetime.now(timezone.utc) < deadline:
        async with AsyncSessionLocal() as db:
            poll = await active_weekly_poll(db)
            result = await finalize_day(db, poll, today_dow) if poll else None
            if result is not None:
                meeting, time_str = result
                meeting_id = meeting.id
                # Пост приглашения в группу БЕЗ scheduler-джобов — иначе те навесят
                # напоминание/чек-ин/карточку позже по реальному времени, и всё смешается.
                from app.services.chat_sender import send_text
                from app.services.invites import build_invite_text

                space_id = (await get_or_create_config(db, "space_id", "")).value or ""
                if space_id:
                    await asyncio.to_thread(
                        send_text, space_id, f"🗓️ {build_invite_text(DAYS[today_dow], time_str, None)}"
                    )
                logger.info("fast_cycle step=кворум встреча_создана id=%s", meeting_id)
            await db.rollback()
        if meeting_id is None:
            await asyncio.sleep(15)  # ждём голоса участников
    if meeting_id is None:
        logger.warning("fast_cycle step=кворум таймаут — кворум не набран")
        return
    await pause()

    # 5. Напоминание (встреча на сегодня — напомнить в группу)
    if meeting_id:
        from app.services.invites import _send_reminder

        await _send_reminder(str(meeting_id))
        logger.info("fast_cycle step=напоминание meeting=%s", meeting_id)
    await pause()

    # 6. Карточка занятия
    if meeting_id:
        from app.cards.service import send_card

        await send_card(str(meeting_id))
        logger.info("fast_cycle step=карточка meeting=%s", meeting_id)
    await pause()

    # 7. Чек-ин — карточка в группу + отметки участников
    async with AsyncSessionLocal() as db:
        from app.services.checkin import build_checkin_card, submit_checkin
        from app.services.chat_sender import send_message as send_space_message

        space_id = (await get_or_create_config(db, "space_id", "")).value or ""
        if space_id and meeting_id:
            card = build_checkin_card(str(meeting_id), action_url=get_settings().chat_app_audience)
            await asyncio.to_thread(
                send_space_message,
                space_id,
                text="The meetup is starting — check in! ✅",
                cards_v2=card["cardsV2"],
            )
        checked = 0
        for uid in voters:
            profile = await get_or_create_profile(db, workspace_user_id=uid)
            r = await submit_checkin(db, profile, meeting_id) if meeting_id else {"ok": False}
            if r.get("ok"):
                checked += 1
        n_att = (
            await db.execute(
                select(func.count())
                .select_from(Attendance)
                .where(Attendance.meeting_instance_id == meeting_id)
            )
        ).scalar_one() if meeting_id else 0
        logger.info("fast_cycle step=чек-ин checked=%s attendance=%s", checked, n_att)
        await db.rollback()

    logger.info("fast_cycle done")
