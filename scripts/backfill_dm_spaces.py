# scripts/backfill_dm_spaces.py
"""Заполнить chat_space_id у профилей без DM, найдя их через Chat API.

Запуск: .\\venv\\Scripts\\python -m scripts.backfill_dm_spaces
"""
import asyncio
import logging

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import Profile
from app.services.chat_sender import find_user_dm_space

logging.basicConfig(level=logging.INFO)


async def main() -> None:
    async with AsyncSessionLocal() as db:
        profiles = (
            await db.execute(select(Profile).where(Profile.chat_space_id.is_(None)))
        ).scalars().all()
        if not profiles:
            print("Нет профилей без chat_space_id.")
            return
        for profile in profiles:
            space = find_user_dm_space(profile.workspace_user_id or "")
            if space:
                profile.chat_space_id = space
                print(f"{profile.user_name}: DM = {space}")
            else:
                print(f"{profile.user_name}: DM не найден")
        await db.commit()


if __name__ == "__main__":
    asyncio.run(main())