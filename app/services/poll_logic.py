# app/services/poll_logic.py
"""Чистая логика ежедневного голосования «в тот же день».

ОГРАНИЧЕНИЯ (по требованию команды):
- НЕ вызываем сеть, БД и asyncio — только чистые функции над простыми данными.
- НЕ трогаем schemas.py, messaging.py, pytest.ini и чужие файлы.
- НЕ добавляем поля в модели SQLAlchemy.

ЭТОТ МОДУЛЬ НИЧЕГО НЕ СОХРАНЯЕТ. Он только считает и возвращает план.
Запись в БД делает вызывающий слой (вебхук / планировщик / скрипт).

--------------------------------------------------------------------
КАРТА ЗАПИСИ В БД (таблицы и поля)

Схема дневная: «опрос» = один день (в weekly_polls week_start = дата дня,
voting_deadline = 13:00 того же дня). Слоты фиксированные: 15–16, 16–17, 17–18.

1. build_daily_slots(day, location)  ->  poll_slots (ПЕРЕЗАПИСЬ при создании
   опроса дня):
     poll_id        = id созданного weekly_polls
     slot_start     = slot.start          (UTC, TIMESTAMPTZ)
     slot_end       = slot.end            (UTC, TIMESTAMPTZ)
     location       = slot.location       (из config.default_location)
     priority       = 0
     votes_count    = 0 (свежие слоты)

2. save_attendance_response (вызывающий слой)  ->  poll_responses:
     profile_id, poll_id, status='responded', responded_at=now,
     will_attend=True/False.  «Нет» -> голосов нет.

3. save_time_vote (вызывающий слой)  ->  poll_votes (ПЕРЕЗАПИСЬ голоса
   участника в этом опросе):
     poll_response_id, profile_id, poll_slot_id, voted_at=now.
     Триггер БД пересчитает poll_slots.votes_count.

4. finalize_slots(slots, quorum)  ->  список MeetingPlan (слоты с голосами
   >= quorum). Вызывающий слой создаёт meeting_instances на каждый такой
   слот и закрывает опрос (weekly_polls.status='closed').

5. plan_meeting_messages(meeting, recipients)  ->  только REMINDER
   (за meeting_reminder_hours до slot.start). Анонс в группу строится
   отдельно через build_announcement_text и шлётся сразу при финализации.
--------------------------------------------------------------------
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

# Пояс встреч и напоминаний. Должен совпадать с config.app_tz
# (по умолчанию Europe/Moscow). Чистый модуль config не читает — фиксируем здесь.
APP_TZ = ZoneInfo("Europe/Moscow")

# Фиксированные слоты дня: (час, минута) старта. Длительность 60 минут.
DAILY_SLOTS: tuple[tuple[int, int], ...] = ((15, 0), (16, 0), (17, 0))
DAILY_SLOT_MINUTES = 60
DAILY_QUORUM_DEFAULT = 4
DEFAULT_REMINDER_HOURS = 1  # напоминание за 1 час (config meeting_reminder_hours)


# ---------------------------------------------------------------------
# Простые структуры данных (НЕ модели SQLAlchemy, ничего не сохраняют)
# ---------------------------------------------------------------------

@dataclass(frozen=True)
class Slot:
    """Один слот времени встречи (день+время). slot_key — стабильный ключ,
    по нему вызывающий слой находит poll_slots.id при записи."""
    slot_key: str
    day: date
    start: datetime
    end: datetime
    votes: int = 0
    location: str = ""


@dataclass(frozen=True)
class MeetingPlan:
    """Готовая к записи встреча (слот, набравший кворум)."""
    day: date
    slot: Slot


@dataclass(frozen=True)
class MessagePlan:
    """Одно сообщение из очереди после финализации встречи."""
    kind: Literal["ANNOUNCEMENT", "REMINDER"]
    send_at: datetime
    text: str
    recipients: tuple[str, ...]  # workspace_user_id получателей


# ---------------------------------------------------------------------
# Слоты дня
# ---------------------------------------------------------------------

def build_daily_slots(day: date, location: str = "") -> list[Slot]:
    """Свежий план слотов на день (15–16, 16–17, 17–18 по APP_TZ), votes=0.

    ПЕРЕЗАПИСЬ: при создании нового опроса дня вызывающий слой удаляет
    старые poll_slots/poll_votes/poll_responses этого poll_id и вставляет
    слоты из этой функции.
    """
    slots: list[Slot] = []
    for hour, minute in DAILY_SLOTS:
        start = datetime(day.year, day.month, day.day, hour, minute, tzinfo=APP_TZ)
        end = start + timedelta(minutes=DAILY_SLOT_MINUTES)
        key = f"{day.isoformat()}T{hour:02d}{minute:02d}"
        slots.append(
            Slot(slot_key=key, day=day, start=start, end=end, votes=0, location=location)
        )
    return slots


# ---------------------------------------------------------------------
# Финализация: все слоты, набравшие кворум, дают по встрече (до 3 групп)
# ---------------------------------------------------------------------

def check_quorum(votes: int, quorum: int) -> bool:
    """Кворум набран, если голосов не меньше порога."""
    return votes >= quorum


def finalize_slots(slots: list[Slot], quorum: int) -> list[MeetingPlan]:
    """Слоты с голосами >= quorum -> встречи, по одной на слот (по времени).

    Ни один слот не набрал кворум -> пустой список (вызывающий слой молчит).
    """
    winners = [s for s in slots if check_quorum(s.votes, quorum)]
    winners.sort(key=lambda s: s.start)
    return [MeetingPlan(day=s.day, slot=s) for s in winners]


# ---------------------------------------------------------------------
# Тексты уведомлений
# ---------------------------------------------------------------------

def time_label(slot: Slot) -> str:
    """'15:00–16:00' по таймзоне бота."""
    start_local = slot.start.astimezone(APP_TZ)
    end_local = slot.end.astimezone(APP_TZ)
    return f"{start_local:%H:%M}–{end_local:%H:%M}"


def build_announcement_text(meeting: MeetingPlan, activity: str = "") -> str:
    """Анонс встречи в общую группу (сразу при финализации).

    activity — строка «активность + тема», которую готовит Кирилл (activity.py).
    Пустая -> «активность и тема уточняются».
    """
    slot = meeting.slot
    location = slot.location or "место уточним позже"
    activity_line = activity.strip() if activity else "Активность и тема уточняются"
    return (
        f"📢 Сегодня встреча по английскому!\n"
        f"🕐 {time_label(slot)}\n"
        f"📍 {location}\n"
        f"🎯 {activity_line}"
    )


def build_reminder_text(meeting: MeetingPlan, reminder_hours: int) -> str:
    """Напоминание участнику за reminder_hours до начала."""
    slot = meeting.slot
    location = slot.location or "место уточним позже"
    return (
        f"⏰ Напоминание: встреча по английскому через {reminder_hours} ч.\n"
        f"{time_label(slot)}, {location}. Ждём тебя!"
    )


def build_checkin_text(meeting: MeetingPlan) -> str:
    """Вопрос чек-ина в конце дня (заголовок карточки)."""
    return f"Ты был(а) сегодня на встрече по английскому {time_label(meeting.slot)}?"


# ---------------------------------------------------------------------
# Очередь сообщений после финализации (только напоминание)
# ---------------------------------------------------------------------

def plan_meeting_messages(
    meeting: MeetingPlan,
    recipients: list[str],
    reminder_hours: int = DEFAULT_REMINDER_HOURS,
) -> list[MessagePlan]:
    """Сообщения после финализации встречи.

    Анонс в группу строится отдельно (build_announcement_text) и шлётся сразу,
    поэтому здесь планируется только REMINDER — за reminder_hours до slot.start.
    """
    if not recipients:
        return []
    reminder_at = meeting.slot.start - timedelta(hours=reminder_hours)
    return [
        MessagePlan(
            kind="REMINDER",
            send_at=reminder_at,
            text=build_reminder_text(meeting, reminder_hours),
            recipients=tuple(recipients),
        )
    ]
