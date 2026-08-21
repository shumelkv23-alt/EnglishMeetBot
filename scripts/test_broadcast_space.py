# scripts/test_broadcast_space.py
"""Рассылка участникам space (в их DM, если он есть в profiles).

Осторожно — шлёт реально! Space указывается аргументом или CHAT_TEST_SPACE.
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.database import AsyncSessionLocal  # noqa: E402
from app.services.broadcast import broadcast_to_space_members  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser(description="Broadcast to members of a space")
    parser.add_argument("--space", help="Space name, e.g. spaces/XXXX")
    args = parser.parse_args()

    space = args.space or get_settings().chat_test_space
    if not space:
        raise SystemExit("Space not specified: pass --space or set CHAT_TEST_SPACE in .env")

    async with AsyncSessionLocal() as db:
        result = await broadcast_to_space_members(
            db,
            space,
            "Привет! Это тестовая рассылка участникам нашего пространства. 🎉",
        )
        print(result)


if __name__ == "__main__":
    asyncio.run(main())