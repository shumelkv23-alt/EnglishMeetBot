"""Ручная генерация и отправка карточки занятия (без ожидания T−1ч).

Запуск: ./venv/Scripts/python -m scripts.send_card_now [meeting_id]
  meeting_id — id встречи. По умолчанию последняя запланированная встреча.
"""
import asyncio
import sys

from sqlalchemy import select

from app.cards.service import send_card
from app.database import AsyncSessionLocal
from app.models import MeetingInstance


async def main() -> None:
    meeting_id = sys.argv[1] if len(sys.argv) > 1 else None

    if meeting_id is None:
        async with AsyncSessionLocal() as db:
            m = (
                await db.execute(
                    select(MeetingInstance).order_by(MeetingInstance.id.desc()).limit(1)
                )
            ).scalars().first()
            meeting_id = str(m.id) if m else None

    if not meeting_id:
        print("нет встречи — сначала scripts.finalize_day_now")
        return

    await send_card(meeting_id)
    print(f"карточка занятия отправлена для встречи {meeting_id}")


if __name__ == "__main__":
    asyncio.run(main())
