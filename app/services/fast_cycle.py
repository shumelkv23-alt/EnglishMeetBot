"""Одиночный прогон полного цикла бота (fast_cycle): этапы с паузами, реальная отправка.

В отличие от interval-джобов, каждый этап выполняется РОВНО ОДИН раз —
имитация разворачивания «дня» за один прогон, без повторов/спама.

Запускается из scheduler при config['fast_cycle']=true.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

# Пауза после нажатия «Finish voting» / кворума: напоминание → 10с → карточка.
POST_MEETING_DELAY_SECONDS = 10


async def run_cycle(step_seconds: int) -> None:
    """Прогнать один цикл: опрос → вопросы → голоса → кворум → напоминание → карточка → чек-ин."""
    from app.services.weekly_poll import (
        DAYS,
        active_weekly_poll,
        ensure_weekly_poll,
        finalize_day,
        get_or_create_config,
        send_weekly_poll_card,
    )

    tz = ZoneInfo(get_settings().app_timezone)
    today_dow = datetime.now(tz).weekday()

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

    # 3. Кворум — ждём, пока участники проголосуют (кворум из config['quorum_threshold']).
    # Кнопка «Finish voting» ставит config['finish_voting_requested'] — тогда проверка
    # кворума выполняется СРАЗУ, не дожидаясь следующей итерации цикла. Кворум всё
    # равно обязателен: без него встреча не создаётся.
    meeting_id = None
    deadline = datetime.now(timezone.utc) + timedelta(minutes=8)
    while meeting_id is None and datetime.now(timezone.utc) < deadline:
        async with AsyncSessionLocal() as db:
            poll = await active_weekly_poll(db)
            result = await finalize_day(db, poll, today_dow) if poll else None
            requested = poll is not None and bool(
                (await get_or_create_config(db, "finish_voting_requested", False)).value
            )
            if requested:
                # Флаг обработали — сбрасываем; если кворума не хватило, сообщаем в группу.
                cfg = await get_or_create_config(db, "finish_voting_requested", False)
                cfg.value = False
                await db.commit()
                if result is None:
                    from app.services.chat_sender import send_text

                    space_id = (await get_or_create_config(db, "space_id", "")).value or ""
                    if space_id:
                        await asyncio.to_thread(
                            send_text, space_id,
                            "Quorum not met yet — keep voting! 🗳️",
                        )
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
            await asyncio.sleep(5)  # ждём голоса участников / нажатие кнопки
    if meeting_id is None:
        logger.warning("fast_cycle step=кворум таймаут — кворум не набран")
        return
    await asyncio.sleep(POST_MEETING_DELAY_SECONDS)

    # 4. Напоминание (встреча на сегодня — напомнить в группу)
    from app.services.invites import _send_reminder

    await _send_reminder(str(meeting_id))
    logger.info("fast_cycle step=напоминание meeting=%s", meeting_id)
    await asyncio.sleep(POST_MEETING_DELAY_SECONDS)

    # 5. Карточка занятия (+ vocabulary внутри карточки)
    from app.cards.service import send_card

    await send_card(str(meeting_id))
    logger.info("fast_cycle step=карточка meeting=%s", meeting_id)
    await pause()

    # 6. Чек-ин — карточка в группу (участники отмечаются кнопкой сами)
    async with AsyncSessionLocal() as db:
        from app.services.checkin import build_checkin_card
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
        await db.rollback()

    logger.info("fast_cycle done")
