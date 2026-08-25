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


async def test_submit_poll_touches_activity(db, today_poll):
    from app.services.weekly_poll import submit_poll

    p = await get_or_create_profile(db, "users/e2e_touch_poll")
    p.reminder_count = 5
    p.last_activity_at = None
    await db.commit()

    await submit_poll(db, p, {"day": {"stringInputs": {"value": ["0"]}}, "time": {"stringInputs": {"value": ["15:00"]}}})

    await db.refresh(p)
    assert p.last_activity_at is not None
    assert p.reminder_count == 0


async def test_submit_weekly_question_touches_activity(db):
    from app.services.weekly_questions import submit_weekly_question

    p = await get_or_create_profile(db, "users/e2e_touch_wq")
    p.reminder_count = 2
    p.last_activity_at = None
    await db.commit()

    await submit_weekly_question(
        db, p, {"q_llm": {"stringInputs": {"value": ["ответ"]}}}, "личный вопрос", "общий вопрос",
    )

    await db.refresh(p)
    assert p.last_activity_at is not None
    assert p.reminder_count == 0


async def test_submit_checkin_touches_activity(db, today_poll):
    from sqlalchemy import select

    from app.models import MeetingInstance, PollSlot
    from app.services.checkin import submit_checkin

    p = await get_or_create_profile(db, "users/e2e_touch_checkin")
    p.reminder_count = 4
    p.last_activity_at = None
    await db.commit()

    slot = (
        await db.execute(select(PollSlot).where(PollSlot.poll_id == today_poll.id).limit(1))
    ).scalar_one()
    meeting = MeetingInstance(
        poll_id=today_poll.id,
        selected_slot_id=slot.id,
        scheduled_start=datetime.now(timezone.utc),
        scheduled_end=datetime.now(timezone.utc) + timedelta(hours=1),
        location="Онлайн (Meet)",
        status="scheduled",
    )
    db.add(meeting)
    await db.flush()

    await submit_checkin(db, p, meeting.id)

    await db.refresh(p)
    assert p.last_activity_at is not None
    assert p.reminder_count == 0


async def test_message_touches_activity(client, db):
    from sqlalchemy import select

    from app.models import Profile

    event = {
        "type": "MESSAGE",
        "user": {"name": "users/e2e_touch_msg", "displayName": "E2E", "email": "e2e@example.com"},
        "message": {"text": "привет"},
        "space": {"name": "spaces/e2e_dm", "type": "DM"},
    }
    resp = await client.post("/webhooks/google-chat", json=event)
    assert resp.status_code == 200

    profile = (
        await db.execute(select(Profile).where(Profile.workspace_user_id == "users/e2e_touch_msg"))
    ).scalar_one()
    assert profile.last_activity_at is not None


async def test_message_touches_activity_addon(client, db):
    from sqlalchemy import select

    from app.models import Profile

    event = {
        "chat": {
            "user": {"name": "users/e2e_touch_msg_addon", "displayName": "E2E", "email": "e2e@example.com"},
            "messagePayload": {
                "message": {"text": "привет"},
                "space": {"name": "spaces/e2e_dm", "type": "DM"},
            },
        }
    }
    resp = await client.post("/webhooks/google-chat", json=event)
    assert resp.status_code == 200

    profile = (
        await db.execute(select(Profile).where(Profile.workspace_user_id == "users/e2e_touch_msg_addon"))
    ).scalar_one()
    assert profile.last_activity_at is not None
