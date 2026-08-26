"""Ручная рассылка вопросов недели (без ожидания cron Sunday 11:00).

Запуск: ./venv/Scripts/python -m scripts.send_questions_now
"""
import asyncio

from app.database import AsyncSessionLocal
from app.services.weekly_questions import send_weekly_questions


async def main() -> None:
    async with AsyncSessionLocal() as db:
        sent = await send_weekly_questions(db)
        print(f"вопросы недели разосланы: {sent}")


if __name__ == "__main__":
    asyncio.run(main())
