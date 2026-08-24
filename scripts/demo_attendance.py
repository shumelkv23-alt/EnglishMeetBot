"""Демо-проверка: встреча через ~10 минут + карточка чек-ина сразу в группу.

Позволяет проверить цепочку «Я на встрече ✅ → +3 балла → команда "топ"»,
не дожидаясь cron и окна настоящей встречи.

Запуск: ./venv/Scripts/python -m scripts.demo_attendance
"""
import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import DailyPoll, MeetingInstance as MeetingORM, PollSlot
from app.services.checkin import build_checkin_card
from app.services.chat_sender import send_message as send_space_message
from app.services.weekly_poll import get_or_create_config


async def main() -> None:
    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)
        # Для встречи нужен существующий poll_id + slot_id — берём последний опрос
        poll = (
            await db.execute(select(DailyPoll).order_by(DailyPoll.id.desc()).limit(1))
        ).scalar_one_or_none()
        if poll is None:
            print("NO_POLL — сначала запусти ./venv/Scripts/python -m scripts.send_poll_now")
            return
        slot = (
            await db.execute(select(PollSlot).where(PollSlot.poll_id == poll.id).limit(1))
        ).scalar_one_or_none()
        if slot is None:
            print("NO_SLOTS — нет слотов у опроса, что-то не так")
            return

        # Встреча через 10 минут: окно чек-ина [start-15м, start+15м] уже открыто
        scheduled_start = now + timedelta(minutes=10)
        meeting = MeetingORM(
            poll_id=poll.id,
            selected_slot_id=slot.id,
            scheduled_start=scheduled_start,
            scheduled_end=scheduled_start + timedelta(minutes=60),
            location="Онлайн (Meet)",
            status="scheduled",
        )
        db.add(meeting)
        await db.flush()  # присвоить id до commit (иначе async expiry)
        meeting_id = meeting.id
        await db.commit()

        space_id = (await get_or_create_config(db, "space_id", "")).value or ""
        card = build_checkin_card(str(meeting_id), get_settings().chat_app_audience)
        send_space_message(
            space_id,
            text="Встреча начинается — отметься! ✅",
            cards_v2=card.get("cardsV2"),
        )
        print(f"OK: встреча id={meeting_id}, карточка отправлена в группу {space_id}")
        print("Нажми «Я на встрече ✅» в течение ~25 минут, затем напиши «топ».")


if __name__ == "__main__":
    asyncio.run(main())
