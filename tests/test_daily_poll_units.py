# tests/test_daily_poll_units.py
from app.services.form_parsing import parse_form_inputs
from app.services.weekly_poll import _normalize_submit_time, resolve_day_result


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
