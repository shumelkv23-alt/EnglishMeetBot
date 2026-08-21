"""Еженедельный опрос: карточка, парсинг ответов, дедлайн, рассылка, сабмит.

Чистые функции в начале файла (тестируются юнитами), БД-функции ниже
(проверяются интеграционными скриптами на поднятом Postgres).
"""
import logging
from datetime import datetime, timedelta

from app.services.form_parsing import parse_form_inputs

logger = logging.getLogger(__name__)

DAY_RU = {
    "Mon": "Понедельник",
    "Tue": "Вторник",
    "Wed": "Среда",
    "Thu": "Четверг",
    "Fri": "Пятница",
    "Sat": "Суббота",
    "Sun": "Воскресенье",
}

WORKDAY_SLOTS = [{"day": d, "time": "19:00", "location": "Онлайн (Meet)"} for d in ["Mon", "Tue", "Wed", "Thu", "Fri"]]


def slot_day_time(slot_start: datetime) -> tuple[str, str]:
    """День недели и время слота в формате схемы Slot: ("Wed", "19:00")."""
    return slot_start.strftime("%a"), slot_start.strftime("%H:%M")


def compute_deadline(slot_times: list[datetime], buffer_hours: int) -> datetime:
    """Дедлайн голосования: самый ранний слот минус буфер (REQ-2.3)."""
    return min(slot_times) - timedelta(hours=buffer_hours)


def parse_poll_form(form_inputs: dict) -> dict:
    """Разобрать formInputs карточки опроса.

    Возвращает {"answers": [("q_llm", "текст"), ("q_bank", "текст")],
    "slot_ids": [int, ...]}. Слоты — все значения полей, не начинающиеся с "q_".
    Обрабатывает оба формата Google: {name: {"stringInputs": {...}}} и
    add-on {name: {"": {"stringInputs": {...}}}}.
    """
    answers = []
    slot_ids = []
    for name, values in parse_form_inputs(form_inputs).items():
        if name.startswith("q_"):
            answers.append((name, values[0]))
        else:
            for v in values:
                try:
                    slot_ids.append(int(v))
                except (TypeError, ValueError):
                    logger.warning("poll_bad_slot_value value=%r", v)
    return {"answers": answers, "slot_ids": slot_ids}


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


def build_poll_card(personal_q: str, bank_q: str, slots: list[dict], action_url: str = "") -> dict:
    """Cards V2 карточка опроса: вопросы через textParagraph + ответы через textInput + чекбоксы дней.

    action_url — URL вебхука (chat_app_audience), куда Google отправит запрос
    при клике на кнопку. В Chat Card API action.function — это URL, а не имя
    функции (метод приходит отдельно через parameters).
    """
    question_widgets = []
    for name, label in (("q_llm", personal_q), ("q_bank", bank_q)):
        question_widgets.append({
            "textParagraph": {"text": f"<b>{label}</b>"}
        })
        question_widgets.append({
            "textInput": {"name": name, "label": "Твой ответ"}
        })

    day_items = []
    for s in slots:
        day_text = DAY_RU.get(s["label"], s["label"])
        day_items.append({
            "text": day_text,
            "value": str(s["id"]),
            "selected": False,
        })

    slot_widgets = [{
        "selectionInput": {
            "name": "slots",
            "label": "Выбери удобные дни (можно несколько)",
            "type": "CHECK_BOX",
            "items": day_items,
        }
    }] if day_items else [{
        "textParagraph": {
            "text": "На эту неделю слоты ещё не заданы — обсудим время на встрече."
        }
    }]

    return {
        "cardsV2": [
            {
                "cardId": "weeklyPoll",
                "card": {
                    "header": {
                        "title": "Еженедельный опрос 🗓️",
                        "subtitle": "Ответь на 2 вопроса и отметь удобные дни",
                    },
                    "sections": [
                        {"header": "Вопросы недели", "widgets": question_widgets},
                        {"header": "Удобные дни", "widgets": slot_widgets},
                        {
                            "widgets": [
                                {
                                    "buttonList": {
                                        "buttons": [
                                            {
                                                "text": "Отправить",
                                                "onClick": {
                                                    "action": {
                                                        "function": action_url or "weekly_poll_submit",
                                                        "parameters": [
                                                            {"key": "method", "value": "submit_weekly_poll"}
                                                        ],
                                                    }
                                                },
                                            }
                                        ]
                                    }
                                }
                            ]
                        },
                    ],
                },
            }
        ]
    }


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


# --- БД-часть (интеграционная) ---
from datetime import date, date as date_type, timezone  # noqa: E402

from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.models import (  # noqa: E402
    Config,
    PollQuestion,
    PollResponse,
    PollSlot,
    PollVote,
    Profile,
    DailyPoll,
)
from app.config import get_settings  # noqa: E402
from app.services.onboarding import current_week_start  # noqa: E402
from app.services.question_bank import bank_questions_for  # noqa: E402
from app.messaging import send_message  # noqa: E402
from app.schemas import MessagePayload  # noqa: E402


def _config_slots(db_cfg_value) -> list[dict]:
    """Слоты из config: [{"day": "Wed", "time": "19:00"}, ...] или []."""
    if isinstance(db_cfg_value, dict):
        raw = db_cfg_value.get("poll_slots") or []
    else:
        raw = db_cfg_value or []
    return [item for item in raw if isinstance(item, dict)]


def _slot_datetime_for_week(week_start: date_type, day: str, time: str) -> datetime | None:
    """datetime слота в рамках недели (понедельник = day 0)."""
    days = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}
    if day not in days or len(time) != 5 or time[2] != ":":
        return None
    hour, minute = int(time[:2]), int(time[3:5])
    return datetime.combine(
        week_start + timedelta(days=days[day]),
        datetime.min.time().replace(hour=hour, minute=minute),
        tzinfo=None,
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


async def active_poll_for_week(db: AsyncSession, week_start: date_type) -> DailyPoll | None:
    return (
        await db.execute(
            select(DailyPoll).where(
                DailyPoll.week_start == week_start,
                DailyPoll.status == "active",
            )
        )
    ).scalar_one_or_none()


def _week_aware(week_start: date_type, naive: datetime) -> datetime:
    """Формат хранения проекта — timestamptz; храним с UTC-поясом.

    week_start как date и также как базис для замены даты — на случай слота,
    выпавшего на другие сутки из-за week_start + days.
    """
    return naive.replace(tzinfo=timezone.utc)


async def _copy_last_week_slots(db: AsyncSession, poll: DailyPoll, week_start: date_type) -> int:
    """Автокопия слотов прошлой недели (REQ-10) для нового опроса."""
    prev_poll = (
        await db.execute(
            select(DailyPoll)
            .where(DailyPoll.week_start < week_start)
            .order_by(DailyPoll.week_start.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if prev_poll is None:
        return 0
    prev_slots = (
        await db.execute(select(PollSlot).where(PollSlot.poll_id == prev_poll.id))
    ).scalars().all()
    if not prev_slots:
        return 0
    created = 0
    for ps in prev_slots:
        wd, tm = ps.slot_start.strftime("%a"), ps.slot_start.strftime("%H:%M")
        new_start = _slot_datetime_for_week(week_start, wd, tm)
        if new_start is None:
            continue
        db.add(PollSlot(
            poll_id=poll.id,
            slot_start=_week_aware(week_start, new_start),
            slot_end=_week_aware(week_start, new_start) + timedelta(minutes=90),
            location=ps.location,
            priority=ps.priority,
        ))
        created += 1
    return created


async def ensure_weekly_poll(db: AsyncSession, now: datetime) -> DailyPoll | None:
    """Активный опрос недели; если нет — создать: слоты из config или
    автокопия прошлой недели, дедлайн = min(слоты) − VOTING_BUFFER_HOURS."""
    week_start = current_week_start()
    poll = await active_poll_for_week(db, week_start)
    if poll is not None:
        return poll

    cfg = await get_or_create_config(db, "poll_slots", [])
    slots_cfg = _config_slots(cfg.value)

    poll = DailyPoll(
        week_start=week_start,
        voting_deadline=now + timedelta(days=7),  # временное; пересчитаем ниже
        status="active",
    )
    db.add(poll)
    await db.flush()

    slot_times: list[datetime] = []
    for item in slots_cfg:
        dt = _slot_datetime_for_week(week_start, item.get("day", ""), item.get("time", ""))
        if dt is None:
            continue
        db.add(PollSlot(
            poll_id=poll.id,
            slot_start=_week_aware(week_start, dt),
            slot_end=_week_aware(week_start, dt) + timedelta(minutes=90),
            location=item.get("location", "Онлайн (Meet)"),
            priority=item.get("priority", 0),
        ))
        slot_times.append(dt)

    if not slot_times:
        for item in WORKDAY_SLOTS:
            dt = _slot_datetime_for_week(week_start, item["day"], item["time"])
            if dt is None:
                continue
            db.add(PollSlot(
                poll_id=poll.id,
                slot_start=_week_aware(week_start, dt),
                slot_end=_week_aware(week_start, dt) + timedelta(minutes=90),
                location=item.get("location", "Онлайн (Meet)"),
                priority=item.get("priority", 0),
            ))
            slot_times.append(dt)
        if slot_times:
            logger.info("weekly_poll_default_slots created=%s", len(slot_times))
        else:
            logger.warning("weekly_poll_no_slots week=%s", week_start)

    slots = (await db.execute(select(PollSlot).where(PollSlot.poll_id == poll.id))).scalars().all()
    if slots:
        poll.voting_deadline = compute_deadline(
            [s.slot_start for s in slots],
            int((await get_or_create_config(db, "voting_buffer_hours", 24)).value or 24),
        )
    await db.commit()
    await db.refresh(poll)
    logger.info("weekly_poll_created id=%s deadline=%s slots=%s", poll.id, poll.voting_deadline, len(slots))
    return poll


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


# --- генерация и рассылка ---
from app.services.llm_questions import generate_personal_question  # noqa: E402


async def ensure_personal_questions(db: AsyncSession, poll: DailyPoll, profiles: list[Profile]) -> int:
    """Пакетная генерация персональных вопросов (подход Б, идемпотентно).

    Для профилей с interests зовёт LLM; результат — upsert в poll_questions.
    Сбой генерации — просто нет записи (в карточке будет запасной вопрос банка).
    Возвращает количество созданных вопросов.
    """
    created = 0
    for profile in profiles:
        exists = (
            await db.execute(
                select(PollQuestion).where(
                    PollQuestion.poll_id == poll.id,
                    PollQuestion.profile_id == profile.id,
                )
            )
        ).scalar_one_or_none()
        if exists is not None:
            continue  # уже сгенерировано — не дублируем
        interests = list(profile.interests or [])
        text = generate_personal_question(interests)
        if text is None:
            logger.warning("poll_question_llm_fallback profile_id=%s", profile.id)
            continue
        db.add(PollQuestion(poll_id=poll.id, profile_id=profile.id, question_text=text))
        created += 1
    await db.commit()
    logger.info("poll_questions_generated created=%s", created)
    return created


async def send_weekly_polls(db: AsyncSession, now: datetime) -> dict:
    """Шаг 1: опрос недели; шаг 2: генерация; шаг 3: рассылка карточек;
    шаг 4: poll_responses (pending). Ответивших не беспокоим."""
    poll = await ensure_weekly_poll(db, now)
    if poll is None:
        return {"poll_id": None, "sent": 0, "personal_ok": False}

    bank_q1, bank_q2 = bank_questions_for(poll.week_start)
    profiles = (await db.execute(
        select(Profile).where(
            Profile.is_active.is_(True),
            Profile.onboarding_completed.is_(True),
            Profile.workspace_user_id.isnot(None),
        )
    )).scalars().all()

    await ensure_personal_questions(db, poll, profiles)

    # персональный текст каждого (или запасной банковский)
    personal_by_profile = {}
    for row in (await db.execute(
        select(PollQuestion).where(PollQuestion.poll_id == poll.id)
    )).scalars().all():
        personal_by_profile[row.profile_id] = row.question_text

    responded_profile_ids = set(
        (await db.execute(
            select(PollResponse.profile_id).where(
                PollResponse.poll_id == poll.id,
                PollResponse.status == "responded",
            )
        )).scalars().all()
    )

    slots = (await db.execute(
        select(PollSlot).where(PollSlot.poll_id == poll.id).order_by(PollSlot.slot_start)
    )).scalars().all()
    slot_labels = [
        {"id": s.id, "label": s.slot_start.strftime("%a")}
        for s in slots
    ]

    sent = 0
    for profile in profiles:
        if profile.id in responded_profile_ids:
            continue
        personal_q = personal_by_profile.get(profile.id) or bank_q2  # фолбэк на банк
        card = build_poll_card(personal_q, bank_q1, slot_labels, action_url=get_settings().chat_app_audience)
        send_message(
            profile.workspace_user_id,
            MessagePayload(text="Еженедельный опрос 🗓️", card=card),
        )
        response = (
            await db.execute(
                select(PollResponse).where(
                    PollResponse.profile_id == profile.id,
                    PollResponse.poll_id == poll.id,
                )
            )
        ).scalar_one_or_none()
        if response is None:
            response = PollResponse(profile_id=profile.id, poll_id=poll.id)
            db.add(response)
        await db.flush()
        sent += 1
    await db.commit()
    logger.info("weekly_polls_sent poll=%s sent=%s", poll.id, sent)
    return {"poll_id": poll.id, "sent": sent, "personal_ok": bool(personal_by_profile)}