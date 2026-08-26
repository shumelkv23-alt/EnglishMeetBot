"""Activity Matcher: подбор активности по теме карточки (ТЗ §4.6).

Реестр существующих групповых игр с `topic_tags`. Совпадение — по ключевым
словам в теме; при отсутствии совпадений — случайная групповая игра.
"""
import random

# Реестр групповых игр бота (6 штук) с тэгами тем.
GAMES: list[dict] = [
    {"activity_id": "alias", "name": "Alias", "activity_type": "group_game",
     "tags": ["word", "words", "vocabulary", "describe", "explain", "language"]},
    {"activity_id": "snake_oil", "name": "Snake Oil", "activity_type": "group_game",
     "tags": ["creative", "funny", "persuade", "sell", "invent", "idea"]},
    {"activity_id": "quiplash", "name": "Quiplash", "activity_type": "group_game",
     "tags": ["funny", "creative", "quick", "witty", "joke", "answer"]},
    {"activity_id": "who_am_i", "name": "Who am I?", "activity_type": "group_game",
     "tags": ["guess", "people", "character", "famous", "person", "yes/no"]},
    {"activity_id": "spy", "name": "Spy", "activity_type": "group_game",
     "tags": ["deduction", "question", "mystery", "bluff", "secret", "detective"]},
    {"activity_id": "guesspionage", "name": "Guesspionage", "activity_type": "group_game",
     "tags": ["guess", "statistics", "survey", "number", "percent", "predict"]},
]

_GAME_BY_ID = {g["activity_id"]: g for g in GAMES}


def game_by_id(activity_id: str) -> dict | None:
    """Игра по activity_id (для Game Day, где активность — центр карточки)."""
    return _GAME_BY_ID.get(activity_id)


def match_activity(topic: str, rng: random.Random | None = None) -> dict:
    """Подобрать активность по теме (совпадение topic_tags) или случайную."""
    rng = rng or random
    lowered = topic.lower()
    best: dict | None = None
    best_score = 0
    for g in GAMES:
        score = sum(1 for tag in g["tags"] if tag in lowered)
        if score > best_score:
            best = g
            best_score = score
    if best is None:
        best = rng.choice(GAMES)
    return {
        "activity_id": best["activity_id"],
        "activity_type": best["activity_type"],
        "relevance_reason": f"matched {best_score} topic tag(s)",
    }
