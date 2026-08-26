"""Ручная отправка недельной таблицы дней × времён (без ожидания cron).

Запуск: .\venv\Scripts\python -m scripts.send_weekly_table
"""
import asyncio

from app.database import AsyncSessionLocal
from app.services.weekly_availability import ensure_weekly_poll, post_or_refresh_weekly_table


async def main() -> None:
    async with AsyncSessionLocal() as db:
        poll = await ensure_weekly_poll(db)
        print("poll:", poll.id, poll.week_start, poll.status)
        resp = await post_or_refresh_weekly_table(
            db, poll, text="Кто в какие дни на этой неделе? 🗓️",
        )
        print("sent:", None if resp is None else resp.get("name"))


if __name__ == "__main__":
    asyncio.run(main())
