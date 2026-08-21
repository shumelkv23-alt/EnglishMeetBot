# scripts/test_daily_finalize.py
"""Принудительная финализация сегодняшнего опроса (не дожидаясь 13:00).

Показывает, какие слоты набрали кворум и какие встречи созданы.
Осторожно — реально пишет анонсы в группу и возвращает напоминания!
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import AsyncSessionLocal  # noqa: E402
from app.services.poll_store import finalize_today  # noqa: E402
from app.timeutil import app_now  # noqa: E402


async def main() -> None:
    now = app_now()
    async with AsyncSessionLocal() as db:
        outcome = await finalize_today(db, now)
        # Читаем поля ДО закрытия сессии (после commit объекты expire).
        meetings = [
            (
                m.scheduled_start.isoformat(),
                m.scheduled_end.isoformat(),
                m.location,
            )
            for m in outcome["meetings"]
        ]
        reminders = [
            (r.send_at.isoformat(), list(r.recipients))
            for r in outcome["reminders"]
        ]

    print("meetings:", len(meetings))
    for start, end, loc in meetings:
        print(" -", start, "->", end, loc)
    print("reminders:", len(reminders))
    for send_at, recips in reminders:
        print(" - at", send_at, "->", recips)


if __name__ == "__main__":
    asyncio.run(main())
