"""Ручная финализация дня: квота → встреча → приглашение → джобы карточки/напоминания.

Запуск: ./venv/Scripts/python -m scripts.finalize_day_now [day]
  day — индекс дня (0=Mon .. 6=Sun). По умолчанию завтрашний день.
"""
import asyncio
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.services.weekly_poll import DAYS, active_weekly_poll, finalize_day
from app.services.invites import handle_time_finalized


async def main() -> None:
    today = datetime.now(ZoneInfo(get_settings().app_timezone)).weekday()
    day = int(sys.argv[1]) if len(sys.argv) > 1 else (today + 1) % 7

    async with AsyncSessionLocal() as db:
        poll = await active_weekly_poll(db)
        if poll is None:
            print("нет активного опроса — сначала scripts.send_poll_now")
            return
        result = await finalize_day(db, poll, day)
        if result is None:
            print(f"{DAYS[day]}: квота не набрана или встреча уже есть")
            return
        meeting, time_str = result
        await handle_time_finalized(
            db, meeting.id, DAYS[day], time_str, scheduled_start=meeting.scheduled_start
        )
        print(f"встреча id={meeting.id} на {DAYS[day]} {time_str} — приглашение + джобы созданы")


if __name__ == "__main__":
    asyncio.run(main())
