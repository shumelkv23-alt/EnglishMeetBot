"""Банк лёгких разговорных вопросов для еженедельного опроса.

Банк — fallback для LLM-вопросов (REQ-10) и источник «общего» вопроса
в карточке. Вопросы детерминированы неделей: никакого состояния в БД не нужно.
"""
from datetime import date

BANK: list[str] = [
    "What movie or series would you rewatch?",
    "What sweet treat reminds you of childhood?",
    "Name a place you'd love to go back to.",
    "What book changed the way you think about something?",
    "What do you usually cook when you have dinner alone?",
    "What hobby would you like to pick up, and why?",
    "What's the most surprising thing you learned this week?",
    "What skill helped you the most recently?",
    "If you could have lunch with a famous person — who would it be?",
    "What would you take to a desert island besides your phone?",
    "What song has been stuck in your head lately?",
    "Which trip do you remember most, and why?",
    "What's your favorite way to relax after work?",
    "What talent would you like to gain overnight?",
    "What gets you out of bed in the morning?",
    "What word or phrase from another language do you use often?",
    "What would you teach a foreigner to do really well?",
    "What game or sport do you enjoy the most, and why?",
    "Name one habit you're proud of.",
    "What topic could you talk about for hours?",
]


def bank_questions_for(week_start: date, exclude: set[str] | None = None) -> list[str]:
    """Два вопроса недели (основной + запасной), не пересекающиеся с `exclude`.

    Основной — для всех участников; запасной — как замена персонального
    LLM-вопроса (фолбэк REQ-10). Индекс — ISO-номер недели по модулю длины
    банка. `exclude` — уже заданные участнику вопросы: их пропускаем, идя по
    банку вперёд от детерминированного индекса.
    """
    exclude = exclude or set()
    index = week_start.isocalendar().week % len(BANK)
    result: list[str] = []
    for offset in range(len(BANK)):
        q = BANK[(index + offset) % len(BANK)]
        if q not in exclude and q not in result:
            result.append(q)
        if len(result) >= 2:
            break
    # Если исключён весь банк (маловероятно) — добиваем из начала без повторов.
    if len(result) < 2:
        for q in BANK:
            if q not in result:
                result.append(q)
            if len(result) >= 2:
                break
    return result
