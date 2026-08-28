# tests/test_daily_poll_units.py
from datetime import date

from app.services.form_parsing import parse_form_inputs
from app.services.weekly_poll import (
    _is_valid_submit_time,
    _normalize_submit,
    build_confirmation_card,
    build_weekly_poll_card,
    parse_day,
    slot_datetime,
    week_monday,
)


def test_parse_day_names_and_numbers():
    assert parse_day("Mon") == 0
    assert parse_day("mon") == 0
    assert parse_day("0") == 0
    assert parse_day("6") == 6
    assert parse_day("sun") == 6


def test_parse_day_rejects_garbage():
    assert parse_day("banana") == -1
    assert parse_day("7") == -1
    assert parse_day("") == -1


def test_parse_form_inputs_addon_nested():
    addon = {"slots": {"": {"stringInputs": {"value": ["15:00"]}}}}
    assert parse_form_inputs(addon) == {"slots": ["15:00"]}


def test_parse_form_inputs_flat():
    flat = {"q1": {"stringInputs": {"value": ["it", "travel"]}}}
    assert parse_form_inputs(flat) == {"q1": ["it", "travel"]}


def test_normalize_submit():
    form = {"day": {"stringInputs": {"value": ["Mon"]}}, "time": {"stringInputs": {"value": ["15:00"]}}}
    assert _normalize_submit(form) == (0, "15:00")
    assert _normalize_submit({}) == (-1, "")


def test_is_valid_submit_time():
    assert _is_valid_submit_time("15:00") is True
    assert _is_valid_submit_time("16:00") is True
    assert _is_valid_submit_time("17:00") is True
    assert _is_valid_submit_time("banana") is False
    assert _is_valid_submit_time("18:00") is False
    assert _is_valid_submit_time("") is False


def test_slot_datetime_parses_time():
    dt = slot_datetime("15:00")
    assert dt.hour == 15 and dt.minute == 0


def test_slot_datetime_carrier_date():
    dt = slot_datetime("17:30")
    assert dt.date().isoformat() == "2000-01-01"
    assert dt.tzinfo is not None


def test_week_monday_known_date():
    # 2024-01-01 — понедельник; среда той же недели → понедельник
    assert week_monday(date(2024, 1, 3)) == date(2024, 1, 1)


def test_week_monday_returns_monday():
    assert week_monday().weekday() == 0


def test_build_weekly_poll_card_sections_and_buttons():
    card = build_weekly_poll_card([0, 1], ["15:00", "16:00"], "https://x/hook", today_dow=0)
    sections = card["cardsV2"][0]["card"]["sections"]
    assert len(sections) == 2
    assert sections[0]["header"] == "Mon · 0 voted"
    buttons = sections[0]["widgets"][0]["buttonList"]["buttons"]
    assert [b["text"] for b in buttons] == ["15:00 (0)", "16:00 (0)"]
    p = {x["key"]: x["value"] for x in buttons[0]["onClick"]["action"]["parameters"]}
    assert p["method"] == "submit_daily_poll"
    assert p["day"] == "0"
    assert p["time"] == "15:00"


def test_build_weekly_poll_card_shows_counts():
    counts = {(0, "15:00"): 4, (0, "16:00"): 2, (1, "15:00"): 1}
    card = build_weekly_poll_card([0, 1], ["15:00", "16:00"], "https://x/hook", counts, today_dow=0)
    sections = card["cardsV2"][0]["card"]["sections"]
    assert sections[0]["header"] == "Mon · 6 voted"
    buttons = sections[0]["widgets"][0]["buttonList"]["buttons"]
    assert [b["text"] for b in buttons] == ["15:00 (4)", "16:00 (2)"]


def test_build_weekly_poll_card_no_finish_button_by_default():
    card = build_weekly_poll_card([0], ["15:00"], "https://x/hook", today_dow=0)
    sections = card["cardsV2"][0]["card"]["sections"]
    for section in sections:
        widgets = section.get("widgets", [])
        for w in widgets:
            if "buttonList" in w:
                for b in w["buttonList"]["buttons"]:
                    p = {x["key"]: x["value"] for x in b["onClick"]["action"]["parameters"]}
                    assert p["method"] != "finish_voting"


def test_build_weekly_poll_card_finish_button():
    card = build_weekly_poll_card([0], ["15:00"], "https://x/hook", today_dow=0, show_finish_button=True)
    sections = card["cardsV2"][0]["card"]["sections"]
    last = sections[-1]["widgets"][0]["buttonList"]["buttons"]
    assert len(last) == 1
    p = {x["key"]: x["value"] for x in last[0]["onClick"]["action"]["parameters"]}
    assert p["method"] == "finish_voting"


def test_build_confirmation_card_has_yes_no():
    card = build_confirmation_card(3, "https://x/hook")
    assert "Thursday" in card["cardsV2"][0]["card"]["header"]["title"]
    buttons = card["cardsV2"][0]["card"]["sections"][0]["widgets"][0]["buttonList"]["buttons"]
    assert len(buttons) == 2
    no_params = {p["key"]: p["value"] for p in buttons[1]["onClick"]["action"]["parameters"]}
    assert no_params["method"] == "confirm_attendance"
    assert no_params["answer"] == "no"
    assert no_params["day"] == "3"
