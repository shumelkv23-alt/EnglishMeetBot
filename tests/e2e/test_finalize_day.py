"""E2E: finalize_day — кворум обязателен, в том числе при завершении кнопкой.

Кнопка «Finish voting» лишь ускоряет проверку (run_cycle), сама finalize_day
всегда требует кворум. Нужен поднятый Postgres (та же БД, что у бота).
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.models import DailyPoll, MeetingInstance, PollSlot
from app.services.weekly_poll import finalize_day, meeting_start_utc, slot_datetime, week_monday

TEST_DOW = 2  # Wednesday — не пересекается с реальным днём голосования


async def _make_poll(db, votes_by_time: dict[str, int]) -> DailyPoll:
    # poll_date из далёкого прошлого: у daily_polls.poll_date unique-констрейнт,
    # а опрос текущей недели уже существует. finalize_day дату не проверяет.
    poll = DailyPoll(
        poll_date=week_monday() - timedelta(weeks=50),
        voting_deadline=datetime.now(timezone.utc) + timedelta(days=1),
        status="active",
    )
    db.add(poll)
    await db.flush()
    for t in ("15:00", "16:00", "17:00"):
        db.add(PollSlot(
            poll_id=poll.id,
            day_of_week=TEST_DOW,
            slot_start=slot_datetime(t),
            slot_end=slot_datetime(t) + timedelta(minutes=60),
            location="Online (Meet)",
            votes_count=votes_by_time.get(t, 0),
        ))
    await db.commit()
    await db.refresh(poll)
    return poll


async def _cleanup(db, poll_id: int) -> None:
    await db.execute(
        MeetingInstance.__table__.delete().where(MeetingInstance.poll_id == poll_id)
    )
    await db.execute(PollSlot.__table__.delete().where(PollSlot.poll_id == poll_id))
    await db.execute(DailyPoll.__table__.delete().where(DailyPoll.id == poll_id))
    await db.commit()


@pytest.mark.e2e
async def test_finalize_day_below_quorum_returns_none(db):
    # 2 голоса < кворума 3 → встреча НЕ создаётся (в т.ч. по кнопке Finish voting)
    poll = await _make_poll(db, {"15:00": 2})
    try:
        assert await finalize_day(db, poll, TEST_DOW) is None
    finally:
        await _cleanup(db, poll.id)


@pytest.mark.e2e
async def test_finalize_day_at_quorum_creates_meeting(db):
    # 3 голоса == кворум 3 → встреча на слоте с max голосов
    poll = await _make_poll(db, {"15:00": 1, "16:00": 2})
    try:
        result = await finalize_day(db, poll, TEST_DOW)
        assert result is not None
        meeting, time_str = result
        assert time_str == "16:00"
        assert meeting.scheduled_start == meeting_start_utc(
            poll.poll_date + timedelta(days=TEST_DOW), slot_datetime("16:00")
        )
    finally:
        await _cleanup(db, poll.id)


@pytest.mark.e2e
async def test_finalize_day_without_votes_returns_none(db):
    poll = await _make_poll(db, {})
    try:
        assert await finalize_day(db, poll, TEST_DOW) is None
    finally:
        await _cleanup(db, poll.id)
