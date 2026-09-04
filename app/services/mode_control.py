# app/services/mode_control.py
"""Переключение режимов бота (demo vs orig) по кнопке при добавлении в группу.

Собирает то, что раньше делали скрипты scripts/prep_demo.py и scripts/reset_demo.py,
в переиспользуемые функции, чтобы карточка «demo / orig» вызывала их напрямую.

- demo: fast_cycle=True, quorum=4, 3 засеянных голоса за сегодня → запуск быстрого цикла.
- orig: fast_cycle=False, quorum=3, демо-данные удалены → обычный cron-режим.
"""
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select, update

from app.config import get_settings
from app.models import MeetingInstance, PollResponse, PollSlot, PollVote, Profile
from app.services.onboarding import get_or_create_profile
from app.services.weekly_poll import (
    active_weekly_poll,
    ensure_weekly_poll,
    get_or_create_config,
    submit_poll,
)

logger = logging.getLogger(__name__)

DEMO_USERS = ("users/demo_1", "users/demo_2", "users/demo_3")
DEMO_TIME = "15:00"


async def _clear_poll_votes(db, poll) -> None:
    """Чистый старт опроса: убрать ВСЕ голоса/ответы и отменить встречи.

    Нужно обоим режимам: при повторном прогоне (или переключении demo↔orig)
    в голосовании не должны висеть голоса реальных пользователей с прошлых прогонов.
    """
    slot_ids = select(PollSlot.id).where(PollSlot.poll_id == poll.id)
    await db.execute(delete(PollVote).where(PollVote.poll_slot_id.in_(slot_ids)))
    await db.execute(delete(PollResponse).where(PollResponse.poll_id == poll.id))

    # Отменяем встречи и снимаем их запланированные джобы (напоминание/check-in/карточка),
    # иначе те «выстрелят» позже по уже отменённой встрече и введут людей в заблуждение.
    meeting_ids = (
        await db.execute(select(MeetingInstance.id).where(MeetingInstance.poll_id == poll.id))
    ).scalars().all()
    await db.execute(
        update(MeetingInstance)
        .where(MeetingInstance.poll_id == poll.id)
        .values(status="cancelled")
    )
    from app.scheduler import unschedule_meeting_jobs

    for mid in meeting_ids:
        unschedule_meeting_jobs(mid)


async def enable_demo_mode(db, space_id: str = "", step_seconds: int = 60, demo_day: int | None = None) -> None:
    """Включить демо: fast_cycle=True, quorum=4, очистить прежние голоса и засеять 3 демо-голоса.

    demo_day — день недели (0=Пн..6=Вс) демо-встречи; None → сегодня (по таймзоне приложения).
    """
    if demo_day is None:
        demo_day = datetime.now(ZoneInfo(get_settings().app_timezone)).weekday()

    fc = await get_or_create_config(db, "fast_cycle", False)
    fc.value = True
    qt = await get_or_create_config(db, "quorum_threshold", 3)
    qt.value = 4
    st = await get_or_create_config(db, "fast_cycle_seconds", 60)
    st.value = step_seconds
    # Сброс залипшего флага «Finish voting»: иначе при первом же прогоне цикла
    # бот сразу напишет «Quorum not met», не дождавшись голосов.
    fv = await get_or_create_config(db, "finish_voting_requested", False)
    fv.value = False
    dd = await get_or_create_config(db, "demo_day", demo_day)
    dd.value = demo_day
    if space_id:
        scfg = await get_or_create_config(db, "space_id", "")
        scfg.value = space_id
    # коммитим ДО голосования: submit_poll читает fast_cycle, чтобы не отклонить
    # голос по времени (сегодня после 13:00 в демо разрешено).
    await db.commit()

    poll = await ensure_weekly_poll(db)
    await _clear_poll_votes(db, poll)

    form = {
        "day": {"stringInputs": {"value": [str(demo_day)]}},
        "time": {"stringInputs": {"value": [DEMO_TIME]}},
    }
    for uid in DEMO_USERS:
        profile = await get_or_create_profile(db, workspace_user_id=uid)
        await submit_poll(db, profile, form)
    await db.commit()
    logger.info("mode_control demo_enabled day=%s time=%s", demo_day, DEMO_TIME)


async def enable_normal_mode(db) -> None:
    """Вернуть обычный режим: fast_cycle=False, quorum=3, чистый старт опроса."""
    for key, val in (("fast_cycle", False), ("finish_voting_requested", False)):
        cfg = await get_or_create_config(db, key, val)
        cfg.value = val
    qt = await get_or_create_config(db, "quorum_threshold", 3)
    qt.value = 3

    # Чистый старт: убрать все голоса/ответы текущего опроса и отменить встречи
    # (иначе при переключении в обычный режим остаются голоса с прошлых прогонов).
    poll = await active_weekly_poll(db)
    if poll is not None:
        await _clear_poll_votes(db, poll)

    # Демо-профили удаляем целиком (их голоса/ответы уже убраны в _clear_poll_votes).
    demo_ids = (
        await db.execute(
            select(Profile.id).where(Profile.workspace_user_id.like("users/demo_%"))
        )
    ).scalars().all()
    if demo_ids:
        await db.execute(delete(Profile).where(Profile.id.in_(demo_ids)))

    await db.commit()
    logger.info("mode_control normal_enabled")
