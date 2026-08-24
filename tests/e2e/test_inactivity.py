"""E2E: remind_inactive — отправка напоминаний неактивным (реальная БД)."""
from datetime import datetime, timedelta, timezone

import pytest

from app.services.inactivity import remind_inactive
from app.services.onboarding import get_or_create_profile

pytestmark = pytest.mark.e2e

NOW = datetime.now(timezone.utc)


async def _make_profile(db, user_id, *, days_ago, reminder_count=0, last_reminder_days=None):
    p = await get_or_create_profile(db, user_id, chat_space_id="spaces/e2e_inact")
    p.last_activity_at = NOW - timedelta(days=days_ago)
    p.reminder_count = reminder_count
    p.last_reminder_at = (NOW - timedelta(days=last_reminder_days)) if last_reminder_days else None
    await db.commit()
    return p


async def test_remind_inactive_sends_and_increments(db, monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr("app.services.inactivity.send_message", lambda uid, payload: sent.append(uid))
    p = await _make_profile(db, "users/e2e_inact1", days_ago=8)

    await remind_inactive(db)

    assert "users/e2e_inact1" in sent
    await db.refresh(p)
    assert p.reminder_count == 1
    assert p.last_reminder_at is not None


async def test_remind_skips_recently_active(db, monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr("app.services.inactivity.send_message", lambda uid, payload: sent.append(uid))
    await _make_profile(db, "users/e2e_inact_active", days_ago=1)

    await remind_inactive(db)

    assert "users/e2e_inact_active" not in sent


async def test_remind_respects_interval(db, monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr("app.services.inactivity.send_message", lambda uid, payload: sent.append(uid))
    await _make_profile(db, "users/e2e_inact_int", days_ago=8, reminder_count=1, last_reminder_days=1)

    await remind_inactive(db)

    assert "users/e2e_inact_int" not in sent  # интервал 3 дня не прошёл


async def test_remind_stops_at_limit(db, monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr("app.services.inactivity.send_message", lambda uid, payload: sent.append(uid))
    await _make_profile(db, "users/e2e_inact_limit", days_ago=8, reminder_count=3, last_reminder_days=4)

    await remind_inactive(db)

    assert "users/e2e_inact_limit" not in sent  # лимит 3 исчерпан
