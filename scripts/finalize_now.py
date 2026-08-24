"""Запустить финализацию опроса дня прямо сейчас (как cron 14:05).

Создаёт встречи для времён, набравших кворум, и рассылает приглашения:
личные DM ответившим + пост в группу (handle_time_finalized). Джобы
напоминания/чек-ина в этом процессе не ставятся — они живут в шедулере
приложения (здесь scheduler = None).

Запуск: ./venv/Scripts/python -m scripts.finalize_now
"""
import asyncio

from app.scheduler import _finalize_daily_poll


async def main() -> None:
    await _finalize_daily_poll()
    print("finalize done")


if __name__ == "__main__":
    asyncio.run(main())
