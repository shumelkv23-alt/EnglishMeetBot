# scripts/test_broadcast_writers.py
"""Рассылка всем, кто писал боту (profiles с chat_space_id). Осторожно — шлёт реально!"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import AsyncSessionLocal  # noqa: E402
from app.services.broadcast import broadcast_to_writers  # noqa: E402


async def main() -> None:
    async with AsyncSessionLocal() as db:
        result = await broadcast_to_writers(
            db,
            "Привет! Это тестовая рассылка всем, кто писал EnglishMeetBot. 🎉",
        )
        print(result)


if __name__ == "__main__":
    asyncio.run(main())