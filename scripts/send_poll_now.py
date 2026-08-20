"""Ручная отправка еженедельного опроса (для проверки без ожидания cron).

Запуск: .\venv\Scripts\python -m scripts.send_poll_now
"""
import asyncio
from datetime import datetime, timezone

from app.database import AsyncSessionLocal
from app.services.weekly_poll import send_weekly_polls


async def main() -> None:
    async with AsyncSessionLocal() as db:
        result = await send_weekly_polls(db, datetime.now(timezone.utc))
        print("RESULT:", result)


if __name__ == "__main__":
    asyncio.run(main())