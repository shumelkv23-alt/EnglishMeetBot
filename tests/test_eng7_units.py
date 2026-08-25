from datetime import datetime, timedelta, timezone

from app.services.checkin import build_checkin_card, checkin_window, is_within_window, job_ids
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
    end = datetime(2026, 8, 26, 20, 0, tzinfo=timezone.utc)
    open_at, close_at = checkin_window(start, end)
    assert open_at == start
    assert close_at == end + timedelta(minutes=15)


def test_build_checkin_card_has_count():
    card = build_checkin_card("7", action_url="https://example.com/hook", count=3)
    sections = card["cardsV2"][0]["card"]["sections"]
    assert sections[0]["widgets"][0]["textParagraph"]["text"] == "Checked in: 3"


def test_is_within_window():
    start = datetime(2026, 8, 26, 19, 0, tzinfo=timezone.utc)
    end = datetime(2026, 8, 26, 20, 0, tzinfo=timezone.utc)
    open_at, close_at = checkin_window(start, end)
    assert is_within_window(start, open_at, close_at) is True
    assert is_within_window(end + timedelta(minutes=16), open_at, close_at) is False


def test_job_ids():
    assert job_ids("7") == {"open": "checkin_open_7", "close": "checkin_close_7"}
    assert reminder_job_id("7") == "remind_7"


def test_build_checkin_card_button_function_is_url():
    card = build_checkin_card("7", action_url="https://example.com/hook")
    button = card["cardsV2"][0]["card"]["sections"][1]["widgets"][0]["buttonList"]["buttons"][0]
    function = button["onClick"]["action"]["function"]
    assert function == "https://example.com/hook"
    assert function != "checkin_submit"