"""Интеграционная проверка опроса (нужен поднятый Postgres).

Прогон: ensure_weekly_poll -> submit_poll -> проверка answers/votes/poll_responses.
Запуск: .\venv\Scripts\python scripts\test_poll_flow.py
"""
import asyncio
from datetime import datetime, timedelta, timezone

from app.database import AsyncSessionLocal
from app.models import Answer, PollResponse, PollSlot, PollVote, WeeklyPoll
from app.services.onboarding import current_week_start, get_or_create_profile
from app.services.weekly_poll import ensure_weekly_poll, get_or_create_config, submit_poll
from sqlalchemy import delete, select


async def main() -> None:
    async with AsyncSessionLocal() as db:
        profile = await get_or_create_profile(db, "users/test_poll_flow", display_name="TestFlow")

        # 1. настроить окружение: слоты из конфига (в тестовой БД их ещё нет)
        cfg = await get_or_create_config(db, "poll_slots", [])
        cfg.value = [
            {"day": "Sun", "time": "23:00", "location": "Meet"},
            {"day": "Wed", "time": "19:00", "location": "Meet", "priority": 1},
        ]
        await db.commit()
        # 2. очистить опрос текущей недели, чтобы ensure_weekly_poll создал заново со слотами
        await db.execute(Answer.__table__.delete().where(Answer.profile_id == profile.id))
        await db.execute(delete(PollVote).where(PollVote.profile_id == profile.id))
        await db.execute(delete(PollResponse).where(PollResponse.profile_id == profile.id))
        old = (await db.execute(select(WeeklyPoll).where(WeeklyPoll.week_start == current_week_start()))).scalar_one_or_none()
        if old is not None:
            await db.execute(delete(PollSlot).where(PollSlot.poll_id == old.id))
            await db.execute(delete(PollResponse).where(PollResponse.poll_id == old.id))
            await db.execute(delete(WeeklyPoll).where(WeeklyPoll.id == old.id))
            await db.commit()

        poll = await ensure_weekly_poll(db, datetime.now(timezone.utc))
        # страховка: дедлайн должен быть в будущем (тестовая неделя в середине)
        if poll.voting_deadline < datetime.now(timezone.utc):
            poll.voting_deadline = datetime.now(timezone.utc) + timedelta(hours=2)
            await db.commit()
        print("poll:", None if poll is None else (poll.id, poll.status, poll.voting_deadline))

        slots = [
            s.id for s in (
                await db.execute(select(PollSlot).where(PollSlot.poll_id == poll.id))
            ).scalars().all()
        ]
        print("slots:", slots)

        form = {
            "q_llm": {"stringInputs": {"value": ["Люблю нейросети"]}},
            "q_bank": {"stringInputs": {"value": ["Дюна"]}},
            "slots": {"stringInputs": {"value": [str(slots[0])] if slots else []}},
        }
        first = await submit_poll(db, profile, form)
        second = await submit_poll(db, profile, form)  # повторный — должен перезаписать, не дублировать
        print("first:", first, "second:", second)

        answers = (await db.execute(select(Answer).where(Answer.profile_id == profile.id))).scalars().all()
        votes = (await db.execute(select(PollVote).where(PollVote.profile_id == profile.id))).scalars().all()
        responded = (await db.execute(select(PollResponse).where(PollResponse.profile_id == profile.id))).scalars().all()
        print("answers:", len(answers), "votes:", len(votes), "responded:", len(responded))
        assert first["ok"] is True
        assert len(votes) == 1
        assert all(r.status == "responded" for r in responded)

        await db.execute(Answer.__table__.delete().where(
            Answer.profile_id == profile.id
        ))
        await db.commit()
        print("OK")


if __name__ == "__main__":
    asyncio.run(main())