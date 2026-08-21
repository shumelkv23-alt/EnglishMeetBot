# tests/test_poll_logic.py
"""Тесты чистой логики ежедневного голосования (без БД, сети, asyncio).

Запуск: .\\venv\\Scripts\\python -m pytest
или:   py -m pytest
"""
from datetime import date, datetime, timedelta, timezone

import pytest

from app.services.poll_logic import (
    APP_TZ,
    DAILY_QUORUM_DEFAULT,
    DEFAULT_REMINDER_HOURS,
    MeetingPlan,
    MessagePlan,
    Slot,
    build_announcement_text,
    build_checkin_text,
    build_daily_slots,
    build_reminder_text,
    check_quorum,
    finalize_slots,
    plan_meeting_messages,
    time_label,
)
from app.services.poll_card import (
    METHOD_ATTENDANCE_YES,
    METHOD_ATTENDANCE_NO,
    METHOD_CHECKIN_YES,
    METHOD_CHECKIN_NO,
    METHOD_SUBMIT_TIME,
    build_attendance_card,
    build_checkin_card,
    build_time_card,
)


# ---------------------------------------------------------------------
# Слоты дня
# ---------------------------------------------------------------------

def test_build_daily_slots_three_slots():
    slots = build_daily_slots(date(2026, 8, 21))
    assert len(slots) == 3
    assert [s.start.hour for s in slots] == [15, 16, 17]
    for slot in slots:
        assert slot.start.minute == 0
        assert (slot.end - slot.start).total_seconds() == 3600
        assert slot.votes == 0
        assert slot.start.utcoffset() == timedelta(hours=3)  # Москва (UTC+3)


def test_build_daily_slots_keys():
    slots = build_daily_slots(date(2026, 8, 21))
    keys = {s.slot_key for s in slots}
    assert keys == {
        "2026-08-21T1500",
        "2026-08-21T1600",
        "2026-08-21T1700",
    }


def test_build_daily_slots_custom_location():
    slots = build_daily_slots(date(2026, 8, 21), location="Conference Room A")
    assert all(s.location == "Conference Room A" for s in slots)


# ---------------------------------------------------------------------
# Кворум
# ---------------------------------------------------------------------

def test_check_quorum_boundaries():
    assert check_quorum(4, 4) is True
    assert check_quorum(5, 4) is True
    assert check_quorum(3, 4) is False
    assert check_quorum(0, 4) is False


def test_default_quorum_is_four():
    assert DAILY_QUORUM_DEFAULT == 4


# ---------------------------------------------------------------------
# Финализация: слоты с кворумом -> встречи (до 3 групп)
# ---------------------------------------------------------------------

def _mk_slot(day, hour, votes):
    start = datetime(day.year, day.month, day.day, hour, 0, tzinfo=APP_TZ)
    return Slot(
        slot_key=f"{day.isoformat()}T{hour:02d}00",
        day=day,
        start=start,
        end=start + timedelta(hours=1),
        votes=votes,
        location="Conference Room A",
    )


def test_finalize_slots_single_winner():
    day = date(2026, 8, 21)
    slots = [_mk_slot(day, 15, 4), _mk_slot(day, 16, 3), _mk_slot(day, 17, 2)]
    meetings = finalize_slots(slots, quorum=4)
    assert len(meetings) == 1
    assert meetings[0].slot.start.hour == 15


def test_finalize_slots_multiple_groups():
    # два слота набрали кворум -> две встречи, по времени
    day = date(2026, 8, 21)
    slots = [_mk_slot(day, 17, 5), _mk_slot(day, 15, 4), _mk_slot(day, 16, 1)]
    meetings = finalize_slots(slots, quorum=4)
    assert [m.slot.start.hour for m in meetings] == [15, 17]


def test_finalize_slots_no_quorum():
    day = date(2026, 8, 21)
    slots = [_mk_slot(day, 15, 3), _mk_slot(day, 16, 2), _mk_slot(day, 17, 1)]
    assert finalize_slots(slots, quorum=4) == []


def test_finalize_slots_empty():
    assert finalize_slots([], quorum=4) == []


# ---------------------------------------------------------------------
# Тексты уведомлений
# ---------------------------------------------------------------------

def test_time_label():
    slot = _mk_slot(date(2026, 8, 21), 15, 4)
    assert time_label(slot) == "15:00–16:00"


def test_announcement_text_contains_time_and_placeholder():
    day = date(2026, 8, 21)
    meeting = MeetingPlan(day=day, slot=_mk_slot(day, 15, 4))
    text = build_announcement_text(meeting)
    assert "15:00–16:00" in text
    assert "Conference Room A" in text
    assert "уточняются" in text  # нет активности от Кирилла


def test_announcement_text_uses_activity():
    day = date(2026, 8, 21)
    meeting = MeetingPlan(day=day, slot=_mk_slot(day, 15, 4))
    text = build_announcement_text(meeting, activity="Quiz & Chat — тема: путешествия")
    assert "путешествия" in text
    assert "уточняются" not in text


def test_reminder_text():
    day = date(2026, 8, 21)
    meeting = MeetingPlan(day=day, slot=_mk_slot(day, 16, 4))
    text = build_reminder_text(meeting, reminder_hours=1)
    assert "16:00–17:00" in text
    assert "через 1 ч" in text


def test_checkin_text():
    day = date(2026, 8, 21)
    meeting = MeetingPlan(day=day, slot=_mk_slot(day, 17, 4))
    assert "17:00–18:00" in build_checkin_text(meeting)


# ---------------------------------------------------------------------
# Очередь сообщений после финализации (только напоминание)
# ---------------------------------------------------------------------

def test_plan_meeting_messages_only_reminder():
    day = date(2026, 8, 21)
    slot = _mk_slot(day, 15, 4)
    meeting = MeetingPlan(day=day, slot=slot)
    msgs = plan_meeting_messages(meeting, recipients=["u1", "u2"], reminder_hours=1)

    assert len(msgs) == 1
    assert msgs[0].kind == "REMINDER"
    assert msgs[0].send_at == slot.start - timedelta(hours=1)
    assert msgs[0].recipients == ("u1", "u2")
    assert "Напоминание" in msgs[0].text


def test_plan_meeting_messages_empty_recipients():
    day = date(2026, 8, 21)
    meeting = MeetingPlan(day=day, slot=_mk_slot(day, 15, 4))
    assert plan_meeting_messages(meeting, recipients=[]) == []


# ---------------------------------------------------------------------
# Карточки
# ---------------------------------------------------------------------

def _widgets(card):
    return [
        w
        for section in card["cardsV2"][0]["card"]["sections"]
        for w in section.get("widgets", [])
    ]


def _buttons(card):
    return [
        b
        for w in _widgets(card)
        for b in w.get("buttonList", {}).get("buttons", [])
    ]


def _button_methods(card):
    return [
        next(
            p["value"]
            for p in b["onClick"]["action"]["parameters"]
            if p.get("key") == "method"
        )
        for b in _buttons(card)
    ]


def test_attendance_card_buttons():
    card = build_attendance_card("Тест")
    methods = _button_methods(card)
    assert methods == [METHOD_ATTENDANCE_YES, METHOD_ATTENDANCE_NO]


def test_time_card_radio_options():
    card = build_time_card("Тест", date(2026, 8, 21))
    sel = next(w for w in _widgets(card) if "selectionInput" in w)["selectionInput"]
    assert sel["name"] == "time"
    assert sel["type"] == "RADIO_BUTTON"
    values = [it["value"] for it in sel["items"]]
    assert values == ["2026-08-21T1500", "2026-08-21T1600", "2026-08-21T1700"]
    assert _button_methods(card) == [METHOD_SUBMIT_TIME]


def test_checkin_card_buttons():
    card = build_checkin_card("Тест", "15:00–16:00")
    assert _button_methods(card) == [METHOD_CHECKIN_YES, METHOD_CHECKIN_NO]
