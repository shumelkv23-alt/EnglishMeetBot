"""Ручная отправка ежедневного опроса (для проверки без ожидания cron).

Запуск: .\venv\Scripts\python -m scripts.send_poll_now
"""
import asyncio
from datetime import datetime, timezone

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.messaging import send_message
from app.schemas import MessagePayload
from app.services.weekly_poll import build_daily_poll_card, ensure_daily_poll, get_or_create_config


async def main() -> None:
    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)
        poll = await ensure_daily_poll(db, now)
        space_id = (await get_or_create_config(db, "space_id", "")).value or ""
        print("poll:", None if poll is None else (poll.id, poll.status))
        if poll is not None and space_id:
            slots = ["15:00", "16:00", "17:00"]
            send_message(space_id, MessagePayload(
                text="Кто сегодня и во сколько? 🗓️",
                card=build_daily_poll_card(slots, get_settings().chat_app_audience),
            ))
        else:
            print("space_id не задан — карточку отправить некуда")


if __name__ == "__main__":
    asyncio.run(main())
