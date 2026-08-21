# scripts/test_daily_checkin.py
"""Принудительная рассылка чек-инов «ты был(а) на встрече?» за сегодня.

Осторожно — реально шлёт DM участникам сегодняшних встреч!
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import AsyncSessionLocal  # noqa: E402
from app.services.poll_store import send_daily_checkins  # noqa: E402
from app.timeutil import app_now  # noqa: E402


async def main() -> None:
    async with AsyncSessionLocal() as db:
        sent = await send_daily_checkins(db, app_now())
        print("checkins sent:", sent)


if __name__ == "__main__":
    asyncio.run(main())
