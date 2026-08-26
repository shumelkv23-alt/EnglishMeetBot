# tests/test_week_theme_units.py
from datetime import date, timedelta

from app.services.week_theme import THEME_BANK, week_theme


def test_week_theme_returns_bank_entry():
    assert week_theme(date(2026, 8, 24)) in THEME_BANK


def test_week_theme_is_deterministic():
    assert week_theme(date(2026, 8, 24)) == week_theme(date(2026, 8, 24))


def test_week_theme_no_repeat_within_bank():
    # 24 последовательные недели -> 24 разных темы
    monday = date(2026, 1, 5)  # понедельник
    seen = [week_theme(monday + timedelta(weeks=w)) for w in range(len(THEME_BANK))]
    assert len(set(seen)) == len(THEME_BANK)
