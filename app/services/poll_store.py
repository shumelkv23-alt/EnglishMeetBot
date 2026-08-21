# app/services/poll_store.py
"""DB-слой еженедельного голосования: связывает чистую логику
poll_logic/poll_card с базой и отправкой.

Здесь живёт ВСЁ, что требует БД/сети (сами poll_logic/poll_card остаются
чистыми). Вызывающие слоты — вебхук (save_poll_vote) и планировщик
(create_weekly_poll_and_broadcast / decide_tomorrow / finalize_expired_weeks).

Карта записи в БД — см. docstring app/services/poll_logic.py.
"""
import logging
from datetime import date, datetime, time as dtime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import (
    Answer,
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
from app.services.poll_card import DEFAULT_THEME_QUESTIONS, build_poll_card
from app.services.poll_logic import (
    DEFAULT_ANNOUNCEMENT_HOUR,
    MEETING,
    NEED_MORE_VOTES,
    RU_DAYS,
    DayVotes,
    MeetingPlan,
    MessagePlan,
    Slot,
    build_week_slots,
    decide_for_tomorrow,
    escalation_text,
    plan_week_messages,
    week_cancelled_text,
    week_start_for,
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


def _week_end(week_start: date) -> datetime:
    """Воскресенье 23:59 UTC недели week_start (voting_deadline по спеке)."""
    return datetime.combine(
        week_start + timedelta(days=6), dtime(23, 59), tzinfo=timezone.utc
    )


def _day_start(day: date) -> datetime:
    return datetime.combine(day, dtime(0, 0), tzinfo=timezone.utc)


def _day_end(day: date) -> datetime:
    return _day_start(day + timedelta(days=1))


def slot_key_for(day: date, start: datetime) -> str:
    """Стабильный ключ слота — тот же формат, что в build_week_slots()."""
    return f"{day.isoformat()}T{start.hour:02d}{start.minute:02d}"


# ---------------------------------------------------------------------
# Создание опроса недели
# ---------------------------------------------------------------------

async def get_or_create_poll_for_week(db: AsyncSession, week_start: date) -> WeeklyPoll:
    """Опрос на неделю week_start: создать с полным набором слотов или вернуть существующий.

    Существующий опрос НЕ трогаем (голоса посреди недели стирать нельзя).
    """
    poll = (
        await db.execute(select(WeeklyPoll).where(WeeklyPoll.week_start == week_start))
    ).scalar_one_or_none()

    if poll is None:
        location = await config_value(db, "default_location", "")
        poll = WeeklyPoll(
            week_start=week_start,
            voting_deadline=_week_end(week_start),
            status="active",
        )
        db.add(poll)
        await db.flush()  # нужен poll.id для слотов

        slots = build_week_slots(week_start, location=str(location or ""))
        for s in slots:
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
        logger.info("weekly_poll_created week_start=%s slots=%s", str(week_start), len(slots))
    return poll


async def current_or_next_poll(db: AsyncSession, today: date) -> WeeklyPoll | None:
    """Активный опрос ближайшей недели: текущей или следующей."""
    this_week = week_start_for(today)
    poll = (
        await db.execute(
            select(WeeklyPoll)
            .where(
                WeeklyPoll.status == "active",
                WeeklyPoll.week_start >= this_week,
            )
            .order_by(WeeklyPoll.week_start)
            .limit(1)
        )
    ).scalar_one_or_none()
    return poll


async def create_weekly_poll_and_broadcast(db: AsyncSession) -> dict:
    """Воскресный сценарий: опрос на следующую неделю + карточка всем, кто писал боту.

    Возвращает сводку {week_start, created, sent, skipped}.
    """
    next_week = week_start_for(date.today()) + timedelta(days=7)
    quorum = int(await config_value(db, "quorum_threshold", 3) or 3)

    existing = (
        await db.execute(select(WeeklyPoll).where(WeeklyPoll.week_start == next_week))
    ).scalar_one_or_none()
    created = existing is None

    poll = await get_or_create_poll_for_week(db, next_week)

    card = build_poll_card(week_start=poll.week_start, quorum=quorum)["cardsV2"]

    profiles = (await db.execute(select(Profile))).scalars().all()
    sent, skipped = 0, 0
    for profile in profiles:
        if not await ensure_profile_dm(db, profile):
            skipped += 1
            continue
        try:
            chat_sender.send_card(profile.chat_space_id, card)
            sent += 1
        except Exception:
            logger.exception("poll_card_send_failed profile_id=%s", profile.id)
            skipped += 1

    logger.info(
        "weekly_poll_broadcast week=%s created=%s sent=%s skipped=%s",
        str(next_week), created, sent, skipped,
    )
    return {"week_start": str(next_week), "created": created, "sent": sent, "skipped": skipped}


# ---------------------------------------------------------------------
# Парсинг формы голосования (чистая функция — покрыта тестами)
# ---------------------------------------------------------------------

def parse_poll_form(form_inputs: dict) -> tuple[list[date], list[str]]:
    """formInputs клика «Забронировать день» -> (выбранные даты, ответы на темы).

    Понимает оба формата Google:
      классический {"days": {"stringInputs": {"value": [...]}}}
      add-on        {"days": {"": {"stringInputs": {"value": [...]}}}}
    Даты без валидного ISO-формата молча отбрасываются.
    Темы — список из ДВУХ строк, выровненный по вопросам
    (q_theme1, q_theme2); неотвеченный вопрос — пустая строка.
    """
    def values_of(name: str) -> list[str]:
        field = form_inputs.get(name)
        if not isinstance(field, dict):
            return []
        payload = field.get("stringInputs") or field.get("")
        # add-on: под ключом "" лежит ещё одна обёртка stringInputs
        if isinstance(payload, dict) and "stringInputs" in payload:
            payload = payload["stringInputs"]
        if not isinstance(payload, dict):
            return []
        raw = payload.get("value", [])
        return [v.strip() for v in raw if isinstance(v, str) and v.strip()]

    def single_of(name: str) -> str:
        vals = values_of(name)
        return vals[0] if vals else ""

    days: list[date] = []
    seen: set[date] = set()
    for raw in values_of("days"):
        try:
            d = date.fromisoformat(raw)
        except ValueError:
            continue
        if d not in seen:
            seen.add(d)
            days.append(d)

    themes = [single_of("q_theme1"), single_of("q_theme2")]
    return days, themes


# ---------------------------------------------------------------------
# Приём голоса (вебхук)
# ---------------------------------------------------------------------

async def save_poll_vote(db: AsyncSession, profile: Profile, form_inputs: dict) -> str:
    """Сохранить голос участника и вернуть текст подтверждения для DM.

    - poll_responses: upsert по (profile_id, poll_id), status='responded'
    - poll_votes: ПЕРЕЗАПИСЬ голосов этого участника в рамках опроса
    - answers: ответы на тематические вопросы (append-only)
    Счётчики votes_count пересчитывают триггеры БД.
    """
    days, themes = parse_poll_form(form_inputs)
    if not days:
        return (
            "Не вижу выбранных дней 🤔 Отметь хотя бы один день "
            "в карточке и нажми кнопку ещё раз."
        )

    week = week_start_for(days[0])
    poll = (
        await db.execute(select(WeeklyPoll).where(WeeklyPoll.week_start == week))
    ).scalar_one_or_none()
    if poll is None or poll.status != "active":
        return (
            "Опрос на эту неделю не найден или уже закрыт. "
            "Напиши «голосование», чтобы получить актуальную карточку."
        )

    slots = (
        await db.execute(select(PollSlot).where(PollSlot.poll_id == poll.id))
    ).scalars().all()
    slot_by_day = {s.slot_start.date(): s for s in slots}

    # 1. upsert poll_responses (UNIQUE profile_id + poll_id)
    response = (
        await db.execute(
            select(PollResponse).where(
                PollResponse.profile_id == profile.id,
                PollResponse.poll_id == poll.id,
            )
        )
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if response is None:
        response = PollResponse(
            profile_id=profile.id,
            poll_id=poll.id,
            status="responded",
            responded_at=now,
        )
        db.add(response)
        await db.flush()
    else:
        response.status = "responded"
        response.responded_at = now

    # 2. перезапись голосов участника в этом опросе (повторное голосование)
    old_slot_ids = [s.id for s in slots]
    if old_slot_ids:
        await db.execute(
            delete(PollVote).where(
                PollVote.profile_id == profile.id,
                PollVote.poll_slot_id.in_(old_slot_ids),
            )
        )

    chosen_days: list[date] = []
    for day in days:
        slot = slot_by_day.get(day)
        if slot is None:
            continue
        db.add(
            PollVote(
                poll_response_id=response.id,
                profile_id=profile.id,
                poll_slot_id=slot.id,
                voted_at=now,
            )
        )
        chosen_days.append(day)

    # 3. тематические ответы -> answers (append-only история)
    for question_text, answer_text in zip(DEFAULT_THEME_QUESTIONS, themes):
        if not answer_text:
            continue
        db.add(
            Answer(
                profile_id=profile.id,
                question_text=question_text,
                answer_text=answer_text,
                is_public=profile.public_consent,
                week_start=poll.week_start,
            )
        )

    await db.commit()

    labels = ", ".join(RU_DAYS[d.weekday()] for d in sorted(chosen_days))
    logger.info(
        "poll_vote_saved profile_id=%s poll_id=%s days=%s themes=%s",
        profile.id, poll.id, [str(d) for d in chosen_days], len(themes),
    )
    if not chosen_days:
        return "Дни из карточки не совпали со слотами опроса — попробуй ещё раз."
    return (
        f"Голос учтён ✅ Ты выбрал(а): {labels} в 13:00–14:00.\n"
        "Встреча назначится на ПЕРВЫЙ день, когда наберётся кворум. "
        "Можно проголосовать заново в любой момент — новые дни заменят старые."
    )


# ---------------------------------------------------------------------
# Ежедневное решение «на завтра»
# ---------------------------------------------------------------------

async def _day_votes_for(db: AsyncSession, poll: WeeklyPoll, day: date) -> DayVotes | None:
    """Итоги голосования по конкретному дню опроса (poll_votes JOIN poll_slots)."""
    rows = (
        await db.execute(
            select(PollSlot, PollVote.profile_id)
            .join(PollVote, PollVote.poll_slot_id == PollSlot.id)
            .where(
                PollSlot.poll_id == poll.id,
                PollSlot.slot_start >= _day_start(day),
                PollSlot.slot_start < _day_end(day),
            )
        )
    ).all()
    if not rows:
        return None

    votes_by_slot: dict[int, set[int]] = {}
    slot_by_id: dict[int, PollSlot] = {}
    for slot, profile_id in rows:
        slot_by_id[slot.id] = slot
        votes_by_slot.setdefault(slot.id, set()).add(profile_id)

    voters: set[int] = set()
    slots: list[Slot] = []
    for slot_id, slot in slot_by_id.items():
        count = len(votes_by_slot.get(slot_id, set()))
        voters.update(votes_by_slot.get(slot_id, set()))
        slots.append(
            Slot(
                slot_key=slot_key_for(day, slot.slot_start),
                day=day,
                start=slot.slot_start,
                end=slot.slot_end,
                votes=count,
                location=slot.location,
            )
        )

    return DayVotes(day=day, voters=len(voters), slots=tuple(slots))


async def _recipients_for_day(db: AsyncSession, poll: WeeklyPoll, day: date) -> list[str]:
    """workspace_user_id всех, кто голосовал за день (для анонса/напоминания)."""
    rows = (
        await db.execute(
            select(Profile.workspace_user_id)
            .join(PollVote, PollVote.profile_id == Profile.id)
            .join(PollSlot, PollVote.poll_slot_id == PollSlot.id)
            .where(
                PollSlot.poll_id == poll.id,
                PollSlot.slot_start >= _day_start(day),
                PollSlot.slot_start < _day_end(day),
            )
            .distinct()
        )
    ).scalars().all()
    return [r for r in rows if r]


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


from app.database import AsyncSessionLocal  # noqa: E402


async def _deliver_to_users(recipient_ids: tuple[str, ...], text: str) -> int:
    """Доставить текст в DM каждому получателю. Возвращает число доставок.

    Полностью async: вызывается из вебхука и async-джоб планировщика,
    поэтому общий движок БД всегда используется из своего event loop.
    """
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


async def _announce_and_plan_reminder(
    meeting_plan: MeetingPlan, recipient_ids: list[str], reminder_hours: int
) -> MessagePlan | None:
    """Отправить ANNOUNCEMENT сразу (решение принимаем в 20:00 вечера накануне),
    вернуть REMINDER-план планировщику."""
    plans = plan_week_messages(
        meeting_plan,
        recipients=recipient_ids,
        announcement_hour=DEFAULT_ANNOUNCEMENT_HOUR,
        reminder_hours=reminder_hours,
    )
    for plan in plans:
        if plan.kind == "ANNOUNCEMENT":
            delivered = await _deliver_to_users(plan.recipients, plan.text)
            logger.info("announcement_sent delivered=%s", delivered)
    reminders = [p for p in plans if p.kind == "REMINDER"]
    return reminders[0] if reminders else None


async def decide_tomorrow(db: AsyncSession, now: datetime) -> dict:
    """Ежедневная проверка в 20:00 UTC: хватает ли голосов на завтрашний день.

    Возвращает {'decision': Decision|None, 'reminder': MessagePlan|None}.
    MEETING   -> создаёт meeting_instances, закрывает опрос, шлёт анонс
                 проголосовавшим, reminder отдаёт планировщику.
    NEED_MORE_VOTES -> эскалация в chat_test_space.
    Активного опроса на завтра нет -> {'decision': None, 'reminder': None}.
    """
    tomorrow = (now + timedelta(days=1)).date()
    poll = (
        await db.execute(
            select(WeeklyPoll).where(
                WeeklyPoll.status == "active",
                WeeklyPoll.week_start <= tomorrow,
                WeeklyPoll.week_start >= tomorrow - timedelta(days=6),
            )
        )
    ).scalar_one_or_none()
    if poll is None:
        return {"decision": None, "reminder": None}

    day_votes = await _day_votes_for(db, poll, tomorrow)
    quorum = int(await config_value(db, "quorum_threshold", 3) or 3)
    decision = decide_for_tomorrow(day_votes, quorum)

    if decision.kind == MEETING and decision.meeting is not None:
        slot = decision.meeting.slot
        slot_row = (
            await db.execute(
                select(PollSlot).where(
                    PollSlot.poll_id == poll.id,
                    PollSlot.slot_start == slot.start,
                )
            )
        ).scalar_one()

        meeting = MeetingInstance(
            poll_id=poll.id,
            selected_slot_id=slot_row.id,
            scheduled_start=slot_row.slot_start,
            scheduled_end=slot_row.slot_end,
            location=slot_row.location,
            status="scheduled",
        )
        db.add(meeting)
        poll.status = "closed"
        poll.closed_at = now
        await db.commit()
        await db.refresh(meeting)

        recipients = await _recipients_for_day(db, poll, tomorrow)
        reminder_hours = int(await config_value(db, "meeting_reminder_hours", 1) or 1)
        reminder = await _announce_and_plan_reminder(
            decision.meeting, recipients, reminder_hours
        )
        logger.info(
            "meeting_fixed meeting_id=%s day=%s voters=%s recipients=%s",
            meeting.id, str(tomorrow), decision.voters, len(recipients),
        )
        return {"decision": decision, "reminder": reminder}

    if decision.kind == NEED_MORE_VOTES:
        send_escalation(escalation_text(decision.day, decision.voters, decision.quorum))

    return {"decision": decision, "reminder": None}


def send_escalation(text: str) -> bool:
    """Эскалация организатору — в settings.chat_test_space."""
    space = get_settings().chat_test_space
    if not space:
        logger.warning("escalation_skipped_no_space text=%r", text[:80])
        return False
    try:
        chat_sender.send_text(space, text)
        return True
    except Exception:
        logger.exception("escalation_send_failed")
        return False


# ---------------------------------------------------------------------
# Финал недели: никто не набрал кворум
# ---------------------------------------------------------------------

async def finalize_expired_weeks(db: AsyncSession, now: datetime) -> int:
    """Активные опросы, чья неделя уже закончилась, закрыть как cancelled
    с финальной эскалацией. Возвращает число закрытых."""
    today = now.date()
    expired = (
        await db.execute(
            select(WeeklyPoll).where(
                WeeklyPoll.status == "active",
                WeeklyPoll.week_start + timedelta(days=6) < today,
            )
        )
    ).scalars().all()

    closed = 0
    for poll in expired:
        quorum = int(await config_value(db, "quorum_threshold", 3) or 3)
        poll.status = "cancelled"
        closed += 1
        send_escalation(week_cancelled_text(quorum))
        logger.info("weekly_poll_cancelled week_start=%s", str(poll.week_start))

    if closed:
        await db.commit()
    return closed
