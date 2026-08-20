"""Демо: бот присылает карточку еженедельного опроса (вопрос + слоты времени).

Отправляет реальную Cards V2-карточку в CHAT_TEST_SPACE из .env.
Запуск: .\venv\Scripts\python -m scripts.demo_poll_card
"""
import asyncio
from datetime import datetime, timezone

from sqlalchemy import select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import PollSlot
from app.services.chat_sender import send_message
from app.services.llm_questions import generate_personal_question
from app.services.onboarding import get_or_create_profile
from app.services.question_bank import bank_questions_for
from app.services.weekly_poll import build_poll_card, ensure_weekly_poll


async def main() -> None:
    async with AsyncSessionLocal() as db:
        poll = await ensure_weekly_poll(db, datetime.now(timezone.utc))

        bank_q1, bank_q2 = bank_questions_for(poll.week_start)

        profile = await get_or_create_profile(
            db, "users/111473858428808568928", display_name="Кирилл"
        )
        interests = list(profile.interests or [])
        personal_q = generate_personal_question(interests) or bank_q2
        print("personal_q:", personal_q)

        slots = (
            await db.execute(select(PollSlot).where(PollSlot.poll_id == poll.id).order_by(PollSlot.slot_start))
        ).scalars().all()
        slot_labels = [
            {"id": s.id, "label": f"{s.slot_start.strftime('%a')} {s.slot_start.strftime('%H:%M')}"}
            for s in slots
        ]
        print("slot_labels:", slot_labels)

        card = build_poll_card(personal_q, bank_q1, slot_labels)
        space = get_settings().chat_test_space
        result = send_message(space, text="Еженедельный опрос 🗓️", cards_v2=card["cardsV2"])
        print("sent:", result.get("name"))


if __name__ == "__main__":
    asyncio.run(main())