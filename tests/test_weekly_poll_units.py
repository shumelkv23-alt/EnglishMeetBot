from datetime import datetime, timedelta, timezone

from app.services.weekly_poll import (
    build_poll_card,
    compute_deadline,
    parse_poll_form,
    slot_day_time,
)


def test_parse_poll_form_with_answers_and_slots():
    form = {
        "q_llm": {"stringInputs": {"value": ["Люблю читать фантастику"]}},
        "q_bank": {"stringInputs": {"value": ["Дюна"]}},
        "slots": {"stringInputs": {"value": ["1", "3"]}},
    }
    parsed = parse_poll_form(form)
    assert dict(parsed["answers"]) == {"q_llm": "Люблю читать фантастику", "q_bank": "Дюна"}
    assert parsed["slot_ids"] == [1, 3]


def test_parse_poll_form_empty():
    assert parse_poll_form({}) == {"answers": [], "slot_ids": []}


def test_compute_deadline_minus_buffer():
    a = datetime(2026, 8, 26, 19, 0, tzinfo=timezone.utc)
    b = datetime(2026, 8, 28, 19, 0, tzinfo=timezone.utc)
    assert compute_deadline([a, b], 24) == datetime(2026, 8, 25, 19, 0, tzinfo=timezone.utc)


def test_slot_day_time():
    dt = datetime(2026, 8, 26, 19, 0, tzinfo=timezone.utc)  # среда
    assert slot_day_time(dt) == ("Wed", "19:00")


def test_build_poll_card_structure():
    card = build_poll_card("Персональный вопрос?", "Банковский вопрос?", [{"id": 7, "label": "Ср 19:00"}])
    assert card["cardsV2"][0]["cardId"] == "weeklyPoll"
    sections = card["cardsV2"][0]["card"]["sections"]
    assert len(sections) == 3  # вопросы + слоты + кнопка
    assert len(sections[0]["widgets"]) == 2  # q_llm + q_bank
    assert sections[0]["widgets"][0]["textInput"]["name"] == "q_llm"
    items = sections[1]["widgets"][0]["selectionInput"]["items"]
    assert items[0] == {"text": "Ср 19:00", "value": "7", "selected": False}