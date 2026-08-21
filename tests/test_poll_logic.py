# tests/test_poll_logic.py
"""Тесты чистой логики недельного голосования (без БД, сети, asyncio).

Запуск: .\\venv\\Scripts\\python -m pytest
или:   py -m pytest
"""
from datetime import date, datetime, timedelta, timezone

import pytest

from app.services.poll_logic import (
    MEETING,
    NEED_MORE_VOTES,
    WEEK_CANCELLED,
    Decision,
    DayVotes,
    MessagePlan,
    MeetingPlan,
    Slot,
    VoteRecord,
    aggregate_votes,
    build_week_slots,
    check_quorum,
    decide_for_tomorrow,
    escalation_text,
    pick_next_meeting,
    pick_slot_by_max_votes,
    plan_week_messages,
    week_cancelled_text,
    week_dates,
    week_start_for,
)
from app.services.poll_card import TIME_LABEL, build_poll_card


# ---------------------------------------------------------------------
# Неделя и слоты
# ---------------------------------------------------------------------

def test_week_start_for_returns_monday():
    # 2026-08-20 — четверг
    assert week_start_for(date(2026, 8, 20)) == date(2026, 8, 17)


def test_week_start_for_monday_itself():
    assert week_start_for(date(2026, 8, 17)) == date(2026, 8, 17)


def test_week_dates_seven_days():
    dates = week_dates(date(2026, 8, 17))
    assert len(dates) == 7
    assert dates[0] == date(2026, 8, 17)  # Пн
    assert dates[6] == date(2026, 8, 23)  # Вс


def test_build_week_slots_default_one_per_day_at_13():
    slots = build_week_slots(date(2026, 8, 17))
    assert len(slots) == 7
    for slot in slots:
        assert slot.start.hour == 13
        assert slot.start.minute == 0
        assert (slot.end - slot.start).total_seconds() == 3600
        assert slot.votes == 0
        assert slot.start.utcoffset() == timedelta(hours=3)  # Москва (UTC+3)


def test_build_week_slots_keys_and_days():
    slots = build_week_slots(date(2026, 8, 17))
    assert slots[0].day == date(2026, 8, 17)
    assert slots[6].day == date(2026, 8, 23)
    keys = {s.slot_key for s in slots}
    assert len(keys) == 7
    assert "2026-08-17T1300" in keys


def test_build_week_slots_multiple_times():
    slots = build_week_slots(date(2026, 8, 17), times=[(12, 0), (13, 0)])
    assert len(slots) == 14  # 7 дней x 2 времени
    hours = sorted(s.start.hour for s in slots if s.day == date(2026, 8, 17))
    assert hours == [12, 13]


def test_build_week_slots_custom_location():
    slots = build_week_slots(date(2026, 8, 17), location="Conference Room A")
    assert all(s.location == "Conference Room A" for s in slots)


# ---------------------------------------------------------------------
# Выбор слота: максимум голосов, ничья -> раньше
# ---------------------------------------------------------------------

def _mk_slot(day, hour, votes):
    start = datetime(day.year, day.month, day.day, hour, 0, tzinfo=timezone.utc)
    return Slot(
        slot_key=f"{day.isoformat()}T{hour:02d}00",
        day=day,
        start=start,
        end=start,
        votes=votes,
    )


def test_pick_slot_by_max_votes_simple():
    day = date(2026, 8, 18)
    slots = [_mk_slot(day, 13, 1), _mk_slot(day, 14, 5), _mk_slot(day, 15, 2)]
    assert pick_slot_by_max_votes(slots).start.hour == 14


def test_pick_slot_by_max_votes_tie_prefers_earlier():
    day = date(2026, 8, 18)
    slots = [_mk_slot(day, 14, 4), _mk_slot(day, 13, 4)]
    assert pick_slot_by_max_votes(slots).start.hour == 13


def test_pick_slot_by_max_votes_empty():
    assert pick_slot_by_max_votes([]) is None


def test_pick_slot_by_max_votes_tie_across_days():
    # равные голоса за два дня -> более ранний день
    slots = [_mk_slot(date(2026, 8, 20), 13, 3), _mk_slot(date(2026, 8, 18), 13, 3)]
    assert pick_slot_by_max_votes(slots).day == date(2026, 8, 18)


# ---------------------------------------------------------------------
# Кворум
# ---------------------------------------------------------------------

def test_check_quorum_boundaries():
    assert check_quorum(3, 3) is True
    assert check_quorum(5, 3) is True
    assert check_quorum(2, 3) is False
    assert check_quorum(0, 3) is False


# ---------------------------------------------------------------------
# Агрегация голосов
# ---------------------------------------------------------------------

def test_aggregate_votes_distinct_voters_per_day():
    slots = build_week_slots(date(2026, 8, 17))
    votes = [
        VoteRecord("2026-08-17T1300", "u1"),
        VoteRecord("2026-08-17T1300", "u2"),
        VoteRecord("2026-08-18T1300", "u1"),  # u1 голосует и за вторник тоже
        VoteRecord("2026-08-18T1300", "u3"),
    ]
    days = aggregate_votes(votes, slots)
    by_day = {d.day: d for d in days}
    assert by_day[date(2026, 8, 17)].voters == 2  # u1, u2
    assert by_day[date(2026, 8, 18)].voters == 2  # u1, u3
    # голоса по слотам
    mon_slot = by_day[date(2026, 8, 17)].slots[0]
    assert mon_slot.votes == 2


def test_aggregate_votes_ignores_unknown_slot():
    slots = build_week_slots(date(2026, 8, 17))
    votes = [VoteRecord("9999-01-01T1300", "u1")]
    assert aggregate_votes(votes, slots) == []


# ---------------------------------------------------------------------
# Решение по дню («на завтра»)
# ---------------------------------------------------------------------

def test_decide_for_tomorrow_no_votes():
    d = decide_for_tomorrow(None, quorum=3)
    assert d.kind == NEED_MORE_VOTES
    assert d.reason == "no_votes_yet"


def test_decide_for_tomorrow_below_quorum():
    day = DayVotes(day=date(2026, 8, 18), voters=2, slots=())
    d = decide_for_tomorrow(day, quorum=3)
    assert d.kind == NEED_MORE_VOTES
    assert d.reason == "below_quorum"
    assert d.voters == 2
    assert d.meeting is None


def test_decide_for_tomorrow_reaches_quorum():
    day = date(2026, 8, 18)
    slots = (_mk_slot(day, 14, 1), _mk_slot(day, 13, 3))
    day_votes = DayVotes(day=day, voters=3, slots=slots)
    d = decide_for_tomorrow(day_votes, quorum=3)
    assert d.kind == MEETING
    assert d.meeting.day == day
    assert d.meeting.slot.start.hour == 13  # максимум голосов
    assert d.reason == "quorum_reached"


# ---------------------------------------------------------------------
# Полный проход по неделе
# ---------------------------------------------------------------------

def test_pick_next_meeting_earliest_quorum_day_wins():
    # вторник и четверг оба набрали кворум -> выбирается вторник (раньше)
    tue = DayVotes(day=date(2026, 8, 18), voters=3, slots=(_mk_slot(date(2026, 8, 18), 13, 3),))
    thu = DayVotes(day=date(2026, 8, 20), voters=5, slots=(_mk_slot(date(2026, 8, 20), 13, 5),))
    d = pick_next_meeting([thu, tue], quorum=3)  # порядок на входе не важен
    assert d.kind == MEETING
    assert d.meeting.day == date(2026, 8, 18)
    assert d.reason == "earliest_quorum_day"


def test_pick_next_meeting_only_later_day_has_quorum():
    # понедельник не набрал кворум, среда набрала -> встреча в среду
    mon = DayVotes(day=date(2026, 8, 17), voters=2, slots=(_mk_slot(date(2026, 8, 17), 13, 2),))
    wed = DayVotes(day=date(2026, 8, 19), voters=4, slots=(_mk_slot(date(2026, 8, 19), 13, 4),))
    d = pick_next_meeting([wed, mon], quorum=3)
    assert d.kind == MEETING
    assert d.meeting.day == date(2026, 8, 19)


def test_pick_next_meeting_no_quorum_all_week():
    days = [
        DayVotes(day=date(2026, 8, 17), voters=2, slots=(_mk_slot(date(2026, 8, 17), 13, 2),)),
        DayVotes(day=date(2026, 8, 18), voters=2, slots=(_mk_slot(date(2026, 8, 18), 13, 2),)),
    ]
    d = pick_next_meeting(days, quorum=3)
    assert d.kind == WEEK_CANCELLED
    assert d.reason == "no_day_reached_quorum"
    assert d.meeting is None


def test_pick_next_meeting_empty_week():
    d = pick_next_meeting([], quorum=3)
    assert d.kind == WEEK_CANCELLED


# ---------------------------------------------------------------------
# Тексты эскалации
# ---------------------------------------------------------------------

def test_escalation_text_mentions_counts():
    text = escalation_text(date(2026, 8, 18), voters=1, quorum=3)
    assert "1" in text and "3" in text
    assert "не фиксируется" in text.lower()


def test_escalation_text_no_day():
    assert "Ждём голоса" in escalation_text(None, 0, 3)


def test_week_cancelled_text():
    assert "3" in week_cancelled_text(3)
    assert "отменяется" in week_cancelled_text(3)


# ---------------------------------------------------------------------
# Очередь сообщений ТОЛЬКО после фиксации
# ---------------------------------------------------------------------

def test_plan_week_messages_only_after_meeting():
    day = date(2026, 8, 18)  # вторник
    slot = _mk_slot(day, 13, 3)
    meeting = MeetingPlan(day=day, slot=slot)
    msgs = plan_week_messages(meeting, recipients=["u1", "u2"], reminder_hours=1)

    assert len(msgs) == 2
    kinds = [m.kind for m in msgs]
    assert "ANNOUNCEMENT" in kinds and "REMINDER" in kinds

    ann = next(m for m in msgs if m.kind == "ANNOUNCEMENT")
    assert ann.send_at.date() == date(2026, 8, 17)  # за день до встречи
    assert ann.send_at.hour == 20
    assert "Завтра" in ann.text
    assert ann.recipients == ("u1", "u2")

    rem = next(m for m in msgs if m.kind == "REMINDER")
    assert rem.send_at == slot.start - timedelta(hours=1)
    assert "Напоминание" in rem.text


def test_plan_week_messages_empty_recipients():
    meeting = MeetingPlan(day=date(2026, 8, 18), slot=_mk_slot(date(2026, 8, 18), 13, 3))
    assert plan_week_messages(meeting, recipients=[]) == []


def test_plan_week_messages_custom_hours():
    day = date(2026, 8, 18)
    meeting = MeetingPlan(day=day, slot=_mk_slot(day, 13, 3))
    msgs = plan_week_messages(meeting, ["u1"], announcement_hour=9, reminder_hours=2)
    ann = next(m for m in msgs if m.kind == "ANNOUNCEMENT")
    rem = next(m for m in msgs if m.kind == "REMINDER")
    assert ann.send_at.hour == 9
    assert rem.send_at == _mk_slot(day, 13, 3).start - timedelta(hours=2)


# ---------------------------------------------------------------------
# Карточка
# ---------------------------------------------------------------------

def _card_sections():
    card = build_poll_card(week_start=date(2026, 8, 17), user_name="Тест")
    return card["cardsV2"][0]["card"]["sections"]


def _all_widgets(sections):
    widgets = []
    for s in sections:
        widgets.extend(s.get("widgets", []))
    return widgets


def test_card_has_seven_days():
    widgets = _all_widgets(_card_sections())
    sel = next(w for w in widgets if "selectionInput" in w)["selectionInput"]
    assert sel["name"] == "days"
    assert sel["type"] == "CHECK_BOX"
    assert len(sel["items"]) == 7
    assert sel["items"][0]["value"] == "2026-08-17"  # Пн
    assert sel["items"][6]["value"] == "2026-08-23"  # Вс


def test_card_min_day_filters_past_days():
    # неделя с Пн 2026-08-17; среда 19.08 -> показываем только Ср..Вс
    card = build_poll_card(
        week_start=date(2026, 8, 17), user_name="Тест", min_day=date(2026, 8, 19)
    )
    widgets = _all_widgets(card["cardsV2"][0]["card"]["sections"])
    sel = next(w for w in widgets if "selectionInput" in w)["selectionInput"]
    values = [it["value"] for it in sel["items"]]
    assert values == [
        "2026-08-19",
        "2026-08-20",
        "2026-08-21",
        "2026-08-22",
        "2026-08-23",
    ]
    assert len(values) == 5


def test_card_fixed_time_13():
    sections = _card_sections()
    time_section = next(s for s in sections if s.get("header") == "2. Время")
    text = time_section["widgets"][0]["textParagraph"]["text"]
    assert TIME_LABEL in text
    assert "13:00" in text


def test_card_submit_button_method():
    widgets = _all_widgets(_card_sections())
    btn = next(w for w in widgets if "buttonList" in w)["buttonList"]["buttons"][0]
    assert btn["text"] == "Забронировать день 🚀"
    params = btn["onClick"]["action"]["parameters"]
    assert {"key": "method", "value": "submit_poll_vote"} in params


def test_card_has_no_theme_questions():
    # темы подбирает ИИ — текстовых полей в карточке больше нет
    widgets = _all_widgets(_card_sections())
    text_inputs = [w for w in widgets if "textInput" in w]
    assert text_inputs == []


def test_card_mentions_quorum():
    sections = _card_sections()
    intro = sections[0]["widgets"][0]["textParagraph"]["text"]
    assert "минимум 3" in intro