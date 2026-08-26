"""Недельный сбор людей: таблица дней × времён, toggle-голосование, автосбор встреч.

Заменяет старый «ежедневный опрос». Поток:
  - воскресенье 10:00 — карточка-таблица постится/обновляется в группе;
  - участник кликает по ячейке (день × время) — голос добавляется/убирается
    (нельзя два времени в один день; в прошедший день голосовать нельзя);
  - каждый день джоб проверяет, могут ли 3 человека завтра в одно время —
    если да, материализует встречу (DailyPoll/PollSlot/MeetingInstance) и отдаёт
    её в handle_time_finalized (приглашения + напоминание + чек-ин);
  - после чек-ина участнику уходит «придёшь завтра? да/нет».

Чистые функции в начале (тестируются юнитами), БД-часть ниже.
"""
import json
import logging
from datetime import date, datetime, time, timedelta, timezone

from app.config import APP_TZ, get_settings

logger = logging.getLogger(__name__)

# Порядок дней недели (0 = понедельник). «Рабочие» по умолчанию — пн..пт.
DAYS_ALL = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
WORKING_DAYS = ("mon", "tue", "wed", "thu", "fri")
DAY_ORDER = {d: i for i, d in enumerate(DAYS_ALL)}
DAY_LABELS = {
    "mon": "Mon", "tue": "Tue", "wed": "Wed", "thu": "Thu", "fri": "Fri",
    "sat": "Sat", "sun": "Sun",
}
DAY_FULL = {
    "mon": "Monday", "tue": "Tuesday", "wed": "Wednesday", "thu": "Thursday",
    "fri": "Friday", "sat": "Saturday", "sun": "Sunday",
}
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def monday_of(d: date) -> date:
    """Понедельник недели, в которую попадает дата d."""
    return d - timedelta(days=d.weekday())


def week_start_for_poll(d: date) -> date:
    """Понедельник недели текущего опроса. В воскресенье — уже следующая неделя."""
    if d.weekday() == 6:  # воскресенье: опрос на будущую неделю
        return d + timedelta(days=1)
    return monday_of(d)


def day_code_of(d: date) -> str:
    """Код дня ('mon'..'sun') по дате."""
    return DAYS_ALL[d.weekday()]


def _minutes(time_str: str) -> int:
    h, m = time_str.split(":")
    return int(h) * 60 + int(m)


def _parse_time(time_str: str) -> time:
    h, m = time_str.split(":")
    return time(int(h), int(m))


def _time_rank(time_str: str) -> int:
    """Отрицательные минуты: для tie-break «раньше = лучше» при max()."""
    return -_minutes(time_str)


def build_weekly_table_card(
    days: list[str],
    times: list[str],
    votes: dict[tuple[str, str], int],
    scheduled: set[tuple[str, str]],
    week_start: date,
    action_url: str,
) -> dict:
    """Карточка-таблица недели: по секции на день, в секции — кнопки времён.

    votes — {(day, time): count}; scheduled — {(day, time)} уже собранных встреч.
    Кнопки шлют method=weekly_toggle + day/time в action.parameters.
    """
    sections = []
    for day in days:
        d = week_start + timedelta(days=DAY_ORDER[day])
        buttons = []
        for t in times:
            n = votes.get((day, t), 0)
            label = t
            if (day, t) in scheduled:
                label = f"✅ {t}"
            if n:
                label = f"{label} ({n})"
            buttons.append({
                "text": label,
                "onClick": {"action": {
                    "function": action_url or "weekly_toggle",
                    "parameters": [
                        {"key": "method", "value": "weekly_toggle"},
                        {"key": "day", "value": day},
                        {"key": "time", "value": t},
                    ],
                }},
            })
        sections.append({
            "header": f"{DAY_FULL[day]} · {d.day} {_MONTHS[d.month - 1]}",
            "widgets": [{"buttonList": {"buttons": buttons}}],
        })

    return {
        "cardsV2": [{
            "cardId": "weeklyAvailability",
            "card": {
                "header": {
                    "title": "📅 Meetups this week",
                    "subtitle": "Tap a time to add / remove yourself · 3 people = meetup",
                },
                "sections": sections,
            },
        }]
    }


# --- БД-часть (интеграционная) ---
from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.models import (  # noqa: E402
    DailyPoll,
    MeetingInstance,
    PollResponse,
    PollSlot,
    PollVote,
    Profile,
    WeeklyAvailabilityVote,
    WeeklyPoll,
)
from app.services.chat_sender import patch_message, send_message as send_space_message  # noqa: E402
from app.services.weekly_poll import get_or_create_config  # noqa: E402


def _now_tz(now: datetime | None = None) -> datetime:
    now = now or datetime.now(APP_TZ)
    return now.astimezone(APP_TZ) if now.tzinfo else now.replace(tzinfo=APP_TZ)


async def weekly_days(db: AsyncSession) -> list[str]:
    """Рабочие дни опроса из config['weekly_days'] (по умолчанию пн..пт)."""
    raw = (await get_or_create_config(db, "weekly_days", list(WORKING_DAYS))).value
    if isinstance(raw, str):
        raw = json.loads(raw)
    days = [d for d in (raw or []) if d in DAY_ORDER]
    days.sort(key=lambda d: DAY_ORDER[d])
    return days or list(WORKING_DAYS)


async def weekly_times(db: AsyncSession) -> list[str]:
    """Времена слотов из config['daily_slots'] (как раньше)."""
    raw = (await get_or_create_config(db, "daily_slots", ["15:00", "16:00", "17:00"])).value
    if isinstance(raw, str):
        raw = json.loads(raw)
    return [t for t in (raw or []) if isinstance(t, str)]


async def ensure_weekly_poll(db: AsyncSession, now: datetime | None = None) -> WeeklyPoll:
    """Активный недельный опрос; если нет — создать на текущую неделю."""
    week_start = week_start_for_poll(_now_tz(now).date())
    poll = (
        await db.execute(select(WeeklyPoll).where(WeeklyPoll.week_start == week_start))
    ).scalar_one_or_none()
    if poll is None:
        poll = WeeklyPoll(week_start=week_start, status="active")
        db.add(poll)
        await db.commit()
        await db.refresh(poll)
        logger.info("weekly_poll_created id=%s week_start=%s", poll.id, week_start)
    return poll


async def votes_by_day_time(db: AsyncSession, poll_id: int) -> dict[tuple[str, str], list[int]]:
    """Голоса недели как {(day, time): [profile_id, ...]}."""
    rows = (
        await db.execute(select(WeeklyAvailabilityVote).where(WeeklyAvailabilityVote.poll_id == poll_id))
    ).scalars().all()
    out: dict[tuple[str, str], list[int]] = {}
    for v in rows:
        out.setdefault((v.day, v.time), []).append(v.profile_id)
    return out


async def scheduled_slots(db: AsyncSession, week_start: date) -> set[tuple[str, str]]:
    """Слоты недели, где встреча уже собрана: {(day, time)}."""
    start = datetime.combine(week_start, time(0, 0), tzinfo=APP_TZ)
    end = start + timedelta(days=7)
    # Только встречи недельного расписания (activity_type IS NULL). Игры
    # (quiplash/who_am_i и т.п.) в таблицу «собранных» слотов попадать не должны.
    rows = (
        await db.execute(select(MeetingInstance.scheduled_start).where(
            MeetingInstance.status == "scheduled",
            MeetingInstance.scheduled_start >= start,
            MeetingInstance.scheduled_start < end,
            MeetingInstance.activity_type.is_(None),
        ))
    ).scalars().all()
    out: set[tuple[str, str]] = set()
    for s in rows:
        s = s.astimezone(APP_TZ)
        out.add((DAYS_ALL[s.weekday()], s.strftime("%H:%M")))
    return out


async def build_card_for_poll(db: AsyncSession, poll: WeeklyPoll, action_url: str = "") -> dict:
    """Актуальная карточка-таблица для опроса (счётчики + собранные встречи)."""
    days = await weekly_days(db)
    times = await weekly_times(db)
    votes = await votes_by_day_time(db, poll.id)
    counts = {(d, t): len(pids) for (d, t), pids in votes.items()}
    scheduled = await scheduled_slots(db, poll.week_start)
    return build_weekly_table_card(days, times, counts, scheduled, poll.week_start, action_url)


async def toggle_weekly_vote(db: AsyncSession, profile: Profile, day: str, time: str) -> dict:
    """Переключить голос за (day, time): есть — убрать, нет — добавить.

    Правила: опрос должен быть активен; день не прошедший (в среду нельзя
    голосовать за пн/вт); в один день одно время.
    """
    now = _now_tz()
    poll = await ensure_weekly_poll(db, now)
    if poll.status != "active":
        return {"ok": False, "reason": "closed"}
    days = await weekly_days(db)
    times = await weekly_times(db)
    if day not in days or time not in times:
        return {"ok": False, "reason": "invalid"}

    day_date = poll.week_start + timedelta(days=DAY_ORDER[day])
    if day_date < now.date():
        return {"ok": False, "reason": "past"}

    existing = (
        await db.execute(select(WeeklyAvailabilityVote).where(
            WeeklyAvailabilityVote.poll_id == poll.id,
            WeeklyAvailabilityVote.profile_id == profile.id,
            WeeklyAvailabilityVote.day == day,
        ))
    ).scalar_one_or_none()
    if existing is not None:
        if existing.time == time:
            # Клик по своему же времени — снять голос.
            await db.delete(existing)
            action = "removed"
        else:
            # Клик по другому времени того же дня — перенести голос (а не удалить).
            existing.time = time
            action = "moved"
    else:
        db.add(WeeklyAvailabilityVote(
            poll_id=poll.id, profile_id=profile.id, day=day, time=time,
        ))
        action = "added"
    await db.commit()
    logger.info("weekly_vote_toggled poll=%s profile=%s day=%s time=%s action=%s", poll.id, profile.id, day, time, action)
    return {"ok": True, "action": action, "poll_id": poll.id}


async def user_votes(db: AsyncSession, profile_id: int, poll_id: int) -> list[tuple[str, str]]:
    """Голоса участника в опросе как [(day, time)] по порядку дней."""
    rows = (
        await db.execute(select(WeeklyAvailabilityVote).where(
            WeeklyAvailabilityVote.poll_id == poll_id,
            WeeklyAvailabilityVote.profile_id == profile_id,
        ))
    ).scalars().all()
    pairs = [(v.day, v.time) for v in rows]
    pairs.sort(key=lambda p: DAY_ORDER[p[0]])
    return pairs


async def remove_weekly_vote(db: AsyncSession, profile_id: int, poll_id: int, day: str) -> int:
    """Удалить голос(а) участника за день; возвращает число удалённых."""
    rows = (
        await db.execute(select(WeeklyAvailabilityVote).where(
            WeeklyAvailabilityVote.poll_id == poll_id,
            WeeklyAvailabilityVote.profile_id == profile_id,
            WeeklyAvailabilityVote.day == day,
        ))
    ).scalars().all()
    for v in rows:
        await db.delete(v)
    await db.commit()
    return len(rows)


async def next_vote_after(db: AsyncSession, profile_id: int, after_date: date) -> tuple[str, str, int] | None:
    """Следующий день (day, time, poll_id) из голосов участника строго ПОСЛЕ after_date."""
    poll = await ensure_weekly_poll(db)
    for day, t in await user_votes(db, profile_id, poll.id):
        day_date = poll.week_start + timedelta(days=DAY_ORDER[day])
        if day_date > after_date:
            return day, t, poll.id
    return None


async def schedule_today_meetings(db: AsyncSession, now: datetime | None = None) -> dict | None:
    """Собрать встречу на сегодня, если набрался кворум в одно время.

    Берёт самое популярное время с >= quorum голосов за СЕГОДНЯ (только слоты,
    которые ещё впереди по времени); материализует
    DailyPoll/PollSlot/PollResponse/PollVote/MeetingInstance, чтобы дальше
    работал существующий пайплайн (handle_time_finalized → приглашения,
    напоминание, чек-ин). Возвращает dict или None, если встречи не будет.
    """
    tz_now = _now_tz(now)
    today = tz_now.date()
    day_code = DAYS_ALL[today.weekday()]
    days = await weekly_days(db)
    if day_code not in days:
        return None

    existing = (
        await db.execute(select(DailyPoll).where(DailyPoll.poll_date == today))
    ).scalar_one_or_none()
    if existing is not None:
        return None  # уже отработано (идемпотентность при рестарте)

    poll = await ensure_weekly_poll(db, tz_now)
    votes = await votes_by_day_time(db, poll.id)
    quorum = int((await get_or_create_config(db, "quorum_threshold", 3)).value or 3)

    # Только слоты сегодняшнего дня, которые ещё впереди (не ушедшие по времени).
    now_minutes = tz_now.hour * 60 + tz_now.minute
    candidates = {
        t: pids for (d, t), pids in votes.items()
        if d == day_code and len(pids) >= quorum and _minutes(t) > now_minutes
    }
    if not candidates:
        return None

    best_time = max(candidates, key=lambda t: (len(candidates[t]), _time_rank(t)))
    participant_ids = candidates[best_time]
    slot_start = datetime.combine(today, _parse_time(best_time), tzinfo=APP_TZ)

    daily = DailyPoll(
        poll_date=today,
        voting_deadline=datetime.combine(today, time(0, 0), tzinfo=APP_TZ),
        status="finalized",
        closed_at=datetime.now(timezone.utc),
    )
    db.add(daily)
    await db.flush()

    slot = PollSlot(
        poll_id=daily.id,
        slot_start=slot_start,
        slot_end=slot_start + timedelta(minutes=60),
        location="Online (Meet)",
    )
    db.add(slot)
    await db.flush()

    for pid in participant_ids:
        resp = PollResponse(
            profile_id=pid,
            poll_id=daily.id,
            status="responded",
            responded_at=datetime.now(timezone.utc),
        )
        db.add(resp)
        await db.flush()
        db.add(PollVote(profile_id=pid, poll_slot_id=slot.id, poll_response_id=resp.id))

    meeting = MeetingInstance(
        poll_id=daily.id,
        selected_slot_id=slot.id,
        scheduled_start=slot_start,
        scheduled_end=slot_start + timedelta(minutes=60),
        location="Online (Meet)",
        status="scheduled",
    )
    db.add(meeting)
    await db.flush()
    await db.commit()

    logger.info(
        "weekly_meeting_scheduled day=%s time=%s participants=%s meeting=%s",
        today, best_time, len(participant_ids), meeting.id,
    )
    return {
        "id": meeting.id,
        "day": DAY_LABELS[day_code],
        "time": best_time,
        "scheduled_start": slot_start,
        "participant_ids": participant_ids,
    }


async def post_or_refresh_weekly_table(db: AsyncSession, poll: WeeklyPoll, text: str = "") -> dict | None:
    """Постить таблицу в группу или обновить её на месте (messages.patch).

    Первая отправка сохраняет имя сообщения в poll.poll_message_name.
    """
    space_id = (await get_or_create_config(db, "space_id", "")).value or ""
    if not space_id:
        return None
    card = await build_card_for_poll(db, poll, get_settings().chat_app_audience)
    cards_v2 = card["cardsV2"]
    # Обновляем на месте только если сохранённое сообщение принадлежит текущей группе.
    # Иначе (бота добавили в другую группу, space_id сменился) — постим новую таблицу.
    if poll.poll_message_name and poll.poll_message_name.startswith(f"{space_id}/messages/"):
        try:
            return patch_message(poll.poll_message_name, cards_v2=cards_v2)
        except Exception:
            logger.exception("weekly_table_patch_failed poll=%s", poll.id)
            return None
    resp = send_space_message(space_id, text=text, cards_v2=cards_v2)
    name = resp.get("name")
    if name:
        poll.poll_message_name = name
        await db.commit()
    return resp
