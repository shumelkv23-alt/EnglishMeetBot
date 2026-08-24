"""Ежедневный опрос: карточка, сабмит, создание опроса дня, финализация.

Чистые функции в начале файла (тестируются юнитами), БД-функции ниже
(проверяются интеграционными скриптами на поднятом Postgres).
"""
import json
import logging
from datetime import datetime, timedelta

from app.services.form_parsing import parse_form_inputs

logger = logging.getLogger(__name__)


def _normalize_submit_time(form_inputs: dict) -> str:
    """Одно выбранное время из formInputs: "15:00" / "not_available" или ""."""
    vals = parse_form_inputs(form_inputs).get("time", [])
    return vals[0] if vals else ""


ALLOWED_SUBMIT_TIMES = frozenset({"15:00", "16:00", "17:00"})


def _is_valid_submit_time(choice: str) -> bool:
    """Допустимое значение сабмита: "not_available" или слот из ALLOWED_SUBMIT_TIMES.

    Защищает slot_datetime от невалидного входа ("banana", "15") — валидация
    до вызова, невалидное время в submit_poll превращается в reason="empty".
    """
    return choice == "not_available" or choice in ALLOWED_SUBMIT_TIMES


def resolve_day_result(votes: dict[str, int], quorum: int) -> dict:
    """Итог дня: какие времена набрали порог, кому предложить другое время.

    votes — {"15:00": N, ...}; quorum — минимальное число голосов.
    Возвращает {"meetings": [...], "suggest_to": {...}, "cancelled": bool}.
    """
    meetings = [t for t, c in votes.items() if c >= quorum]
    if not meetings:
        return {"meetings": [], "suggest_to": {}, "cancelled": True}
    # самое популярное из состоявшихся — для предложения недобравшим
    best = max(meetings, key=lambda t: votes[t])
    suggest_to = {
        t: best
        for t, c in votes.items()
        if 0 < c < quorum
    }
    return {"meetings": sorted(meetings), "suggest_to": suggest_to, "cancelled": False}


def build_daily_poll_card(slots: list[str], action_url: str, votes: dict[str, int] | None = None) -> dict:
    """Карточка ежедневного опроса. votes — {time: N} для счётчика голосов.

    При наличии votes кнопки показывают «15:00 (2)»; значение клика по-прежнему
    идёт в parameters["time"] (без счётчика).
    """
    votes = votes or {}
    buttons = []
    for t in slots:
        n = votes.get(t, 0)
        label = f"{t} ({n})" if n else t
        buttons.append({
            "text": label,
            "onClick": {"action": {
                "function": action_url or "submit_daily_poll",
                "parameters": [
                    {"key": "method", "value": "submit_daily_poll"},
                    {"key": "time", "value": t},
                ],
            }},
        })
    buttons.append({
        "text": "Не могу сегодня",
        "onClick": {"action": {
            "function": action_url or "submit_daily_poll",
            "parameters": [
                {"key": "method", "value": "submit_daily_poll"},
                {"key": "time", "value": "not_available"},
            ],
        }},
    })
    return {
        "cardsV2": [{
            "cardId": "dailyPoll",
            "card": {
                "header": {"title": "Кто сегодня и во сколько? 🗓️",
                           "subtitle": "Выбери время или «не могу»"},
                "sections": [{"widgets": [{"buttonList": {"buttons": buttons}}]}],
            },
        }]
    }


# --- БД-часть (интеграционная) ---
from datetime import date, timezone  # noqa: E402

from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.config import APP_TZ  # noqa: E402
from app.models import (  # noqa: E402
    Config,
    DailyPoll,
    MeetingInstance,
    PollResponse,
    PollSlot,
    PollVote,
    Profile,
)


async def get_or_create_config(db: AsyncSession, key: str, fallback_value) -> Config:
    cfg = (await db.execute(select(Config).where(Config.key == key))).scalar_one_or_none()
    if cfg is None:
        cfg = Config(key=key, value=fallback_value)
        db.add(cfg)
        await db.commit()
        await db.refresh(cfg)
    return cfg


def today() -> date:
    """Текущий день в UTC — дата ежедневного опроса."""
    return datetime.now(timezone.utc).date()


def slot_datetime(time_str: str) -> datetime:
    """Слот-время как datetime: часы/минуты на фиксированной дате-переносчике."""
    h, m = time_str.split(":")
    return datetime(2000, 1, 1, int(h), int(m), tzinfo=timezone.utc)


async def active_daily_poll(db: AsyncSession, day: date) -> DailyPoll | None:
    """Активный опрос дня (status='active') или None."""
    return (
        await db.execute(
            select(DailyPoll).where(
                DailyPoll.poll_date == day,
                DailyPoll.status == "active",
            )
        )
    ).scalar_one_or_none()


async def ensure_daily_poll(db: AsyncSession, now: datetime) -> DailyPoll | None:
    """Активный опрос дня; если нет — создать опрос и слоты из config['daily_slots'].

    Слоты создаются с slot_start = slot_datetime(t) (carrier-дата 2000-01-01) —
    так submit_poll матчит голос по slot_start == slot_datetime(choice).
    """
    day = now.date()
    poll = await active_daily_poll(db, day)
    if poll is not None:
        return poll

    raw_slots = (await get_or_create_config(db, "daily_slots", ["15:00", "16:00", "17:00"])).value
    if isinstance(raw_slots, str):  # запасной вариант: конфиг хранился как JSON-строка
        raw_slots = json.loads(raw_slots)
    slot_times = [t for t in raw_slots if isinstance(t, str)]

    deadline_h = int((await get_or_create_config(db, "poll_deadline_hour", 14)).value or 14)
    deadline_m = int((await get_or_create_config(db, "poll_deadline_minute", 0)).value or 0)

    poll = DailyPoll(
        poll_date=day,
        voting_deadline=datetime(day.year, day.month, day.day, deadline_h, deadline_m, tzinfo=APP_TZ),
        status="active",
    )
    db.add(poll)
    await db.flush()
    for t in slot_times:
        st = slot_datetime(t)
        db.add(PollSlot(
            poll_id=poll.id,
            slot_start=st,
            slot_end=st + timedelta(minutes=60),
            location="Онлайн (Meet)",
        ))
    await db.commit()
    logger.info("daily_poll_created id=%s date=%s slots=%s", poll.id, day, len(slot_times))
    return poll


async def finalize_daily_poll(db: AsyncSession, poll: DailyPoll) -> dict:
    """Подвести итог дня: создать встречи для времён, набравших порог.

    Возвращает {"result": resolve_day_result(...), "space_id": из config,
    "meetings": [{"id", "day", "time", "scheduled_start"}, ...]}.
    """
    slots = (await db.execute(
        select(PollSlot).where(PollSlot.poll_id == poll.id)
    )).scalars().all()
    votes = {
        s.slot_start.strftime("%H:%M"): (s.votes_count or 0)
        for s in slots
    }
    quorum = int((await get_or_create_config(db, "quorum_threshold", 3)).value or 3)
    result = resolve_day_result(votes, quorum)

    slot_by_time = {s.slot_start.strftime("%H:%M"): s for s in slots}
    created = []
    for t in result["meetings"]:
        slot_time = slot_datetime(t).time()
        scheduled_start = datetime.combine(poll.poll_date, slot_time, tzinfo=APP_TZ)
        meeting = MeetingInstance(
            poll_id=poll.id,
            selected_slot_id=slot_by_time[t].id,
            scheduled_start=scheduled_start,
            scheduled_end=scheduled_start + timedelta(minutes=60),
            location="Онлайн (Meet)",
            status="scheduled",
        )
        db.add(meeting)
        created.append(meeting)
    poll.status = "finalized" if result["meetings"] else "cancelled"
    poll.closed_at = datetime.now(timezone.utc)
    await db.flush()  # присваиваем id созданным встречам (нужны для invites)

    meetings_out = [
        {
            "id": m.id,
            "day": m.scheduled_start.strftime("%a"),
            "time": m.scheduled_start.strftime("%H:%M"),
            "scheduled_start": m.scheduled_start,
        }
        for m in created
    ]
    await db.commit()
    space_id = (await get_or_create_config(db, "space_id", "")).value or ""
    return {"result": result, "space_id": space_id, "meetings": meetings_out}


async def submit_poll(db: AsyncSession, profile: Profile, form_inputs: dict) -> dict:
    """Сабмит ежедневного опроса: одно время на человека или «не могу»."""
    poll = await active_daily_poll(db, today())
    if poll is None:
        return {"ok": False, "reason": "no_poll"}
    deadline = poll.voting_deadline
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    if deadline < datetime.now(timezone.utc):
        return {"ok": False, "reason": "closed"}

    choice = _normalize_submit_time(form_inputs)
    if not _is_valid_submit_time(choice):
        return {"ok": False, "reason": "empty"}

    response = (
        await db.execute(select(PollResponse).where(
            PollResponse.profile_id == profile.id, PollResponse.poll_id == poll.id))
    ).scalar_one_or_none()
    if response is None:
        response = PollResponse(profile_id=profile.id, poll_id=poll.id)
        db.add(response)
    await db.flush()  # response.id заполнен до вставки PollVote (без неявного autoflush)

    # одно время на человека: убрать старые голоса
    await db.execute(delete(PollVote).where(
        PollVote.profile_id == profile.id,
        PollVote.poll_slot_id.in_(select(PollSlot.id).where(PollSlot.poll_id == poll.id)),
    ))

    if choice == "not_available":
        response.status = "not_available"
        response.responded_at = None  # CHECK valid_response: responded_at только при responded
    else:
        slot = (
            await db.execute(select(PollSlot).where(
                PollSlot.poll_id == poll.id, PollSlot.slot_start == slot_datetime(choice)))
        ).scalar_one_or_none()
        if slot is None:
            await db.rollback()  # откат pending: новый response и удалённые старые голоса
            return {"ok": False, "reason": "empty"}
        db.add(PollVote(profile_id=profile.id, poll_slot_id=slot.id, poll_response_id=response.id))
        response.status = "responded"
        response.responded_at = datetime.now(timezone.utc)

    await db.commit()
    return {"ok": True, "reason": "saved"}


async def build_daily_poll_card_with_counts(db: AsyncSession, poll: DailyPoll, action_url: str) -> dict:
    """Карточка опроса с актуальными счётчиками голосов (слоты из БД)."""
    slots = (await db.execute(select(PollSlot).where(PollSlot.poll_id == poll.id))).scalars().all()
    slots = sorted(slots, key=lambda s: s.slot_start)
    times = [s.slot_start.strftime("%H:%M") for s in slots]
    votes = {s.slot_start.strftime("%H:%M"): (s.votes_count or 0) for s in slots}
    return build_daily_poll_card(times, action_url, votes)
