from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services.inactivity import REMINDER_TEXT, is_inactive, should_remind, touch_activity

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)


def _profile(**kw):
    base = dict(
        last_activity_at=None,
        reminder_count=0,
        last_reminder_at=None,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_touch_activity_sets_time_and_resets_counter():
    p = _profile(reminder_count=3, last_reminder_at=NOW)
    touch_activity(p, NOW)
    assert p.last_activity_at == NOW
    assert p.reminder_count == 0
    assert p.last_reminder_at is None


def test_is_inactive_after_seven_days():
    assert is_inactive(_profile(last_activity_at=NOW - timedelta(days=7)), NOW, 7) is True


def test_is_inactive_active_recently():
    assert is_inactive(_profile(last_activity_at=NOW - timedelta(days=6)), NOW, 7) is False


def test_is_inactive_falls_back_to_created_at():
    assert is_inactive(_profile(created_at=NOW - timedelta(days=30)), NOW, 7) is True


def test_should_remind_first_time():
    assert should_remind(_profile(), NOW, 3, 3) is True


def test_should_remind_interval_not_elapsed():
    p = _profile(last_reminder_at=NOW - timedelta(days=1))
    assert should_remind(p, NOW, 3, 3) is False


def test_should_remind_interval_elapsed():
    p = _profile(reminder_count=1, last_reminder_at=NOW - timedelta(days=3))
    assert should_remind(p, NOW, 3, 3) is True


def test_should_remind_limit_reached():
    p = _profile(reminder_count=3, last_reminder_at=NOW - timedelta(days=4))
    assert should_remind(p, NOW, 3, 3) is False
