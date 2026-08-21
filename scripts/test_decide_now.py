# scripts/test_decide_now.py
"""Принудительный прогон ежедневного решения прямо сейчас (не дожидаясь 20:00).

Показывает исход decide_for_tomorrow для активного опроса:
фиксация встречи / эскалация / нет опроса. Реально шлёт сообщения!
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import AsyncSessionLocal  # noqa: E402
from app.services.poll_store import decide_tomorrow, finalize_expired_weeks  # noqa: E402
from app.timeutil import app_now  # noqa: E402


async def main() -> None:
    now = app_now()
    async with AsyncSessionLocal() as db:
        outcome = await decide_tomorrow(db, now)
        cancelled = await finalize_expired_weeks(db, now)

    decision = outcome["decision"]
    reminder = outcome["reminder"]
    if decision is None:
        print("Активного опроса на завтра нет.")
    else:
        print("kind:", decision.kind)
        print("day:", decision.day, "voters:", decision.voters, "quorum:", decision.quorum)
        print("reason:", decision.reason)
        if decision.meeting is not None:
            print(
                "meeting:",
                decision.meeting.day,
                decision.meeting.slot.start.isoformat(),
                "-",
                decision.meeting.slot.end.isoformat(),
                decision.meeting.slot.location,
            )
    if reminder is not None:
        print("reminder at:", reminder.send_at.isoformat())
        print("reminder text:", reminder.text.replace("\n", " | "))
    print("cancelled_weeks:", cancelled)


if __name__ == "__main__":
    asyncio.run(main())
