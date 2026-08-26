# scripts/wipe_db.py
"""Полная очистка БД (все таблицы) + пересид движка карточек.

Для чистого ручного прогона: стирает профили, опросы, встречи, игры, конфиг.
После очистки config["space_id"] пуст — бот подхватит новую группу при добавлении.

Запуск: ./venv/Scripts/python -m scripts.wipe_db
"""
import asyncio

from sqlalchemy import text

import app.cards.models  # noqa: F401  — регистрирует card_types/cards/content_bank
import app.models  # noqa: F401  — регистрирует остальные таблицы
from app.cards.seed import seed
from app.database import AsyncSessionLocal, Base


async def main() -> None:
    tables = Base.metadata.sorted_tables
    names = ", ".join(f'"{t.name}"' for t in tables)
    async with AsyncSessionLocal() as db:
        await db.execute(text(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE"))
        await db.commit()
        await seed(db)
    print(f"БД очищена ({len(tables)} таблиц), движок карточек перезасеян.")


if __name__ == "__main__":
    asyncio.run(main())
