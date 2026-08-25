"""E2E scheduler-части: финализация опроса, приглашения, check-in.

Эти функции не имеют HTTP-эндпоинта (их зовут джобы APScheduler), поэтому
проверяем их напрямую с реальной БД. Отправку сообщений в тесте приглашений
мокаем (send_message), чтобы не ходить в реальный Google Chat.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import Attendance, MeetingInstance, PollSlot
from app.services.checkin import submit_checkin
from app.services.invites import handle_time_finalized
from app.services.onboarding import get_or_create_profile
from app.services.weekly_poll import finalize_day, submit_poll

pytestmark = pytest.mark.e2e

FORM_1500 = {"day": {"stringInputs": {"value": ["0"]}}, "time": {"stringInputs": {"value": ["15:00"]}}}


async def _first_slot(db, poll) -> PollSlot:
    return (
        await db.execute(select(PollSlot).where(PollSlot.poll_id == poll.id).limit(1))
    ).scalar_one()


async def _make_meeting(db, poll, start: datetime) -> MeetingInstance:
    slot = await _first_slot(db, poll)
    meeting = MeetingInstance(
        poll_id=poll.id,
        selected_slot_id=slot.id,
        scheduled_start=start,
        scheduled_end=start + timedelta(hours=1),
        location="Онлайн (Meet)",
        status="scheduled",
    )
    db.add(meeting)
    await db.flush()
    return meeting


async def test_finalize_creates_meeting_on_quorum(db, today_poll):
    for i in range(3):  # кворум по умолчанию = 3
        p = await get_or_create_profile(db, f"users/e2e_fin_{i}")
        await submit_poll(db, p, FORM_1500)

    result = await finalize_day(db, today_poll, 0)
    assert result is not None
    _, time_str = result
    assert time_str == "15:00"

    meetings = (
        await db.execute(select(MeetingInstance).where(MeetingInstance.poll_id == today_poll.id))
    ).scalars().all()
    assert len(meetings) == 1
    m = meetings[0]
    assert m.scheduled_end - m.scheduled_start == timedelta(minutes=60)


async def test_finalize_cancels_without_quorum(db, today_poll):
    p = await get_or_create_profile(db, "users/e2e_cancel")
    await submit_poll(db, p, FORM_1500)  # 1 голос < кворума 3

    result = await finalize_day(db, today_poll, 0)
    assert result is None

    meetings = (
        await db.execute(select(MeetingInstance).where(MeetingInstance.poll_id == today_poll.id))
    ).scalars().all()
    assert len(meetings) == 0


async def test_handle_time_finalized_posts_to_space(db, today_poll, monkeypatch):
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr("app.services.invites.send_text", lambda space, text: sent.append((space, text)))

    p = await get_or_create_profile(db, "users/e2e_inv")
    await submit_poll(db, p, FORM_1500)  # status=responded

    meeting = await _make_meeting(db, today_poll, datetime.now(timezone.utc) + timedelta(hours=2))
    result = await handle_time_finalized(
        db, meeting.id, "Wed", "19:00",
        scheduled_start=meeting.scheduled_start,
    )
    assert result["invited"] == 0
    assert len(sent) == 1
    _, text = sent[0]
    assert "19:00" in text


async def test_send_reminder_posts_to_space(db, today_poll, monkeypatch):
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr("app.services.invites.send_text", lambda space, text: sent.append((space, text)))

    meeting = await _make_meeting(db, today_poll, datetime.now(timezone.utc) + timedelta(hours=1))
    await db.commit()
    from app.services.invites import _send_reminder

    await _send_reminder(str(meeting.id))
    assert len(sent) == 1
    _, text = sent[0]
    assert "in an hour" in text


async def test_checkin_within_window_marks_present(db, today_poll):
    p = await get_or_create_profile(db, "users/e2e_checkin")
    meeting = await _make_meeting(db, today_poll, datetime.now(timezone.utc))

    result = await submit_checkin(db, p, meeting.id, after_min=15)
    assert result["within"] is True
    assert result["count"] == 1

    att = (
        await db.execute(
            select(Attendance).where(
                Attendance.profile_id == p.id,
                Attendance.meeting_instance_id == meeting.id,
            )
        )
    ).scalar_one()
    assert att.status == "present"


async def test_checkin_outside_window_stays_pending(db, today_poll):
    p = await get_or_create_profile(db, "users/e2e_checkin_out")
    meeting = await _make_meeting(db, today_poll, datetime.now(timezone.utc) - timedelta(hours=3))

    result = await submit_checkin(db, p, meeting.id, after_min=15)
    assert result["within"] is False

    att = (
        await db.execute(
            select(Attendance).where(
                Attendance.profile_id == p.id,
                Attendance.meeting_instance_id == meeting.id,
            )
        )
    ).scalar_one()
    assert att.status == "pending"


async def test_poll_counts_reflects_votes(db, today_poll):
    from app.services.weekly_poll import poll_counts

    p = await get_or_create_profile(db, "users/e2e_counts")
    await submit_poll(db, p, FORM_1500)  # голос за Пн 15:00

    days, times, counts = await poll_counts(db, today_poll.id)
    assert days == [0, 1, 2, 3, 4, 5, 6]
    assert times == ["15:00", "16:00", "17:00"]
    assert counts[(0, "15:00")] == 1
    assert counts[(0, "16:00")] == 0


async def test_inactivity_reminder_job_calls_remind_inactive(db, monkeypatch):
    called: list[int] = []
    async def fake_remind(db):
        called.append(1)
        return 0
    monkeypatch.setattr("app.services.inactivity.remind_inactive", fake_remind)
    from app.scheduler import _run_inactivity_reminder

    await _run_inactivity_reminder()

    assert called == [1]


async def test_inactivity_job_registered(db):
    from app import scheduler as sched_mod
    from app.scheduler import init_scheduler, shutdown_scheduler

    await init_scheduler()
    try:
        assert sched_mod.scheduler.get_job("inactivity-reminder") is not None
    finally:
        shutdown_scheduler()
