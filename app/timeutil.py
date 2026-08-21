# app/timeutil.py
"""Единая точка «сейчас»/«сегодня» в таймзоне бота (config.app_tz).

Раньше часть кода брала date.today() (локальное время машины), а часть —
datetime.now(timezone.utc). Это давало рассинхрон на сутки. Теперь всё
идёт через app_now()/app_today(), чтобы «сегодня» в запрете прошедших
дней, создании опроса и ежедневной проверке совпадали.
"""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.config import get_settings


def app_now() -> datetime:
    """Текущее время в таймзоне бота (aware)."""
    return datetime.now(ZoneInfo(get_settings().app_tz))


def app_today() -> date:
    """Сегодняшняя дата в таймзоне бота."""
    return app_now().date()
