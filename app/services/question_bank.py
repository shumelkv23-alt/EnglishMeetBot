"""Банк лёгких разговорных вопросов для еженедельного опроса.

Банк — fallback для LLM-вопросов (REQ-10) и источник «общего» вопроса
в карточке. Вопросы детерминированы неделей: никакого состояния в БД не нужно.
"""
from datetime import date

BANK: list[str] = [
    "What movie or series would you rewatch?",
    "What treat reminds you of your childhood?",
    "Name a place you'd love to return to.",
    "What book changed how you see something?",
    "What do you usually cook when dining alone?",
    "What hobby would you like to pick up and why?",
    "Name the most surprising thing you learned this week.",
    "What skill helped you the most recently?",
    "If you could have lunch with a famous person — who would it be?",
    "What would you take to a desert island besides your phone?",
    "What song has been stuck in your head lately?",
    "What trip do you remember most and why?",
    "Name your favorite way to unwind after work.",
    "What talent would you like to gain in one day?",
    "What motivates you to get up in the morning?",
    "What word or phrase do you often use from another language?",
    "What would you teach a foreigner to do really well?",
    "What game or sport do you enjoy the most and why?",
    "Name one habit you're proud of.",
    "What topic can you discuss for hours on end?",
]


def bank_questions_for(week_start: date) -> list[str]:
    """Два детерминированных вопроса недели (основной + запасной).

    Основной — для всех участников; запасной — используется как замена
    персонального LLM-вопроса, если генерация не удалась (фолбэк REQ-10).
    Индекс — ISO-номер недели по модулю длины банка.
    """
    index = week_start.isocalendar().week % len(BANK)
    return [BANK[index], BANK[(index + 1) % len(BANK)]]