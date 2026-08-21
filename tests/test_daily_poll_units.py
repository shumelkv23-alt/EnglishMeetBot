# tests/test_daily_poll_units.py
from app.services.form_parsing import parse_form_inputs
from app.services.weekly_poll import (
    _is_valid_submit_time,
    _normalize_submit_time,
    build_daily_poll_card,
    resolve_day_result,
)


def test_resolve_three_groups():
    r = resolve_day_result({"15:00": 3, "16:00": 4, "17:00": 3}, 3)
    assert r["meetings"] == ["15:00", "16:00", "17:00"]
    assert r["suggest_to"] == {}
    assert r["cancelled"] is False


def test_resolve_suggest_losers():
    r = resolve_day_result({"15:00": 3, "16:00": 2, "17:00": 1}, 3)
    assert r["meetings"] == ["15:00"]
    assert r["suggest_to"] == {"16:00": "15:00", "17:00": "15:00"}
    assert r["cancelled"] is False


def test_resolve_cancelled():
    r = resolve_day_result({"15:00": 2, "16:00": 2, "17:00": 2}, 3)
    assert r["meetings"] == []
    assert r["cancelled"] is True


def test_parse_form_inputs_addon_nested():
    addon = {"slots": {"": {"stringInputs": {"value": ["15:00"]}}}}
    assert parse_form_inputs(addon) == {"slots": ["15:00"]}


def test_parse_form_inputs_flat():
    flat = {"q1": {"stringInputs": {"value": ["it", "travel"]}}}
    assert parse_form_inputs(flat) == {"q1": ["it", "travel"]}


def test_normalize_submit_time():
    assert _normalize_submit_time({"time": {"stringInputs": {"value": ["15:00"]}}}) == "15:00"
    assert _normalize_submit_time({"time": {"stringInputs": {"value": ["not_available"]}}}) == "not_available"
    assert _normalize_submit_time({}) == ""


def test_is_valid_submit_time_accepts_slots_and_not_available():
    assert _is_valid_submit_time("15:00") is True
    assert _is_valid_submit_time("16:00") is True
    assert _is_valid_submit_time("17:00") is True
    assert _is_valid_submit_time("not_available") is True


def test_is_valid_submit_time_rejects_garbage():
    assert _is_valid_submit_time("banana") is False
    assert _is_valid_submit_time("15") is False
    assert _is_valid_submit_time("18:00") is False
    assert _is_valid_submit_time("") is False


def test_build_daily_poll_card_has_four_buttons():
    card = build_daily_poll_card(["15:00", "16:00", "17:00"], action_url="https://x/hook")
    buttons = card["cardsV2"][0]["card"]["sections"][0]["widgets"][0]["buttonList"]["buttons"]
    labels = [b["text"] for b in buttons]
    assert labels == ["15:00", "16:00", "17:00", "Не могу сегодня"]
    assert all(b["onClick"]["action"]["function"] == "https://x/hook" for b in buttons)
