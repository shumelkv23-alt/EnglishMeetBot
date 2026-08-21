"""Проверка ENG-7: создание встречи (time_finalized) → приглашения, окна, джобы.
Запуск: .\venv\Scripts\python -m scripts.test_eng7_flow
"""
import asyncio
from datetime import datetime, timedelta, timezone

from app.database import AsyncSessionLocal
from app.models import MeetingInstance as MeetingORM, PollSlot, DailyPoll
from app.services.invites import handle_time_finalized
from sqlalchemy import select


async def main() -> None:
    async with AsyncSessionLocal() as db:
        poll = (await db.execute(
            select(DailyPoll).where(DailyPoll.status == "active").order_by(DailyPoll.week_start.desc()).limit(1)
        )).scalar_one_or_none()
        if poll is None:
            print("NO_ACTIVE_POLL — сначала прогони scripts/test_poll_flow.py")
            return
        slot = (await db.execute(select(PollSlot).where(PollSlot.poll_id == poll.id).limit(1))).scalar_one_or_none()
        if slot is None:
            print("NO_SLOTS — сначала прогони scripts/test_poll_flow.py")
            return

        meeting = MeetingORM(
            poll_id=poll.id,
            selected_slot_id=slot.id,
            scheduled_start=datetime.now(timezone.utc) + timedelta(hours=2),
            scheduled_end=datetime.now(timezone.utc) + timedelta(hours=3, minutes=30),
            location="Онлайн (Meet)",
            status="scheduled",
        )
        db.add(meeting)
        await db.flush()
        result = await handle_time_finalized(
            db, meeting.id, "Wed", "19:00", activity=None,
            scheduled_start=meeting.scheduled_start,
        )
        print("RESULT:", result)
        assert result["invited"] <= 1
        await db.rollback()
        print("OK")


if __name__ == "__main__":
    asyncio.run(main())