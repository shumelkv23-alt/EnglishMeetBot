# tests/test_poll_vote_parse.py
"""Чистые тесты parse_time_form: оба формата Google, дубли, мусор, пустой ввод."""
from app.services.poll_store import parse_time_form


def _classic(values):
    return {"stringInputs": {"value": values}}


def _addon(values):
    return {"": {"stringInputs": {"value": values}}}


class TestClassicFormat:
    def test_single_slot(self):
        form = {"time": _classic(["2026-08-21T1500"])}
        assert parse_time_form(form) == "2026-08-21T1500"

    def test_returns_first_value(self):
        form = {"time": _classic(["2026-08-21T1600", "2026-08-21T1700"])}
        assert parse_time_form(form) == "2026-08-21T1600"


class TestAddonFormat:
    def test_addon_wrapper(self):
        form = {"time": _addon(["2026-08-21T1700"])}
        assert parse_time_form(form) == "2026-08-21T1700"


class TestGarbageAndEmpty:
    def test_empty_form(self):
        assert parse_time_form({}) == ""

    def test_missing_time_key(self):
        assert parse_time_form({"days": _classic(["2026-08-21"])}) == ""

    def test_non_dict_field_ignored(self):
        assert parse_time_form({"time": "2026-08-21T1500"}) == ""

    def test_empty_values(self):
        assert parse_time_form({"time": _classic([])}) == ""

    def test_whitespace_values_skipped(self):
        assert parse_time_form({"time": _classic(["   "])}) == ""

    def test_value_stripped(self):
        assert parse_time_form({"time": _classic([" 2026-08-21T1500 "])}) == "2026-08-21T1500"
