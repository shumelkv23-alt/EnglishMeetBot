from datetime import datetime, timedelta, timezone

from app.services.checkin import checkin_window, is_within_window, job_ids
from app.services.invites import build_escalation_text, build_invite_text
from app.services.reminders import reminder_at, reminder_job_id


def test_build_invite_text_with_theme():
    text = build_invite_text("Wed", "19:00", "Мини-дайджест недели")
    assert "Wed" in text and "19:00" in text and "Мини-дайджест недели" in text


def test_build_invite_text_without_theme():
    assert "тема" not in build_invite_text("Wed", "19:00", None).lower()


def test_build_escalation_text():
    assert build_escalation_text()


def test_reminder_at():
    start = datetime(2026, 8, 26, 19, 0, tzinfo=timezone.utc)
    assert reminder_at(start, 1) == datetime(2026, 8, 26, 18, 0, tzinfo=timezone.utc)


def test_checkin_window():
    start = datetime(2026, 8, 26, 19, 0, tzinfo=timezone.utc)
    open_at, close_at = checkin_window(start, 15)
    assert open_at == start - timedelta(minutes=15)
    assert close_at == start + timedelta(minutes=15)


def test_is_within_window():
    start = datetime(2026, 8, 26, 19, 0, tzinfo=timezone.utc)
    open_at, close_at = checkin_window(start, 15)
    assert is_within_window(start, open_at, close_at) is True
    assert is_within_window(start + timedelta(minutes=16), open_at, close_at) is False


def test_job_ids():
    assert job_ids("7") == {"open": "checkin_open_7", "close": "checkin_close_7"}
    assert reminder_job_id("7") == "remind_7"