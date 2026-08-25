"""Ручной запуск проверки квоты на сегодня (для проверки без ожидания cron).

Запуск: .\venv\Scripts\python -m scripts.check_quorum_now
"""
import asyncio

from app.scheduler import _check_today_quorum


async def main() -> None:
    await _check_today_quorum()
    print("проверка квоты выполнена")


if __name__ == "__main__":
    asyncio.run(main())
