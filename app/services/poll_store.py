# app/services/poll_store.py
"""DB-слой ежедневного голосования «в тот же день»: связывает чистую логику
poll_logic/poll_card с базой и отправкой.

Здесь живёт ВСЁ, что требует БД/сети (сами poll_logic/poll_card остаются
чистыми). Вызывающие слоты — вебхук (save_attendance_response / save_time_vote /
record_checkin) и планировщик (create_daily_poll_and_broadcast / finalize_today /
send_daily_checkins).

Карта записи в БД — см. docstring app/services/poll_logic.py.
"""
import logging
from datetime import date, datetime, time as dtime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.timeutil import app_now, app_today
from app.models import (
    Attendance,
    Config,
    MeetingInstance,
    PollResponse,
    PollSlot,
    PollVote,
    Profile,
    WeeklyPoll,
)
from app.services import chat_sender
from app.services.broadcast import ensure_profile_dm
from app.services.poll_card import (
    build_attendance_card,
    build_checkin_card,
)
from app.services.poll_logic import (
    APP_TZ,
    DAILY_QUORUM_DEFAULT,
    DEFAULT_REMINDER_HOURS,
    MeetingPlan,
    MessagePlan,
    Slot,
    build_announcement_text,
    build_daily_slots,
    finalize_slots,
    plan_meeting_messages,
    time_label,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# config-таблица (ключ-значение, JSONB)
# ---------------------------------------------------------------------

async def config_value(db: AsyncSession, key: str, default):
    """Прочитать настройку из config; JSONB уже десериализован в Python-тип."""
    row = await db.execute(select(Config).where(Config.key == key))
    cfg = row.scalar_one_or_none()
    if cfg is None:
        return default
    return cfg.value


def _slot_key_for_start(start: datetime) -> str:
    """Стабильный ключ слота в таймзоне бота — тот же формат, что build_daily_slots()."""
    local = start.astimezone(APP_TZ)
    return f"{local.date().isoformat()}T{local.hour:02d}{local.minute:02d}"


# ---------------------------------------------------------------------
# Опрос дня (weekly_polls: week_start = дата дня)
# ---------------------------------------------------------------------

async def get_or_create_daily_poll(db: AsyncSession, day: date) -> WeeklyPoll | None:
    """Опрос на день `day`: создать с 3 слотами или вернуть существующий.

    Возвращает None, если сейчас уже позже deadline (13:00) — опоздали,
    опрос дня не создаём (иначе останется «висячий» активный опрос).
    """
    poll = (
        await db.execute(select(WeeklyPoll).where(WeeklyPoll.week_start == day))
    ).scalar_one_or_none()

    if poll is None:
        close_hour = int(await config_value(db, "daily_poll_close_hour", 13) or 13)
        deadline = datetime.combine(day, dtime(close_hour, 0), tzinfo=APP_TZ)
        if app_now() >= deadline:
            return None

        location = await config_value(db, "default_location", "")
        poll = WeeklyPoll(
            week_start=day,
            voting_deadline=deadline,
            status="active",
        )
        db.add(poll)
        await db.flush()  # нужен poll.id для слотов

        for s in build_daily_slots(day, location=str(location or "")):
            db.add(
                PollSlot(
                    poll_id=poll.id,
                    slot_start=s.start,
                    slot_end=s.end,
                    location=s.location,
                    priority=0,
                )
            )
        await db.commit()
        await db.refresh(poll)
        logger.info("daily_poll_created day=%s slots=3", str(day))
    return poll


def _poll_is_open(poll: WeeklyPoll | None) -> bool:
    """Опрос активен и ещё идёт голосование (до 13:00)."""
    return (
        poll is not None
        and poll.status == "active"
        and app_now() < poll.voting_deadline
    )


async def create_daily_poll_and_broadcast(db: AsyncSession) -> dict:
    """Утренний сценарий (пн-пт 9:00): опрос на сегодня + карточка «придёшь?» всем.

    Карточка идёт в DM каждому активному участнику. Возвращает сводку.
    """
    today = app_today()
    poll = await get_or_create_daily_poll(db, today)
    if poll is None:
        logger.warning("daily_poll_skipped_late day=%s", str(today))
        return {"day": str(today), "created": False, "sent": 0, "skipped": 0}

    profiles = (
        await db.execute(select(Profile).where(Profile.is_active.is_(True)))
    ).scalars().all()

    sent, skipped = 0, 0
    for profile in profiles:
        if not await ensure_profile_dm(db, profile):
            skipped += 1
            continue
        card = build_attendance_card(profile.user_name or "друг")["cardsV2"]
        try:
            chat_sender.send_card(profile.chat_space_id, card)
            sent += 1
        except Exception:
            logger.exception("attendance_card_send_failed profile_id=%s", profile.id)
            skipped += 1

    logger.info("daily_poll_broadcast day=%s sent=%s skipped=%s", str(today), sent, skipped)
    return {"day": str(today), "created": True, "sent": sent, "skipped": skipped}


# ---------------------------------------------------------------------
# Парсинг формы выбора времени (чистая функция — покрыта тестами)
# ---------------------------------------------------------------------

def parse_time_form(form_inputs: dict) -> str:
    """formInputs клика «Записаться» -> выбранный slot_key (или "").

    Понимает оба формата Google:
      классический {"time": {"stringInputs": {"value": ["2026-08-21T1500"]}}}
      add-on        {"time": {"": {"stringInputs": {"value": ["2026-08-21T1500"]}}}}
    """
    field = form_inputs.get("time")
    if not isinstance(field, dict):
        return ""
    payload = field.get("stringInputs") or field.get("")
    if isinstance(payload, dict) and "stringInputs" in payload:
        payload = payload["stringInputs"]
    if not isinstance(payload, dict):
        return ""
    raw = payload.get("value", [])
    for v in raw:
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


# ---------------------------------------------------------------------
# Приём ответа «да/нет» и выбора времени (вебхук)
# ---------------------------------------------------------------------

async def save_attendance_response(
    db: AsyncSession, profile: Profile, will_attend: bool
) -> tuple[str, bool]:
    """Сохранить ответ «придёшь сегодня?» и вернуть (текст, показать_карточку_времени).

    will_attend=True  -> (пустой текст, True) — вебхук покажет карточку выбора времени.
    will_attend=False -> (текст «ок, жаль», False).
    Ошибка/закрыто     -> (текст ошибки, False).
    """
    poll = await get_or_create_daily_poll(db, app_today())
    if not _poll_is_open(poll):
        return (
            "Голосование уже закрыто — встречи на сегодня определяются в 13:00. "
            "Приходи завтра! 🙌",
            False,
        )

    now = datetime.now(APP_TZ)
    response = (
        await db.execute(
            select(PollResponse).where(
                PollResponse.profile_id == profile.id,
                PollResponse.poll_id == poll.id,
            )
        )
    ).scalar_one_or_none()
    if response is None:
        response = PollResponse(
            profile_id=profile.id,
            poll_id=poll.id,
            status="responded",
            responded_at=now,
            will_attend=will_attend,
        )
        db.add(response)
    else:
        response.status = "responded"
        response.responded_at = now
        response.will_attend = will_attend
    await db.commit()

    logger.info(
        "attendance_response_saved profile_id=%s will_attend=%s",
        profile.id, will_attend,
    )
    if will_attend:
        return "", True
    return "Ок, жаль, что сегодня не сможешь 🙌 Заглянем завтра!", False


async def save_time_vote(db: AsyncSession, profile: Profile, slot_key: str) -> str:
    """Сохранить выбранное время (один слот) и вернуть текст подтверждения.

    ПЕРЕЗАПИСЬ голоса участника в этом опросе: старые poll_votes удаляются,
    вставляется одна строка за выбранный слот. Счётчик votes_count пересчитает
    триггер БД.
    """
    if not slot_key:
        return "Не вижу выбранное время 🤔 Отметь слот и нажми «Записаться» ещё раз."

    poll = await get_or_create_daily_poll(db, app_today())
    if not _poll_is_open(poll):
        return (
            "Голосование уже закрыто — встречи на сегодня определяются в 13:00. "
            "Приходи завтра! 🙌"
        )

    slot_rows = (
        await db.execute(select(PollSlot).where(PollSlot.poll_id == poll.id))
    ).scalars().all()
    target = next(
        (s for s in slot_rows if _slot_key_for_start(s.slot_start) == slot_key),
        None,
    )
    if target is None:
        return "Не нашёл такой слот времени — попробуй ещё раз 🤔"

    # upsert poll_responses (на случай, если участник сразу выбрал время без «да»)
    response = (
        await db.execute(
            select(PollResponse).where(
                PollResponse.profile_id == profile.id,
                PollResponse.poll_id == poll.id,
            )
        )
    ).scalar_one_or_none()
    now = datetime.now(APP_TZ)
    if response is None:
        response = PollResponse(
            profile_id=profile.id,
            poll_id=poll.id,
            status="responded",
            responded_at=now,
            will_attend=True,
        )
        db.add(response)
        await db.flush()
    else:
        response.status = "responded"
        response.responded_at = now
        response.will_attend = True

    # перезапись голоса участника в этом опросе (одна строка)
    old_slot_ids = [s.id for s in slot_rows]
    if old_slot_ids:
        await db.execute(
            delete(PollVote).where(
                PollVote.profile_id == profile.id,
                PollVote.poll_slot_id.in_(old_slot_ids),
            )
        )
    db.add(
        PollVote(
            poll_response_id=response.id,
            profile_id=profile.id,
            poll_slot_id=target.id,
            voted_at=now,
        )
    )
    await db.commit()

    label = time_label(
        Slot(
            slot_key=slot_key,
            day=target.slot_start.astimezone(APP_TZ).date(),
            start=target.slot_start,
            end=target.slot_end,
            location=target.location,
        )
    )
    logger.info("time_vote_saved profile_id=%s slot=%s", profile.id, slot_key)
    return (
        f"Записал(а) тебя на {label} ✅\n"
        "Если встреча соберётся, придёт анонс в группу и напоминание за час."
    )


# ---------------------------------------------------------------------
# Финализация (13:00): слоты с кворумом -> встречи (до 3 групп)
# ---------------------------------------------------------------------

async def _attendee_ids_for_slot(db: AsyncSession, slot_id: int) -> list[str]:
    """workspace_user_id всех, кто проголосовал за слот."""
    rows = (
        await db.execute(
            select(Profile.workspace_user_id)
            .join(PollVote, PollVote.profile_id == Profile.id)
            .where(PollVote.poll_slot_id == slot_id)
            .distinct()
        )
    ).scalars().all()
    return [r for r in rows if r]


async def finalize_today(db: AsyncSession, now: datetime) -> dict:
    """Финализация сегодняшнего опроса (13:00 по таймзоне бота).

    Каждый слот с голосами >= quorum -> отдельная встреча (до 3 в день).
    Анонс уходит в группу, напоминание за час планируется планировщиком.
    Кворума нет нигде -> тихо, никому не пишем (опрос просто закрывается).

    Возвращает {'meetings': [MeetingInstance], 'reminders': [MessagePlan]}.
    """
    today = now.date()
    poll = (
        await db.execute(
            select(WeeklyPoll).where(
                WeeklyPoll.week_start == today,
                WeeklyPoll.status == "active",
            )
        )
    ).scalar_one_or_none()
    if poll is None:
        return {"meetings": [], "reminders": []}

    quorum = int(await config_value(db, "quorum_threshold", DAILY_QUORUM_DEFAULT) or DAILY_QUORUM_DEFAULT)
    reminder_hours = int(await config_value(db, "meeting_reminder_hours", DEFAULT_REMINDER_HOURS) or DEFAULT_REMINDER_HOURS)

    slot_rows = (
        await db.execute(select(PollSlot).where(PollSlot.poll_id == poll.id))
    ).scalars().all()

    slots: list[Slot] = []
    row_by_key: dict[str, PollSlot] = {}
    for row in slot_rows:
        key = _slot_key_for_start(row.slot_start)
        slots.append(
            Slot(
                slot_key=key,
                day=row.slot_start.astimezone(APP_TZ).date(),
                start=row.slot_start,
                end=row.slot_end,
                votes=row.votes_count,
                location=row.location,
            )
        )
        row_by_key[key] = row

    winners = finalize_slots(slots, quorum)

    meetings: list[MeetingInstance] = []
    reminders: list[MessagePlan] = []
    for plan in winners:
        slot_row = row_by_key[plan.slot.slot_key]
        meeting = MeetingInstance(
            poll_id=poll.id,
            selected_slot_id=slot_row.id,
            scheduled_start=slot_row.slot_start,
            scheduled_end=slot_row.slot_end,
            location=slot_row.location,
            status="scheduled",
        )
        db.add(meeting)
        await db.flush()  # нужен meeting.id для активности/получателей
        await db.refresh(meeting)

        # Активность/тема — логика Кирилла (app/services/activity.py).
        from app.services.activity import pick_activity

        activity = await pick_activity(db, meeting) or ""

        recipient_ids = await _attendee_ids_for_slot(db, slot_row.id)
        announcement = build_announcement_text(plan, activity)
        send_to_group(announcement)

        for rp in plan_meeting_messages(plan, recipient_ids, reminder_hours):
            reminders.append(rp)

        logger.info(
            "meeting_fixed meeting_id=%s slot=%s voters=%s recipients=%s",
            meeting.id, plan.slot.slot_key, plan.slot.votes, len(recipient_ids),
        )
        meetings.append(meeting)

    poll.status = "closed"
    poll.closed_at = now
    await db.commit()

    logger.info(
        "daily_finalize done day=%s meetings=%s",
        str(today), len(meetings),
    )
    return {"meetings": meetings, "reminders": reminders}


# ---------------------------------------------------------------------
# Чек-ин (18:00, конец дня)
# ---------------------------------------------------------------------

async def send_daily_checkins(db: AsyncSession, now: datetime) -> int:
    """Конец дня (18:00): отметить встречи completed и разослать чек-ин участникам.

    Чек-ин уходит в DM каждому, кто проголосовал за слот состоявшейся встречи.
    Возвращает число отправленных чек-инов.
    """
    today = now.date()
    meetings = (
        await db.execute(
            select(MeetingInstance).where(
                MeetingInstance.poll_id.in_(
                    select(WeeklyPoll.id).where(WeeklyPoll.week_start == today)
                ),
                MeetingInstance.status == "scheduled",
            )
        )
    ).scalars().all()

    sent = 0
    for meeting in meetings:
        attendee_ids = await _attendee_ids_for_slot(db, meeting.selected_slot_id)
        label = time_label(
            Slot(
                slot_key=meeting.id,
                day=meeting.scheduled_start.astimezone(APP_TZ).date(),
                start=meeting.scheduled_start,
                end=meeting.scheduled_end,
                location=meeting.location,
            )
        )
        for user_id in attendee_ids:
            space = await _dm_space_for_user(user_id)
            if not space:
                continue
            try:
                chat_sender.send_card(
                    space, build_checkin_card("друг", label)["cardsV2"]
                )
                sent += 1
            except Exception:
                logger.exception("checkin_send_failed user=%s", user_id)

        meeting.status = "completed"
        meeting.completed_at = now

    if meetings:
        await db.commit()
    logger.info("daily_checkins done day=%s sent=%s meetings=%s", str(today), sent, len(meetings))
    return sent


async def record_checkin(db: AsyncSession, profile: Profile, present: bool) -> str:
    """Сохранить чек-ин «был/нет» и вернуть текст подтверждения.

    Записывает attendance (source='self_checkin', status present/absent).
    Баллы (leaderboard_ledger) сознательно НЕ трогаем — это отдельный этап.
    """
    today = app_today()
    poll = (
        await db.execute(select(WeeklyPoll).where(WeeklyPoll.week_start == today))
    ).scalar_one_or_none()
    if poll is None:
        return "Не нашёл сегодняшнюю встречу — чек-ин не сохранён 🤔"

    meeting = None
    meetings = (
        await db.execute(select(MeetingInstance).where(MeetingInstance.poll_id == poll.id))
    ).scalars().all()
    for m in meetings:
        vote = (
            await db.execute(
                select(PollVote).where(
                    PollVote.poll_slot_id == m.selected_slot_id,
                    PollVote.profile_id == profile.id,
                )
            )
        ).scalar_one_or_none()
        if vote is not None:
            meeting = m
            break

    if meeting is None:
        return "Ты не числился(лась) участником сегодняшней встречи — пропускаю."

    now = datetime.now(APP_TZ)
    attendance = (
        await db.execute(
            select(Attendance).where(
                Attendance.profile_id == profile.id,
                Attendance.meeting_instance_id == meeting.id,
            )
        )
    ).scalar_one_or_none()
    status = "present" if present else "absent"
    if attendance is None:
        attendance = Attendance(
            profile_id=profile.id,
            meeting_instance_id=meeting.id,
            source="self_checkin",
            status=status,
            checkin_attempted_at=now,
            is_within_window=True,
        )
        db.add(attendance)
    else:
        attendance.status = status
        attendance.checkin_attempted_at = now
        attendance.is_within_window = True
    await db.commit()

    logger.info(
        "checkin_recorded profile_id=%s meeting_id=%s status=%s",
        profile.id, meeting.id, status,
    )
    if present:
        return "Отлично, отметили, что ты был(а) ✅ Спасибо!"
    return "Жаль, что не получилось 🙁 Отметили. До завтра!"


# ---------------------------------------------------------------------
# Отправка в DM / группу (общие помощники)
# ---------------------------------------------------------------------

async def _dm_space_for_user(user_id: str) -> str:
    """chat_space_id профиля; при отсутствии — поиск через Chat API."""
    async with AsyncSessionLocal() as session:
        profile = (
            await session.execute(
                select(Profile).where(Profile.workspace_user_id == user_id)
            )
        ).scalar_one_or_none()
        if profile is None:
            return ""
        if not await ensure_profile_dm(session, profile):
            return ""
        return profile.chat_space_id or ""


async def _deliver_to_users(recipient_ids: tuple[str, ...], text: str) -> int:
    """Доставить текст в DM каждому получателю. Возвращает число доставок."""
    delivered = 0
    for user_id in recipient_ids:
        try:
            space = await _dm_space_for_user(user_id)
        except Exception:
            logger.exception("dm_resolve_failed user=%s", user_id)
            continue
        if not space:
            logger.warning("recipient_no_dm user=%s", user_id)
            continue
        try:
            chat_sender.send_text(space, text)
            delivered += 1
        except Exception:
            logger.exception("dm_send_failed user=%s", user_id)
    return delivered


def send_to_group(text: str) -> bool:
    """Отправить текст в общую группу (settings.chat_group_space).

    False — группа не настроена (пустой chat_group_space) или отправка не удалась.
    """
    space = get_settings().chat_group_space
    if not space:
        return False
    try:
        chat_sender.send_text(space, text)
        return True
    except Exception:
        logger.exception("group_send_failed")
        return False
