"""Банк слов и подсказок для игры «Кроссворд» (fallback, когда LLM недоступен).

Каждое слово — обычное английское существительное/глагол 3–8 букв. Подбор слов
сделан так, чтобы у них было много общих букв (a, e, t, r, s, o, n, l) — так
локальный решатель почти всегда собирает пересекающуюся сетку без LLM.
"""
import random

_WORDS: list[dict] = [
    {"word": "cat", "clue": "A small furry pet that purrs"},
    {"word": "dog", "clue": "Man's best friend"},
    {"word": "sun", "clue": "It shines in the sky by day"},
    {"word": "sea", "clue": "A huge body of salt water"},
    {"word": "car", "clue": "A vehicle with four wheels"},
    {"word": "house", "clue": "A place where people live"},
    {"word": "apple", "clue": "A red or green fruit"},
    {"word": "table", "clue": "Furniture you eat at"},
    {"word": "train", "clue": "It runs on rails"},
    {"word": "green", "clue": "The color of grass"},
    {"word": "river", "clue": "Water flowing to the sea"},
    {"word": "music", "clue": "Sounds you listen to"},
    {"word": "bread", "clue": "Baked food made of flour"},
    {"word": "sleep", "clue": "What you do at night"},
    {"word": "storm", "clue": "Bad weather with wind and rain"},
    {"word": "smile", "clue": "A happy expression on a face"},
]


def random_crossword_words(count: int) -> list[dict]:
    """Случайная выборка из банка (без повторов). `count` слов или меньше, если банк мал."""
    items = list(_WORDS)
    random.shuffle(items)
    return [dict(w) for w in items[:count]]
