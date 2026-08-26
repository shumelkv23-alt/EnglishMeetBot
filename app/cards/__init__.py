"""Движок генерации и разнообразия карточек занятий (ТЗ card_diversity_tz.md).

Отдельный модуль: ротация типов, генерация контента (шаблон + LLM),
подбор активности, валидация и оркестрация пайплайна.
"""
from app.cards.catalog import CARD_TYPES, CARD_TYPE_NAMES
from app.cards.rotation import compute_weight, select_card_type
from app.cards.validator import validate_card

__all__ = [
    "CARD_TYPES",
    "CARD_TYPE_NAMES",
    "compute_weight",
    "select_card_type",
    "validate_card",
]
