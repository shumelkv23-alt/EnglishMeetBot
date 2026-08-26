"""Недельный опрос: карточка «день недели + время», сабмит, проверка квоты дня.

Один опрос на неделю (создаётся в понедельник): каждый участник голосует за
ОДИН слот (день + время), счётчики видны всем. Ежедневный джоб проверяет,
набрал ли сегодняшний день квоту — если да, создаёт встречу и шлёт уведомление.

Чистые функции в начале (тестируются юнитами), БД-функции ниже.
"""
import asyncio
import json
import logging
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Config, DailyPoll, MeetingInstance, PollResponse, PollSlot, PollVote, Profile
from app.services.form_parsing import parse_form_inputs

logger = logging.getLogger(__name__)

# Дни недели по индексу (0=Пн .. 6=Вс), совпадает с datetime.weekday().
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DAY_FULL = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

ALLOWED_SUBMIT_TIMES = frozenset({"15:00", "16:00", "17:00"})


def parse_day(raw: str) -> int:
    """'Mon' / '0' → 0 (Пн); невалидное → -1."""
    if isinstance(raw, str):
        s = raw.strip()
        if s.isdigit():
            d = int(s)
            return d if 0 <= d <= 6 else -1
        for i, name in enumerate(DAYS):
            if s.lower() == name.lower():
                return i
    return -1


def _normalize_submit(form_inputs: dict) -> tuple[int, str]:
    """(day_of_week, time) из formInputs; day по ключу "day", time по "time"."""
    vals = parse_form_inputs(form_inputs)
    day_raw = (vals.get("day") or [""])[0]
    time_raw = (vals.get("time") or [""])[0]
    return parse_day(day_raw), time_raw


def _is_valid_submit_time(choice: str) -> bool:
    """Допустимое значение времени (слот из ALLOWED_SUBMIT_TIMES)."""
    return choice in ALLOWED_SUBMIT_TIMES


def build_weekly_poll_card(
    days: list[int], times: list[str], action_url: str,
    counts: dict[tuple[int, str], int] | None = None, today_dow: int | None = None,
) -> dict:
    """Карточка недельного опроса: по секции на день, кнопки времени со счётчиками.

    counts — {(day_of_week, "HH:MM"): N}; None → все нули.
    today_dow — индекс сегодняшнего дня (по таймзоне приложения); дни раньше — без кнопок.
    """
    counts = counts or {}
    if today_dow is None:
        today_dow = datetime.now(ZoneInfo(get_settings().app_timezone)).weekday()
    sections = []
    for day in days:
        day_name = DAYS[day]
        total = sum(counts.get((day, t), 0) for t in times)
        if day < today_dow:
            sections.append({
                "header": f"{day_name} · passed",
                "widgets": [{"textParagraph": {"text": "This day has passed"}}],
            })
            continue
        buttons = []
        for t in times:
            c = counts.get((day, t), 0)
            buttons.append({
                "text": f"{t} ({c})",
                "onClick": {"action": {
                    "function": action_url or "submit_daily_poll",
                    "parameters": [
                        {"key": "method", "value": "submit_daily_poll"},
                        {"key": "day", "value": str(day)},
                        {"key": "time", "value": t},
                    ],
                }},
            })
        sections.append({
            "header": f"{day_name} · {total} voted",
            "widgets": [{"buttonList": {"buttons": buttons}}],
        })
    return {
        "cardsV2": [{
            "cardId": "weeklyPoll",
            "card": {
                "header": {"title": "When can you meet this week? 🗓️",
                           "subtitle": "Pick ONE day and time"},
                "sections": sections,
            },
        }]
    }


def build_confirmation_card(day_of_week: int, action_url: str) -> dict:
    """Карточка подтверждения явки в личке: «Will you come on X?» с Yes/No."""
    day_name = DAY_FULL[day_of_week]
    return {
        "cardsV2": [{
            "cardId": "attendanceConfirm",
            "card": {
                "header": {"title": f"Will you come on {day_name}?", "subtitle": "Meetup confirmation"},
                "sections": [{"widgets": [{"buttonList": {"buttons": [
                    {
                        "text": "Yes ✅",
                        "onClick": {"action": {
                            "function": action_url,
                            "parameters": [
                                {"key": "method", "value": "confirm_attendance"},
                                {"key": "day", "value": str(day_of_week)},
                                {"key": "answer", "value": "yes"},
                            ],
                        }},
                    },
                    {
                        "text": "No ❌",
                        "onClick": {"action": {
                            "function": action_url,
                            "parameters": [
                                {"key": "method", "value": "confirm_attendance"},
                                {"key": "day", "value": str(day_of_week)},
                                {"key": "answer", "value": "no"},
                            ],
                        }},
                    },
                ]}}]}],
            },
        }]
    }


# --- БД-часть (интеграционная) ---


async def get_or_create_config(db: AsyncSession, key: str, fallback_value) -> Config:
    cfg = (await db.execute(select(Config).where(Config.key == key))).scalar_one_or_none()
    if cfg is None:
        cfg = Config(key=key, value=fallback_value)
        db.add(cfg)
        await db.commit()
        await db.refresh(cfg)
    return cfg


def week_monday(day: date | None = None) -> date:
    """Понедельник текущей недели (в таймзоне приложения)."""
    d = day or datetime.now(ZoneInfo(get_settings().app_timezone)).date()
    return d - timedelta(days=d.weekday())


def slot_datetime(time_str: str) -> datetime:
    """Слот-время как datetime: часы/минуты на фиксированной дате-переносчике."""
    h, m = time_str.split(":")
    return datetime(2000, 1, 1, int(h), int(m), tzinfo=timezone.utc)


async def active_weekly_poll(db: AsyncSession) -> DailyPoll | None:
    """Активный опрос текущей недели (poll_date = понедельник, status='active')."""
    return (
        await db.execute(
            select(DailyPoll).where(
                DailyPoll.poll_date == week_monday(),
                DailyPoll.status == "active",
            )
        )
    ).scalar_one_or_none()


async def ensure_weekly_poll(db: AsyncSession) -> DailyPoll:
    """Активный опрос недели; если нет — создать опрос и слоты 7 дней × время."""
    poll = await active_weekly_poll(db)
    if poll is not None:
        return poll

    raw_slots = (await get_or_create_config(db, "daily_slots", ["15:00", "16:00", "17:00"])).value
    if isinstance(raw_slots, str):
        raw_slots = json.loads(raw_slots)
    times = [t for t in raw_slots if isinstance(t, str) and _is_valid_submit_time(t)]

    monday = week_monday()
    sunday = monday + timedelta(days=6)
    poll = DailyPoll(
        poll_date=monday,
        voting_deadline=datetime(sunday.year, sunday.month, sunday.day, 23, 59, tzinfo=ZoneInfo(get_settings().app_timezone)),
        status="active",
    )
    db.add(poll)
    await db.flush()
    for dow in range(7):
        for t in times:
            st = slot_datetime(t)
            db.add(PollSlot(
                poll_id=poll.id,
                day_of_week=dow,
                slot_start=st,
                slot_end=st + timedelta(minutes=60),
                location="Online (Meet)",
            ))
    await db.commit()
    logger.info("weekly_poll_created id=%s week=%s times=%s", poll.id, monday, times)
    return poll


async def submit_poll(db: AsyncSession, profile: Profile, form_inputs: dict) -> dict:
    """Сабмит недельного опроса: один слот (день+время) на человека."""
    poll = await active_weekly_poll(db)
    if poll is None:
        return {"ok": False, "reason": "no_poll"}
    deadline = poll.voting_deadline
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    if deadline < datetime.now(timezone.utc):
        return {"ok": False, "reason": "closed"}

    day, choice = _normalize_submit(form_inputs)
    today_dow = datetime.now(ZoneInfo(get_settings().app_timezone)).weekday()
    if day < today_dow:
        return {"ok": False, "reason": "past_day"}
    if day < 0 or not _is_valid_submit_time(choice):
        return {"ok": False, "reason": "empty"}

    response = (
        await db.execute(select(PollResponse).where(
            PollResponse.profile_id == profile.id, PollResponse.poll_id == poll.id))
    ).scalar_one_or_none()
    if response is None:
        response = PollResponse(profile_id=profile.id, poll_id=poll.id)
        db.add(response)
    await db.flush()  # response.id заполнен до вставки PollVote

    # при голосовании за день снимаем пометку «отказался» (если была)
    declined = dict(response.declined_days or {})
    if str(day) in declined:
        declined.pop(str(day))
        response.declined_days = declined

    # один слот на день: убрать только старые голоса за этот же день (другие дни сохраняем)
    await db.execute(delete(PollVote).where(
        PollVote.profile_id == profile.id,
        PollVote.poll_slot_id.in_(
            select(PollSlot.id).where(PollSlot.poll_id == poll.id, PollSlot.day_of_week == day)
        ),
    ))

    slot = (
        await db.execute(select(PollSlot).where(
            PollSlot.poll_id == poll.id,
            PollSlot.day_of_week == day,
            PollSlot.slot_start == slot_datetime(choice),
        ))
    ).scalar_one_or_none()
    if slot is None:
        await db.rollback()
        return {"ok": False, "reason": "empty"}

    db.add(PollVote(profile_id=profile.id, poll_slot_id=slot.id, poll_response_id=response.id))
    response.status = "responded"
    response.responded_at = datetime.now(timezone.utc)

    from app.services.inactivity import touch_activity

    touch_activity(profile, datetime.now(timezone.utc))
    await db.commit()
    return {"ok": True, "reason": "saved"}


async def poll_counts(db: AsyncSession, poll_id: int) -> tuple[list[int], list[str], dict[tuple[int, str], int]]:
    """(дни, времена, {(день, время): голоса}) для недельного опроса."""
    slots = (
        await db.execute(
            select(PollSlot)
            .where(PollSlot.poll_id == poll_id)
            .order_by(PollSlot.day_of_week, PollSlot.slot_start)
            .execution_options(populate_existing=True)  # свежие votes_count (триггер меняет их в обход сессии)
        )
    ).scalars().all()
    days = sorted({s.day_of_week for s in slots})
    times = sorted({s.slot_start.strftime("%H:%M") for s in slots})
    counts = {
        (s.day_of_week, s.slot_start.strftime("%H:%M")): (s.votes_count or 0)
        for s in slots
    }
    return days, times, counts


async def send_weekly_poll_card(db: AsyncSession, poll: DailyPoll) -> None:
    """Отправить карточку опроса в группу (или обновить существующую), запомнить message_name."""
    space_id = (await get_or_create_config(db, "space_id", "")).value or ""
    if not space_id:
        return
    days, times, counts = await poll_counts(db, poll.id)
    card = build_weekly_poll_card(days, times, get_settings().chat_app_audience, counts)
    from app.services.chat_sender import patch_message, send_message as send_space_message

    # уже есть карточка — обновляем на месте, чтобы не плодить дубликаты
    if poll.card_message_name:
        try:
            await asyncio.to_thread(patch_message, poll.card_message_name, cards_v2=card["cardsV2"])
            return
        except Exception:
            logger.exception("poll_card_patch_failed poll=%s", poll.id)

    resp = send_space_message(
        space_id, text="When can you meet this week? 🗓️", cards_v2=card["cardsV2"],
    )
    poll.card_message_name = resp.get("name", "")
    await db.commit()


async def refresh_poll_card(db: AsyncSession, poll: DailyPoll) -> None:
    """Обновить карточку опроса в группе актуальными счётчиками (messages.patch)."""
    if not poll.card_message_name:
        return
    days, times, counts = await poll_counts(db, poll.id)
    card = build_weekly_poll_card(days, times, get_settings().chat_app_audience, counts)
    from app.services.chat_sender import patch_message

    try:
        await asyncio.to_thread(patch_message, poll.card_message_name, cards_v2=card["cardsV2"])
    except Exception:
        logger.exception("poll_card_refresh_failed poll=%s", poll.id)


async def finalize_day(db: AsyncSession, poll: DailyPoll, day_of_week: int) -> tuple[MeetingInstance, str] | None:
    """Подвести день: если набрана квота и встречи ещё нет — создать и вернуть (встреча, время).

    Возвращает None, если квота не набрана или встреча на этот день уже создана.
    """
    quorum = int((await get_or_create_config(db, "quorum_threshold", 4)).value or 4)
    slots = (
        await db.execute(
            select(PollSlot).where(PollSlot.poll_id == poll.id, PollSlot.day_of_week == day_of_week)
        )
    ).scalars().all()
    if not slots:
        return None
    if sum(s.votes_count or 0 for s in slots) < quorum:
        return None

    meeting_date = poll.poll_date + timedelta(days=day_of_week)
    day_start = datetime.combine(meeting_date, time.min, tzinfo=timezone.utc)
    existing = (
        await db.execute(
            select(MeetingInstance).where(
                MeetingInstance.poll_id == poll.id,
                MeetingInstance.scheduled_start >= day_start,
                MeetingInstance.scheduled_start < day_start + timedelta(days=1),
            )
        )
    ).scalars().first()
    if existing is not None:
        return None

    best = max(slots, key=lambda s: s.votes_count or 0)
    duration = int((await get_or_create_config(db, "meeting_duration_minutes", 60)).value or 60)
    slot_start = best.slot_start
    if slot_start.tzinfo is None:
        slot_start = slot_start.replace(tzinfo=timezone.utc)
    start = datetime.combine(meeting_date, slot_start.time(), tzinfo=timezone.utc)
    meeting = MeetingInstance(
        poll_id=poll.id,
        selected_slot_id=best.id,
        scheduled_start=start,
        scheduled_end=start + timedelta(minutes=duration),
        location="Online (Meet)",
        status="scheduled",
    )
    db.add(meeting)
    await db.commit()
    await db.refresh(meeting)
    time_str = slot_start.strftime("%H:%M")
    logger.info("day_quorum_reached poll=%s day=%s time=%s", poll.id, day_of_week, time_str)
    return meeting, time_str


async def decline_day(db: AsyncSession, profile: Profile, day_of_week: int) -> bool:
    """Отказаться от дня: убрать голос и запомнить время (для возможного возврата)."""
    poll = await active_weekly_poll(db)
    if poll is None:
        return False
    slot = (await db.execute(
        select(PollSlot)
        .join(PollVote, PollVote.poll_slot_id == PollSlot.id)
        .where(PollVote.profile_id == profile.id, PollSlot.poll_id == poll.id, PollSlot.day_of_week == day_of_week)
    )).scalars().first()
    if slot is None:
        return False
    time_str = slot.slot_start.strftime("%H:%M")

    await db.execute(delete(PollVote).where(
        PollVote.profile_id == profile.id,
        PollVote.poll_slot_id.in_(
            select(PollSlot.id).where(PollSlot.poll_id == poll.id, PollSlot.day_of_week == day_of_week)
        ),
    ))

    response = (await db.execute(select(PollResponse).where(
        PollResponse.profile_id == profile.id, PollResponse.poll_id == poll.id
    ))).scalar_one_or_none()
    if response is None:
        response = PollResponse(profile_id=profile.id, poll_id=poll.id, status="responded")
        db.add(response)
        await db.flush()
    declined = dict(response.declined_days or {})
    declined[str(day_of_week)] = time_str
    response.declined_days = declined
    await db.commit()
    await refresh_poll_card(db, poll)
    return True


async def restore_day(db: AsyncSession, profile: Profile, day_of_week: int) -> bool:
    """Вернуть голос за день, если ранее от него отказался. True, если голос восстановлен."""
    poll = await active_weekly_poll(db)
    if poll is None:
        return False
    response = (await db.execute(select(PollResponse).where(
        PollResponse.profile_id == profile.id, PollResponse.poll_id == poll.id
    ))).scalar_one_or_none()
    if response is None:
        return False
    declined = dict(response.declined_days or {})
    time_str = declined.pop(str(day_of_week), None)
    if time_str is None:
        return False
    slot = (await db.execute(select(PollSlot).where(
        PollSlot.poll_id == poll.id,
        PollSlot.day_of_week == day_of_week,
        PollSlot.slot_start == slot_datetime(time_str),
    ))).scalar_one_or_none()
    if slot is None:
        response.declined_days = declined
        await db.commit()
        return False
    db.add(PollVote(profile_id=profile.id, poll_slot_id=slot.id, poll_response_id=response.id))
    response.declined_days = declined
    response.status = "responded"
    await db.commit()
    await refresh_poll_card(db, poll)
    return True


async def day_voter_profiles(db: AsyncSession, poll_id: int, day_of_week: int) -> list[Profile]:
    """Профили, проголосовавшие за указанный день (без дублей)."""
    rows = await db.execute(
        select(Profile)
        .join(PollVote, PollVote.profile_id == Profile.id)
        .join(PollSlot, PollSlot.id == PollVote.poll_slot_id)
        .where(PollSlot.poll_id == poll_id, PollSlot.day_of_week == day_of_week)
        .distinct()
    )
    return list(rows.scalars().all())
