"""Ручной запуск рассылки подтверждений явки для указанного дня.

Запуск: .\venv\Scripts\python -m scripts.send_confirmation_now [day]
  day — индекс дня (0=Mon .. 6=Sun). По умолчанию 1 (вторник, «понедельник вечером»).
"""
import asyncio
import sys
from datetime import datetime, time, timedelta

from app.scheduler import _send_day_confirmations
from app.services.weekly_poll import week_monday


async def main() -> None:
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    # симулируем «сейчас 18:00 накануне» целевого дня
    monday = week_monday()
    now = datetime.combine(monday + timedelta(days=target - 1), time(18, 0))
    await _send_day_confirmations(now=now)
    print(f"подтверждения разосланы (симуляция: завтра = день {target})")


if __name__ == "__main__":
    asyncio.run(main())
