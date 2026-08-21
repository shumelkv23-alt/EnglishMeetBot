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
    card = build_poll_card("Персональный вопрос?", "Банковский вопрос?", [{"id": 7, "label": "Wed"}])
    assert card["cardsV2"][0]["cardId"] == "weeklyPoll"
    sections = card["cardsV2"][0]["card"]["sections"]
    assert len(sections) == 3  # вопросы + слоты + кнопка
    widgets = sections[0]["widgets"]
    # textParagraph (вопрос) + textInput (ответ) для каждого из 2 вопросов = 4 виджета
    assert len(widgets) == 4
    assert widgets[0]["textParagraph"]["text"] == "<b>Персональный вопрос?</b>"
    assert widgets[1]["textInput"]["name"] == "q_llm"
    assert widgets[1]["textInput"]["label"] == "Твой ответ"
    assert widgets[2]["textParagraph"]["text"] == "<b>Банковский вопрос?</b>"
    assert widgets[3]["textInput"]["name"] == "q_bank"
    # слоты: русское название дня
    items = sections[1]["widgets"][0]["selectionInput"]["items"]
    assert items[0]["text"] == "Среда"
    assert items[0]["value"] == "7"


def test_build_poll_card_button_function_is_url():
    card = build_poll_card("q", "b", [{"id": 7, "label": "Wed"}], action_url="https://example.com/hook")
    button = card["cardsV2"][0]["card"]["sections"][2]["widgets"][0]["buttonList"]["buttons"][0]
    function = button["onClick"]["action"]["function"]
    assert function == "https://example.com/hook"
    assert function != "weekly_poll_submit"