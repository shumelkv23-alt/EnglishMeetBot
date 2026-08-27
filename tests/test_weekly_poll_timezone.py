"""Юнит-тесты таймзоны встреч: слот-время в таймзоне приложения, а не UTC."""
from datetime import date, timezone
from zoneinfo import ZoneInfo

from app.services.weekly_poll import meeting_start_utc, slot_datetime


def test_meeting_start_utc_uses_app_timezone():
    # Europe/Minsk (UTC+3): слот «15:00» → 12:00 UTC.
    start = meeting_start_utc(
        date(2026, 8, 27), slot_datetime("15:00"), tz=ZoneInfo("Europe/Minsk")
    )
    assert start.hour == 12
    assert start.minute == 0
    assert start.utcoffset() == timezone.utc.utcoffset(None)
