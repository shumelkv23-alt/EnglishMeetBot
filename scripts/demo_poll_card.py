"""Демо: бот присылает обновлённую карточку опроса (Пн-Пт + читаемые вопросы).

Запуск: .\venv\Scripts\python -m scripts.demo_poll_card
"""
import asyncio
from datetime import datetime, timezone

from sqlalchemy import delete, select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import Config, PollSlot, PollVote, PollResponse, DailyPoll
from app.services.chat_sender import send_message
from app.services.llm_questions import generate_personal_question
from app.services.onboarding import get_or_create_profile, current_week_start
from app.services.question_bank import bank_questions_for
from app.services.weekly_poll import build_poll_card, ensure_weekly_poll


async def main() -> None:
    async with AsyncSessionLocal() as db:
        # Удалить старый опрос недели, чтобы ensure создал новый со слотами Пн-Пт
        old = (await db.execute(
            select(DailyPoll).where(DailyPoll.week_start == current_week_start())
        )).scalar_one_or_none()
        if old is not None:
            await db.execute(delete(PollVote).where(
                PollVote.poll_slot_id.in_(select(PollSlot.id).where(PollSlot.poll_id == old.id))
            ))
            await db.execute(delete(PollSlot).where(PollSlot.poll_id == old.id))
            await db.execute(delete(PollResponse).where(PollResponse.poll_id == old.id))
            await db.execute(delete(DailyPoll).where(DailyPoll.id == old.id))
            await db.commit()

        # Очистить конфиг слотов, чтобы ensure_weekly_poll создал дефолтные Пн-Пт
        cfg = (await db.execute(select(Config).where(Config.key == "poll_slots"))).scalar_one_or_none()
        if cfg is not None:
            cfg.value = []
            await db.commit()

        poll = await ensure_weekly_poll(db, datetime.now(timezone.utc))

        bank_q1, bank_q2 = bank_questions_for(poll.week_start)

        profile = await get_or_create_profile(
            db, "users/111473858428808568928", display_name="Кирилл"
        )
        interests = list(profile.interests or [])
        personal_q = generate_personal_question(interests) or bank_q2

        slots = (
            await db.execute(select(PollSlot).where(PollSlot.poll_id == poll.id).order_by(PollSlot.slot_start))
        ).scalars().all()
        slot_labels = [
            {"id": s.id, "label": s.slot_start.strftime("%a")}
            for s in slots
        ]
        print("slots:", slot_labels)
        print("personal_q:", personal_q[:60] + "..." if len(personal_q) > 60 else personal_q)

        card = build_poll_card(personal_q, bank_q1, slot_labels)
        space = get_settings().chat_test_space
        result = send_message(space, text="Еженедельный опрос 🗓️", cards_v2=card["cardsV2"])
        print("sent:", result.get("name"))


if __name__ == "__main__":
    asyncio.run(main())