"""Ручная отправка ежедневного опроса (для проверки без ожидания cron).

Запуск: .\venv\Scripts\python -m scripts.send_poll_now
"""
import asyncio
from datetime import datetime, timezone

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.services.chat_sender import send_message as send_space_message
from app.services.weekly_poll import build_daily_poll_card, ensure_daily_poll, get_or_create_config


async def main() -> None:
    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)
        poll = await ensure_daily_poll(db, now)
        space_id = (await get_or_create_config(db, "space_id", "")).value or ""
        print("poll:", None if poll is None else (poll.id, poll.status))
        if poll is not None and space_id:
            slots = ["15:00", "16:00", "17:00"]
            card = build_daily_poll_card(slots, get_settings().chat_app_audience)
            send_space_message(
                space_id,
                text="Кто сегодня и во сколько? 🗓️",
                cards_v2=card.get("cardsV2"),
            )
        else:
            print("space_id не задан — карточку отправить некуда")


if __name__ == "__main__":
    asyncio.run(main())
