"""Каталог типов карточек (ТЗ §4.1): 12 форматов с весами и safety tier.

Каталог — источник истины для сида таблицы `card_types` и фолбэк, если
таблица пуста. Слаг (name) совпадает со значениями `card_type` из ТЗ §4.2.
"""
from typing import TypedDict


class CardTypeSpec(TypedDict, total=False):
    name: str
    description: str
    min_group_size: int
    max_group_size: int | None
    cefr_min: str
    cefr_max: str
    base_weight: float
    cooldown: int
    safety_tier: int


# safety_tier: 1 — всегда безопасно; 2 — требует модерации (только из content_bank).
CARD_TYPES: list[CardTypeSpec] = [
    {"name": "topic", "description": "Open question + 3 sub-questions of increasing difficulty",
     "min_group_size": 2, "max_group_size": None, "cefr_min": "A2", "cefr_max": "C1",
     "base_weight": 1.0, "cooldown": 3, "safety_tier": 1},
    {"name": "debate", "description": "Safe controversial statement, for/against sides",
     "min_group_size": 4, "max_group_size": None, "cefr_min": "B1", "cefr_max": "C1",
     "base_weight": 1.0, "cooldown": 3, "safety_tier": 2},
    {"name": "storytelling", "description": "Add a sentence to a shared story in turns",
     "min_group_size": 3, "max_group_size": None, "cefr_min": "A2", "cefr_max": "B2",
     "base_weight": 1.0, "cooldown": 3, "safety_tier": 1},
    {"name": "would_you_rather", "description": "Dilemma of 2 options + justify your choice",
     "min_group_size": 2, "max_group_size": None, "cefr_min": "A1", "cefr_max": "B1",
     "base_weight": 1.0, "cooldown": 3, "safety_tier": 1},
    {"name": "roleplay", "description": "Everyday situation + roles",
     "min_group_size": 2, "max_group_size": None, "cefr_min": "A2", "cefr_max": "B2",
     "base_weight": 1.0, "cooldown": 3, "safety_tier": 1},
    {"name": "culture", "description": "Idiom/cultural fact + compare with your own culture",
     "min_group_size": 2, "max_group_size": None, "cefr_min": "B1", "cefr_max": "C1",
     "base_weight": 1.0, "cooldown": 3, "safety_tier": 1},
    {"name": "hot_seat", "description": "One participant answers a series of group questions",
     "min_group_size": 3, "max_group_size": None, "cefr_min": "A2", "cefr_max": "C1",
     "base_weight": 1.0, "cooldown": 3, "safety_tier": 1},
    {"name": "game_day", "description": "Short warm-up before one of the group games",
     "min_group_size": 2, "max_group_size": None, "cefr_min": "A1", "cefr_max": "C1",
     "base_weight": 1.0, "cooldown": 3, "safety_tier": 1},
    {"name": "two_truths", "description": "Share 3 facts about yourself, group guesses the lie",
     "min_group_size": 3, "max_group_size": None, "cefr_min": "A2", "cefr_max": "B2",
     "base_weight": 1.0, "cooldown": 3, "safety_tier": 1},
    {"name": "mystery", "description": "Random topic from the box, no warning in advance",
     "min_group_size": 2, "max_group_size": None, "cefr_min": "B1", "cefr_max": "C1",
     "base_weight": 1.0, "cooldown": 3, "safety_tier": 1},
    {"name": "news_reaction", "description": "Neutral news from a safe pool + reaction",
     "min_group_size": 2, "max_group_size": None, "cefr_min": "B2", "cefr_max": "C1",
     "base_weight": 1.0, "cooldown": 3, "safety_tier": 2},
    {"name": "time_capsule", "description": "Imagine 10 years from now / 10 years ago",
     "min_group_size": 2, "max_group_size": None, "cefr_min": "A2", "cefr_max": "B2",
     "base_weight": 1.0, "cooldown": 3, "safety_tier": 1},
]

CARD_TYPE_NAMES = [t["name"] for t in CARD_TYPES]

# Типы, контент которых генерится только из промодерированного content_bank (ТЗ §4.7).
BANK_ONLY_TYPES = frozenset({"debate", "news_reaction"})
