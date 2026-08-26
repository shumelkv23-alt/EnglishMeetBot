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
    "What's a small thing that always improves your day?",
    "Which app do you use the most and why?",
    "What's something you changed your mind about recently?",
    "Name a food you disliked as a kid but like now.",
    "What's a place you go to clear your head?",
    "If you could instantly learn one skill, which and why?",
    "What's the best purchase you made this year?",
    "Name a tradition from your family you'd like to keep.",
    "What's a film you can rewatch many times?",
    "What would your ideal Sunday look like?",
    "What's something you're looking forward to?",
    "Name a habit you want to build or break.",
    "What's the most useful advice you ever got?",
    "If you could visit one country next month, which?",
    "What's a song that instantly lifts your mood?",
    "Name a small risk that paid off for you.",
    "What's something people often misunderstand about you?",
    "What's a topic you could give a short talk on?",
    "Name a season you love and why.",
    "What's something you'd like to try but haven't yet?",
    "What's a compliment you still remember?",
    "If your day had 25 hours, what would you do with the extra hour?",
    "What's a game you're good at or enjoy?",
    "Name a skill that helped you most at work.",
]


def bank_questions_for(week_start: date) -> list[str]:
    """Два детерминированных вопроса недели (основной + запасной).

    Основной — для всех участников; запасной — используется как замена
    персонального LLM-вопроса, если генерация не удалась (фолбэк REQ-10).
    Индекс — ISO-номер недели по модулю длины банка.
    """
    index = week_start.isocalendar().week % len(BANK)
    return [BANK[index], BANK[(index + 1) % len(BANK)]]