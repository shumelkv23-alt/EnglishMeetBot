# app/services/week_theme.py
"""Недельная тема: детерминированная ротация курируемых тем.

Единый источник темы недели для вопросов (воскресенье) и карточки занятия
(позже в ту же неделю). Детерминирована по понедельнику недели — без хранения,
без повтора в пределах банка.
"""
from datetime import date

THEME_BANK: list[str] = [
    "Travel and places", "Food and cooking", "Work and career",
    "Technology and AI", "Movies and TV", "Books and reading",
    "Music and concerts", "Hobbies and free time", "Sports and fitness",
    "Friends and relationships", "Family and traditions", "Money and habits",
    "Health and routines", "Learning and education", "Nature and the outdoors",
    "Cities and home", "Dreams and ambitions", "Holidays and festivals",
    "Shopping and brands", "Social media and screens", "Languages and culture",
    "Time and productivity", "Seasons and weather", "Food vs. home cooking",
]


def week_theme(week_start: date) -> str:
    """Тема недели: банк по ISO-номеру недели (без повтора в пределах банка)."""
    return THEME_BANK[week_start.isocalendar().week % len(THEME_BANK)]
