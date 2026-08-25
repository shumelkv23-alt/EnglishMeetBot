"""Ручная отправка недельного опроса (для проверки без ожидания cron).

Запуск: .\venv\Scripts\python -m scripts.send_poll_now
"""
import asyncio

from app.database import AsyncSessionLocal
from app.services.weekly_poll import ensure_weekly_poll, send_weekly_poll_card


async def main() -> None:
    async with AsyncSessionLocal() as db:
        poll = await ensure_weekly_poll(db)
        print("poll:", poll.id, poll.status)
        await send_weekly_poll_card(db, poll)
        print("message_name:", poll.card_message_name)


if __name__ == "__main__":
    asyncio.run(main())
