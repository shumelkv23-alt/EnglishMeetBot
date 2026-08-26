"""Rotation Engine: выбор типа карточки без повторов (ТЗ §4.3).

Чистая логика (тестируется юнитами): вход — список типов и история использований
группы, выход — выбранный тип по взвешенному случайному выбору. Тип не выпадает
чаще, чем раз в `cooldown` встреч; вес затухает сразу после использования и
восстанавливается со временем.

`history` — список кортежей (card_type_name, created_at), упорядоченный по времени.
"""
import random
from datetime import datetime
from typing import Protocol

HistoryEntry = tuple[str, datetime]


class CardTypeLike(Protocol):
    name: str
    base_weight: float
    cooldown: int


def last_occurrence(name: str, history: list[HistoryEntry]) -> datetime | None:
    """Время последнего использования типа (None — не использовался)."""
    return max((ts for n, ts in history if n == name), default=None)


def meetings_since(last_used: datetime | None, history: list[HistoryEntry]) -> int:
    """Сколько встреч (карточек) прошло после last_used."""
    if last_used is None:
        return 0
    return sum(1 for _, ts in history if ts > last_used)


def compute_weight(card_type: CardTypeLike, history: list[HistoryEntry]) -> float:
    """Вес типа: 0, если ещё на cooldown; иначе base_weight с затуханием."""
    base = card_type.base_weight
    last_used = last_occurrence(card_type.name, history)
    if last_used is None:
        return base
    since = meetings_since(last_used, history)
    if since < card_type.cooldown:
        return 0.0
    decay = min(1.0, since / (card_type.cooldown * 2))
    return base * decay


def select_card_type(
    card_types: list[CardTypeLike], history: list[HistoryEntry], rng=None
) -> CardTypeLike | None:
    """Взвешенный случайный выбор типа; все на cooldown → fallback на base_weight."""
    rng = rng or random
    if not card_types:
        return None
    weights = {t: compute_weight(t, history) for t in card_types}
    # Если все типы на cooldown (не должно случаться при разумном каталоге) — не застреваем.
    if all(w == 0 for w in weights.values()):
        weights = {t: t.base_weight for t in card_types}

    total = sum(weights.values())
    if total <= 0:
        return card_types[0]
    r = rng.random() * total
    acc = 0.0
    for t, w in weights.items():
        acc += w
        if r <= acc:
            return t
    return card_types[-1]
