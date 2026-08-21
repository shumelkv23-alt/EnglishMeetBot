# app/services/poll_logic.py
"""Чистая логика недельного голосования «ближайший день + кворум».

ОГРАНИЧЕНИЯ (по требованию команды):
- НЕ вызываем сеть, БД и asyncio — только чистые функции над простыми данными.
- НЕ трогаем schemas.py, messaging.py, pytest.ini и чужие файлы.
- НЕ добавляем поля в модели SQLAlchemy.

ЭТОТ МОДУЛЬ НИЧЕГО НЕ СОХРАНЯЕТ. Он только считает и возвращает план.
Запись в БД делает вызывающий слой (вебхук / планировщик / скрипт).
Ниже в docstring — карта: какой результат в какие таблицы и поля писать.

--------------------------------------------------------------------
КАРТА ЗАПИСИ В БД (таблицы и поля)

1. build_week_slots()  ->  таблица poll_slots (ПЕРЕЗАПИСЬ при создании
   нового еженедельного опроса):
     poll_id           = id созданного weekly_polls
     slot_start        = slot.start          (UTC, TIMESTAMPTZ)
     slot_end          = slot.end            (UTC, TIMESTAMPTZ)
     location          = slot.location       (из config.default_location)
     priority          = 0
     votes_count       = 0 (свежие слоты — перезапись, старые голоса сброшены)
   ПЕРЕЗАПИСЬ: при создании нового опроса на неделю СНАЧАЛА удалить
   старые poll_slots + poll_votes + poll_responses этого poll_id,
   потом вставить свежие слоты из build_week_slots().

2. record_votes (вызывающий слой)  ->  таблицы:
   poll_responses:
     profile_id, poll_id, status='responded', responded_at=now
   poll_votes (по одному на выбранный день):
     poll_response_id, profile_id, poll_slot_id, voted_at=now
   answers (ответы на тематические вопросы, по одному на вопрос):
     profile_id, question_text, answer_text, week_start, is_public
   Триггеры БД сами пересчитают poll_slots.votes_count.

3. aggregate_votes()  ->  вход для принятия решения (чистая агрегация,
   вызывающий слой получает те же данные из poll_votes JOIN poll_slots).

4. decide_for_tomorrow() / pick_next_meeting()  ->  Decision:
   - kind='MEETING'      ->  создать meeting_instances:
        poll_id, selected_slot_id (=slot.slot_key -> poll_slots.id),
        scheduled_start=slot.start, scheduled_end=slot.end,
        location, status='scheduled',
        activity_type (по ответам на темы, правило позже)
        И weekly_polls: status='closed', closed_at=now.
   - kind='NEED_MORE_VOTES' ->  эскалация: DM организатору
        (текст escalation_text). weekly_polls остаётся 'active'.
   - kind='WEEK_CANCELLED'  ->  эскалация: DM организатору
        (текст week_cancelled_text). weekly_polls: status='cancelled'.

5. plan_week_messages()  ->  очередь сообщений ТОЛЬКО после фиксации:
   сообщения появляются, лишь когда kind='MEETING' (см. п.4).
   ANNOUNCEMENT: отправить всем проголосовавшим за день встречи
     (профили из poll_votes того дня) — за день до встречи в announcement_hour.
   REMINDER: отправить тем же адресатам за reminder_hours до slot.start.
   Хранить/исполнять очередь может планировщик (send_at — когда слать).
--------------------------------------------------------------------
"""
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

# Пояс встреч и напоминаний. Должен совпадать с config.app_tz
# (по умолчанию Europe/Moscow). Чистый модуль config не читает — фиксируем здесь.
APP_TZ = ZoneInfo("Europe/Moscow")

DEFAULT_START_HOUR = 13
DEFAULT_START_MINUTE = 0
DEFAULT_SLOT_MINUTES = 60
DEFAULT_DAYS_IN_WEEK = 7  # Пн..Вс
DEFAULT_ANNOUNCEMENT_HOUR = 20  # анонс «за день до» — вечером предыдущего дня
DEFAULT_REMINDER_HOURS = 1      # напоминание за 1 час (config meeting_reminder_hours)

# Русские названия дней недели: 0=понедельник ... 6=воскресенье
RU_DAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")

# Возможные исходы решения
MEETING = "MEETING"
NEED_MORE_VOTES = "NEED_MORE_VOTES"
WEEK_CANCELLED = "WEEK_CANCELLED"


# ---------------------------------------------------------------------
# Простые структуры данных (НЕ модели SQLAlchemy, ничего не сохраняют)
# ---------------------------------------------------------------------

@dataclass(frozen=True)
class Slot:
    """Один слот (день+время). slot_key — стабильный ключ, по нему
    вызывающий слой находит poll_slots.id при записи."""
    slot_key: str
    day: date
    start: datetime
    end: datetime
    votes: int = 0
    location: str = ""


@dataclass(frozen=True)
class VoteRecord:
    """Один голос: профиль проголосовал за слот."""
    slot_key: str
    profile_key: str


@dataclass(frozen=True)
class DayVotes:
    """Итоги голосования по одному дню."""
    day: date
    voters: int            # число РАЗНЫХ профилей, проголосовавших за этот день
    slots: tuple[Slot, ...]  # слоты этого дня с подсчитанными голосами


@dataclass(frozen=True)
class MeetingPlan:
    """Готовая к записи встреча (из выигравшего дня и слота)."""
    day: date
    slot: Slot


@dataclass(frozen=True)
class MessagePlan:
    """Одно сообщение из очереди после фиксации."""
    kind: Literal["ANNOUNCEMENT", "REMINDER"]
    send_at: datetime
    text: str
    recipients: tuple[str, ...]  # workspace_user_id получателей


@dataclass(frozen=True)
class Decision:
    """Результат принятия решения по дню/неделе."""
    kind: Literal["MEETING", "NEED_MORE_VOTES", "WEEK_CANCELLED"]
    meeting: MeetingPlan | None = None
    day: date | None = None
    voters: int = 0
    quorum: int = 0
    reason: str = ""


# ---------------------------------------------------------------------
# Неделя и слоты (перезапись при создании нового еженедельного опроса)
# ---------------------------------------------------------------------

def week_start_for(today: date) -> date:
    """Понедельник недели, в которую входит today."""
    return today - timedelta(days=today.weekday())


def week_dates(week_start: date, days_count: int = DEFAULT_DAYS_IN_WEEK) -> list[date]:
    """Даты Пн..Вс недели."""
    return [week_start + timedelta(days=i) for i in range(days_count)]


def build_week_slots(
    week_start: date,
    times: list[tuple[int, int]] | None = None,
    slot_minutes: int = DEFAULT_SLOT_MINUTES,
    days_count: int = DEFAULT_DAYS_IN_WEEK,
    location: str = "",
) -> list[Slot]:
    """Свежий план слотов на неделю (все votes=0).

    По умолчанию один слот в день в 13:00 по APP_TZ (время пока фиксированное).
    Передача times=[(12,0),(13,0),...] включит несколько времён на день.

    ПЕРЕЗАПИСЬ: при создании нового weekly_polls вызывающий слой
    удаляет старые poll_slots/poll_votes/poll_responses этой недели
    и вставляет слоты из этой функции (см. карту в docstring модуля).
    """
    if times is None:
        times = [(DEFAULT_START_HOUR, DEFAULT_START_MINUTE)]
    slots: list[Slot] = []
    for day in week_dates(week_start, days_count):
        for hour, minute in times:
            start = datetime(day.year, day.month, day.day, hour, minute, tzinfo=APP_TZ)
            end = start + timedelta(minutes=slot_minutes)
            key = f"{day.isoformat()}T{hour:02d}{minute:02d}"
            slots.append(Slot(slot_key=key, day=day, start=start, end=end, votes=0, location=location))
    return slots


# ---------------------------------------------------------------------
# Агрегация голосов
# ---------------------------------------------------------------------

def aggregate_votes(vote_records: list[VoteRecord], slots: list[Slot]) -> list[DayVotes]:
    """Посчитать число разных проголосовавших по дням и голоса по слотам.

    Вызывающий слой строит vote_records из poll_votes (profile_id,
    poll_slot_id) и slots из poll_slots (с location/time), либо передаёт
    готовые счётчики из votes_count.
    """
    slot_by_key = {s.slot_key: s for s in slots}
    day_profiles: dict[date, set[str]] = {}
    slot_votes: dict[str, int] = {}
    for rec in vote_records:
        slot = slot_by_key.get(rec.slot_key)
        if slot is None:
            continue
        day_profiles.setdefault(slot.day, set()).add(rec.profile_key)
        slot_votes[rec.slot_key] = slot_votes.get(rec.slot_key, 0) + 1

    result: list[DayVotes] = []
    for day in sorted(day_profiles):
        day_slots = tuple(
            Slot(
                slot_key=s.slot_key,
                day=s.day,
                start=s.start,
                end=s.end,
                votes=slot_votes.get(s.slot_key, 0),
                location=s.location,
            )
            for s in slots
            if s.day == day
        )
        result.append(DayVotes(day=day, voters=len(day_profiles[day]), slots=day_slots))
    return result


# ---------------------------------------------------------------------
# Выбор слота: максимум голосов, ничья -> более ранний
# ---------------------------------------------------------------------

def pick_slot_by_max_votes(slots: list[Slot]) -> Slot | None:
    """Слот с максимумом голосов; при равенстве — тот, что начинается раньше."""
    if not slots:
        return None
    return max(slots, key=lambda s: (s.votes, -s.start.timestamp()))


# ---------------------------------------------------------------------
# Кворум
# ---------------------------------------------------------------------

def check_quorum(voter_count: int, quorum: int) -> bool:
    """Кворум набран, если проголосовавших не меньше порога."""
    return voter_count >= quorum


# ---------------------------------------------------------------------
# Принятие решения
# ---------------------------------------------------------------------

def decide_for_tomorrow(day: DayVotes | None, quorum: int) -> Decision:
    """Решение по конкретному дню (ежедневная проверка «на завтра»).

    - день с кворумом            -> MEETING (фиксируем, слот по максимуму голосов)
    - день есть, но кворум мал    -> NEED_MORE_VOTES (эскалация, ждём)
    - день ещё без голосов        -> NEED_MORE_VOTES (ждём голосов)
    """
    if day is None or day.voters == 0:
        return Decision(
            kind=NEED_MORE_VOTES,
            day=day.day if day else None,
            voters=day.voters if day else 0,
            quorum=quorum,
            reason="no_votes_yet",
        )
    if check_quorum(day.voters, quorum):
        slot = pick_slot_by_max_votes(list(day.slots))
        return Decision(
            kind=MEETING,
            meeting=MeetingPlan(day=day.day, slot=slot),
            day=day.day,
            voters=day.voters,
            quorum=quorum,
            reason="quorum_reached",
        )
    return Decision(
        kind=NEED_MORE_VOTES,
        day=day.day,
        voters=day.voters,
        quorum=quorum,
        reason="below_quorum",
    )


def pick_next_meeting(days: list[DayVotes], quorum: int) -> Decision:
    """Полный проход по неделе: берём САМЫЙ РАННИЙ день, набравший кворум.

    Если ни один день не набрал кворум за неделю -> WEEK_CANCELLED.
    Ничья «два дня поровну» автоматически решается в пользу более раннего
    дня, т.к. идём по датам по порядку и останавливаемся на первом.
    """
    for day in sorted(days, key=lambda d: d.day):
        if check_quorum(day.voters, quorum):
            slot = pick_slot_by_max_votes(list(day.slots))
            return Decision(
                kind=MEETING,
                meeting=MeetingPlan(day=day.day, slot=slot),
                day=day.day,
                voters=day.voters,
                quorum=quorum,
                reason="earliest_quorum_day",
            )
    return Decision(
        kind=WEEK_CANCELLED,
        voters=0,
        quorum=quorum,
        reason="no_day_reached_quorum",
    )


# ---------------------------------------------------------------------
# Тексты уведомлений (эскалация / отмена недели)
# ---------------------------------------------------------------------

def _day_name(d: date) -> str:
    return RU_DAYS[d.weekday()]


def escalation_text(day: date | None, voters: int, quorum: int) -> str:
    """Текст DM организатору: на ближайший день не хватает голосов."""
    if day is None:
        return (
            f"Пока никто не проголосовал за ближайший день. "
            f"Нужно минимум {quorum} участника. Ждём голоса."
        )
    return (
        f"На {_day_name(day)} ({day.isoformat()}) пока {voters} из {quorum} "
        f"необходимых участников. Кворум не набран — встреча НЕ фиксируется. "
        f"Ждём голоса за этот или более поздние дни."
    )


def week_cancelled_text(quorum: int) -> str:
    """Текст DM организатору: за неделю ни один день не набрал кворум."""
    return (
        f"За неделю ни один день не набрал {quorum} участников. "
        f"Встреча на этой неделе отменяется. "
        f"Попробуем на следующей неделе."
    )


# ---------------------------------------------------------------------
# Очередь сообщений ТОЛЬКО после фиксации (kind='MEETING')
# ---------------------------------------------------------------------

def plan_week_messages(
    meeting: MeetingPlan,
    recipients: list[str],
    announcement_hour: int = DEFAULT_ANNOUNCEMENT_HOUR,
    reminder_hours: int = DEFAULT_REMINDER_HOURS,
) -> list[MessagePlan]:
    """Сообщения, которые появляются ТОЛЬКО после фиксации встречи.

    - ANNOUNCEMENT: «завтра встреча» — за день до дня встречи, в
      announcement_hour (вечер предыдущего дня).
    - REMINDER: «скоро встреча» — за reminder_hours до slot.start.

    Никаких сообщений до фиксации этот модуль не планирует.
    """
    if not recipients:
        return []
    announce_at = datetime.combine(
        meeting.day - timedelta(days=1),
        dtime(announcement_hour, 0),
        tzinfo=timezone.utc,
    )
    reminder_at = meeting.slot.start - timedelta(hours=reminder_hours)

    day_label = _day_name(meeting.day)
    start_local = meeting.slot.start.astimezone(APP_TZ)
    end_local = meeting.slot.end.astimezone(APP_TZ)
    time_label = f"{start_local:%H:%M}–{end_local:%H:%M}"
    location = meeting.slot.location or "место уточним позже"

    return [
        MessagePlan(
            kind="ANNOUNCEMENT",
            send_at=announce_at,
            text=(
                f"📢 Завтра встреча по английскому!\n"
                f"День: {day_label} ({meeting.day.isoformat()})\n"
                f"Время: {time_label}\n"
                f"Место: {location}"
            ),
            recipients=tuple(recipients),
        ),
        MessagePlan(
            kind="REMINDER",
            send_at=reminder_at,
            text=(
                f"⏰ Напоминание: встреча по английскому через {reminder_hours} ч.\n"
                f"{day_label} {time_label}, {location}. Ждём тебя!"
            ),
            recipients=tuple(recipients),
        ),
    ]