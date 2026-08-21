"""Интеграционная проверка ежедневного опроса (нужен поднятый Postgres).

Прогон: ensure_daily_poll -> submit_poll -> проверка votes/poll_responses.
Запуск: .\venv\Scripts\python scripts\test_poll_flow.py
"""
import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.database import AsyncSessionLocal
from app.models import PollResponse, PollSlot, PollVote, DailyPoll
from app.services.onboarding import get_or_create_profile
from app.services.weekly_poll import ensure_daily_poll, submit_poll


async def main() -> None:
    async with AsyncSessionLocal() as db:
        profile = await get_or_create_profile(db, "users/test_poll_flow", display_name="TestFlow")

        # очистить голоса/ответы и опрос дня, чтобы ensure создал заново
        await db.execute(delete(PollVote).where(PollVote.profile_id == profile.id))
        await db.execute(delete(PollResponse).where(PollResponse.profile_id == profile.id))
        today = datetime.now(timezone.utc).date()
        old = (await db.execute(select(DailyPoll).where(DailyPoll.poll_date == today))).scalar_one_or_none()
        if old is not None:
            await db.execute(delete(PollSlot).where(PollSlot.poll_id == old.id))
            await db.execute(delete(PollResponse).where(PollResponse.poll_id == old.id))
            await db.execute(delete(DailyPoll).where(DailyPoll.id == old.id))
            await db.commit()

        poll = await ensure_daily_poll(db, datetime.now(timezone.utc))
        # страховка: дедлайн должен быть в будущем (если скрипт гоняют после 14:00 UTC)
        if poll.voting_deadline < datetime.now(timezone.utc):
            poll.voting_deadline = datetime.now(timezone.utc) + timedelta(hours=2)
            await db.commit()
        print("poll:", None if poll is None else (poll.id, poll.status, poll.voting_deadline))

        form = {"time": {"stringInputs": {"value": ["15:00"]}}}
        first = await submit_poll(db, profile, form)
        second = await submit_poll(db, profile, form)  # повторный — перезапись голоса
        print("first:", first, "second:", second)

        votes = (await db.execute(select(PollVote).where(PollVote.profile_id == profile.id))).scalars().all()
        responded = (await db.execute(select(PollResponse).where(PollResponse.profile_id == profile.id))).scalars().all()
        print("votes:", len(votes), "responded:", len(responded))
        assert first["ok"] is True
        assert len(votes) == 1
        assert all(r.status == "responded" for r in responded)

        # выбранный слот — 15:00
        chosen = (await db.execute(select(PollSlot).where(
            PollSlot.poll_id == poll.id,
            PollSlot.id.in_(select(PollVote.poll_slot_id).where(PollVote.profile_id == profile.id)),
        ))).scalar_one_or_none()
        assert chosen is not None and chosen.slot_start.strftime("%H:%M") == "15:00"

        await db.execute(delete(PollVote).where(PollVote.profile_id == profile.id))
        await db.commit()
        print("OK")


if __name__ == "__main__":
    asyncio.run(main())
