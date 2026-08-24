"""Демо: бот присылает карточку ежедневного опроса (кнопки времени + «не могу»).

Запуск: .\venv\Scripts\python -m scripts.demo_poll_card
"""
import asyncio
from datetime import datetime, timezone

from sqlalchemy import delete, select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import PollSlot, PollVote, PollResponse, DailyPoll
from app.services.chat_sender import send_message
from app.services.weekly_poll import build_daily_poll_card, ensure_daily_poll


async def main() -> None:
    async with AsyncSessionLocal() as db:
        # Удалить опрос дня, чтобы ensure создал новый со слотами из config['daily_slots']
        today = datetime.now(timezone.utc).date()
        old = (await db.execute(
            select(DailyPoll).where(DailyPoll.poll_date == today)
        )).scalar_one_or_none()
        if old is not None:
            await db.execute(delete(PollVote).where(
                PollVote.poll_slot_id.in_(select(PollSlot.id).where(PollSlot.poll_id == old.id))
            ))
            await db.execute(delete(PollSlot).where(PollSlot.poll_id == old.id))
            await db.execute(delete(PollResponse).where(PollResponse.poll_id == old.id))
            await db.execute(delete(DailyPoll).where(DailyPoll.id == old.id))
            await db.commit()

        poll = await ensure_daily_poll(db)
        slots = [
            s.slot_start.strftime("%H:%M") for s in (
                await db.execute(select(PollSlot).where(PollSlot.poll_id == poll.id).order_by(PollSlot.slot_start))
            ).scalars().all()
        ]
        print("poll:", poll.id, "slots:", slots)

        card = build_daily_poll_card(slots, get_settings().chat_app_audience)
        space = get_settings().chat_test_space
        if not space:
            print("NO chat_test_space — задай chat_test_space в .env")
            return
        result = send_message(space, text="Кто сегодня и во сколько? 🗓️", cards_v2=card["cardsV2"])
        print("sent:", result.get("name"))


if __name__ == "__main__":
    asyncio.run(main())
