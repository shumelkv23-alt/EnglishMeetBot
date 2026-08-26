"""Pydantic-схемы карточки занятия (ТЗ §4.2).

Используются для валидации LLM-ответа (Phase 2) и как контракт структуры
`cards.content` (JSONB). `type_specific_payload` вариативен по card_type.
"""
from typing import Any

from pydantic import BaseModel, Field


class SubQuestion(BaseModel):
    text: str
    level: str = "medium"  # easy | medium | hard


class VocabItem(BaseModel):
    phrase: str
    translation: str = ""
    example: str = ""


class SuggestedActivity(BaseModel):
    activity_id: str
    activity_type: str = "group_game"  # group_game | solo_activity
    relevance_reason: str = ""


class CardContent(BaseModel):
    """Полная структура карточки. Доп. поля типов — в type_specific_payload."""

    card_type: str
    difficulty_level: str
    warm_up: dict[str, Any] = Field(default_factory=dict)
    main_content: dict[str, Any] = Field(default_factory=dict)
    vocab_box: list[VocabItem] = Field(default_factory=list)
    suggested_activity: SuggestedActivity | None = None
    stretch_challenge: dict[str, Any] | None = None
    wrap_up_question: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)
