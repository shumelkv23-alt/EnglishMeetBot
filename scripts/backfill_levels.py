# scripts/backfill_levels.py
"""Разовый переспрос уровня у активных профилей с english_level IS NULL.

Запуск: ./venv/Scripts/python -m scripts.backfill_levels
"""
import asyncio

from sqlalchemy import select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import Profile
from app.services.chat_sender import send_message
from app.services.levels import build_level_card


async def main() -> None:
    audience = get_settings().chat_app_audience
    async with AsyncSessionLocal() as db:
        profiles = (
            await db.execute(
                select(Profile).where(
                    Profile.is_active.is_(True),
                    Profile.chat_space_id.isnot(None),
                    Profile.english_level.is_(None),
                )
            )
        ).scalars().all()

    sent = 0
    for p in profiles:
        if not p.workspace_user_id:
            continue
        card = build_level_card(None, audience)
        send_message(
            p.workspace_user_id,
            text="Quick question about your English level 🙂",
            cards_v2=card["cardsV2"],
        )
        sent += 1
    print(f"level prompts sent: {sent}")


if __name__ == "__main__":
    asyncio.run(main())
