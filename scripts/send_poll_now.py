"""Ручная отправка недельного опроса (для проверки без ожидания cron).

Запуск: .\venv\Scripts\python -m scripts.send_poll_now
"""
import asyncio

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.services.chat_sender import send_message as send_space_message
from app.services.weekly_poll import (
    build_weekly_poll_card,
    ensure_weekly_poll,
    get_or_create_config,
    poll_counts,
)


async def main() -> None:
    async with AsyncSessionLocal() as db:
        poll = await ensure_weekly_poll(db)
        space_id = (await get_or_create_config(db, "space_id", "")).value or ""
        print("poll:", poll.id, poll.status)
        if space_id:
            days, times, counts = await poll_counts(db, poll.id)
            card = build_weekly_poll_card(days, times, get_settings().chat_app_audience, counts)
            send_space_message(
                space_id,
                text="When can you meet this week? 🗓️",
                cards_v2=card.get("cardsV2"),
            )
            print("отправлено в", space_id)
        else:
            print("space_id не задан — карточку отправить некуда")


if __name__ == "__main__":
    asyncio.run(main())
