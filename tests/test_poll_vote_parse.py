# tests/test_poll_vote_parse.py
"""Чистые тесты parse_poll_form: оба формата Google, дубли, мусор, пустой ввод."""
from datetime import date

from app.services.poll_store import parse_poll_form


def _classic(values):
    return {"stringInputs": {"value": values}}


def _addon(values):
    return {"": {"stringInputs": {"value": values}}}


class TestClassicFormat:
    def test_single_day(self):
        form = {"days": _classic(["2026-08-24"])}
        days, themes = parse_poll_form(form)
        assert days == [date(2026, 8, 24)]
        assert themes == ["", ""]

    def test_multiple_days_order_preserved(self):
        form = {"days": _classic(["2026-08-25", "2026-08-24", "2026-08-28"])}
        days, _ = parse_poll_form(form)
        assert days == [date(2026, 8, 25), date(2026, 8, 24), date(2026, 8, 28)]

    def test_duplicates_dropped(self):
        form = {"days": _classic(["2026-08-24", "2026-08-24"])}
        days, _ = parse_poll_form(form)
        assert days == [date(2026, 8, 24)]


class TestAddonFormat:
    def test_addon_wrapper(self):
        form = {"days": _addon(["2026-08-24", "2026-08-26"])}
        days, _ = parse_poll_form(form)
        assert days == [date(2026, 8, 24), date(2026, 8, 26)]

    def test_themes_addon(self):
        form = {
            "days": _addon(["2026-08-24"]),
            "q_theme1": _addon(["нейросети"]),
            "q_theme2": _addon(["сериалы"]),
        }
        _, themes = parse_poll_form(form)
        assert themes == ["нейросети", "сериалы"]


class TestThemes:
    def test_themes_classic(self):
        form = {
            "days": _classic(["2026-08-24"]),
            "q_theme1": _classic(["IT и будущее"]),
            "q_theme2": _classic([]),
        }
        _, themes = parse_poll_form(form)
        assert themes == ["IT и будущее", ""]

    def test_themes_whitespace_stripped_and_empty_skipped(self):
        form = {
            "days": _classic(["2026-08-24"]),
            "q_theme1": _classic(["   "]),
            "q_theme2": _classic([" игры "]),
        }
        _, themes = parse_poll_form(form)
        assert themes == ["", "игры"]


class TestGarbageAndEmpty:
    def test_invalid_dates_dropped(self):
        form = {"days": _classic(["не дата", "2026-13-99", "2026-08-24", ""])}
        days, _ = parse_poll_form(form)
        assert days == [date(2026, 8, 24)]

    def test_empty_form(self):
        assert parse_poll_form({}) == ([], ["", ""])

    def test_missing_days_key(self):
        form = {"q_theme1": _classic(["что-то"])}
        days, themes = parse_poll_form(form)
        assert days == []
        assert themes == ["что-то", ""]

    def test_non_dict_fields_ignored(self):
        form = {"days": "2026-08-24", "q_theme1": 42}
        assert parse_poll_form(form) == ([], ["", ""])
