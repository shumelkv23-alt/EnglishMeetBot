"""Переоткрыть опрос дня и отправить карточку голосования (для теста).

Возвращает сегодняшний опрос в active (снимает closed_at) и шлёт карточку
с актуальными счётчиками в группу, чтобы проверить живое обновление.

Запуск: ./venv/Scripts/python -m scripts.demo_vote
"""
import asyncio
from datetime import datetime, timezone

from sqlalchemy import select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import DailyPoll
from app.services.chat_sender import send_message as send_space_message
from app.services.weekly_poll import build_daily_poll_card_with_counts, get_or_create_config


async def main() -> None:
    async with AsyncSessionLocal() as db:
        today = datetime.now(timezone.utc).date()
        poll = (
            await db.execute(select(DailyPoll).where(DailyPoll.poll_date == today))
        ).scalar_one_or_none()
        if poll is None:
            print("NO_POLL — нет опроса на сегодня")
            return

        # переоткрыть: снова active, снять closed_at
        poll.status = "active"
        poll.closed_at = None
        await db.commit()

        space_id = (await get_or_create_config(db, "space_id", "")).value or ""
        if not space_id:
            print("NO_SPACE — space_id не задан")
            return

        card = await build_daily_poll_card_with_counts(db, poll, get_settings().chat_app_audience)
        send_space_message(
            space_id,
            text="Кто сегодня и во сколько? 🗓️",
            cards_v2=card.get("cardsV2"),
        )
        print(f"OK poll={poll.id} card sent to {space_id}")


if __name__ == "__main__":
    asyncio.run(main())
