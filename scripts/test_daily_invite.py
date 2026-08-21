# scripts/test_daily_invite.py
"""Создать опрос на сегодня и разослать карточки «Сможешь сегодня прийти?».
Осторожно — шлёт реальные DM тем, у кого есть чат с ботом!"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import AsyncSessionLocal  # noqa: E402
from app.services.poll_store import create_daily_poll_and_broadcast  # noqa: E402


async def main() -> None:
    async with AsyncSessionLocal() as db:
        result = await create_daily_poll_and_broadcast(db)
        print(result)


if __name__ == "__main__":
    asyncio.run(main())
