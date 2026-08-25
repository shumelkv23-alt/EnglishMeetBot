"""Брифинг встречи (тема + дискуссионные тезисы + свежие новости, на английском).

Отдельный модуль: генерация через LLM (`generator`) и оркестрация
сбор/отправка/расписание (`briefing`).
"""
from app.services.briefing.briefing import (
    briefing_at,
    briefing_job_id,
    build_briefing_card,
    restore_briefings_on_startup,
    schedule_briefing_for_meeting,
    send_briefing,
)
from app.services.briefing.generator import generate_briefing

__all__ = [
    "briefing_at",
    "briefing_job_id",
    "build_briefing_card",
    "generate_briefing",
    "restore_briefings_on_startup",
    "schedule_briefing_for_meeting",
    "send_briefing",
]
