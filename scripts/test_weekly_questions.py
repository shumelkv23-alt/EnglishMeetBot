"""Проверка генерации вопросов недели для первого профиля (без LLM-ключа — банк)."""
import asyncio

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import Profile
from app.services.weekly_questions import weekly_questions_for


async def main() -> None:
    async with AsyncSessionLocal() as db:
        profile = (
            await db.execute(select(Profile).order_by(Profile.id).limit(1))
        ).scalar_one_or_none()
        if profile is None:
            print("NO_PROFILE")
            return
        print("profile:", profile.id, "interests=", profile.interests, "level=", profile.english_level)
        questions = await weekly_questions_for(db, profile)
        print("questions:")
        for q in questions:
            print(" -", q)
        assert len(questions) == 2


if __name__ == "__main__":
    asyncio.run(main())
