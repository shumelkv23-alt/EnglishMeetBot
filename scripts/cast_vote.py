# scripts/cast_vote.py
"""Ручной голос в недельном опросе (тест кворума без UI).

Запуск: ./venv/Scripts/python -m scripts.cast_vote <day> <time> <user_id>
  day — 0=Mon .. 6=Sun; time — "HH:MM"; user_id — 'users/...' профиля.
"""
import asyncio
import sys

from app.database import AsyncSessionLocal
from app.services.onboarding import get_or_create_profile
from app.services.weekly_poll import submit_poll


async def main() -> None:
    day = int(sys.argv[1])
    time = sys.argv[2]
    user_id = sys.argv[3]

    form = {
        "day": {"stringInputs": {"value": [str(day)]}},
        "time": {"stringInputs": {"value": [time]}},
    }
    async with AsyncSessionLocal() as db:
        profile = await get_or_create_profile(db, workspace_user_id=user_id)
        if not profile.english_level:
            profile.english_level = "B1"
        result = await submit_poll(db, profile, form)
        print(f"vote {user_id} day={day} {time} -> {result}")


if __name__ == "__main__":
    asyncio.run(main())
