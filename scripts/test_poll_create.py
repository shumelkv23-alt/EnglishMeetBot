# scripts/test_poll_create.py
"""Создать недельный опрос (следующая неделя) и разослать карточки.
Осторожно — шлёт реальные сообщения тем, у кого есть DM с ботом!"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import AsyncSessionLocal  # noqa: E402
from app.services.poll_store import create_weekly_poll_and_broadcast  # noqa: E402


async def main() -> None:
    async with AsyncSessionLocal() as db:
        result = await create_weekly_poll_and_broadcast(db)
        print(result)


if __name__ == "__main__":
    asyncio.run(main())
