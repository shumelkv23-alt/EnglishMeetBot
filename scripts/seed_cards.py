"""Ручной сид движка карточек: каталог типов + контент-банк.

Запуск: ./venv/Scripts/python -m scripts.seed_cards
"""
import asyncio

from app.cards.seed import seed
from app.database import AsyncSessionLocal


async def main() -> None:
    async with AsyncSessionLocal() as db:
        result = await seed(db)
        print("seeded:", result)


if __name__ == "__main__":
    asyncio.run(main())
