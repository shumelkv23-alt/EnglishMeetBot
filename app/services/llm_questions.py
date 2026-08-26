"""Генерация персональных вопросов через OpenRouter (LLM).

Провайдер: OpenAI-совместимый endpoint OpenRouter (`/chat/completions`),
JSON-режим. Приватность: в промпт уходят только interests из профиля
(это данные, которые пользователь сам указал для подбора тем).
Любой сбой генерации возвращает None — вызывающий код использует банк (REQ-10).
"""
import json
import logging

import requests

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

_LEVEL_HINTS = {
    "A1": "Use very simple words and short sentences. Ask about concrete everyday things (food, weather, family, hobbies).",
    "A2": "Use simple everyday language. Ask about concrete personal experience.",
    "B1": "Use everyday language; invite opinions and reasons (\"why\").",
    "B2": "Use natural conversational English; invite opinions, comparisons and hypotheticals.",
    "C1": "Use sophisticated English; invite nuanced opinions and abstract ideas.",
    "C2": "Use idiomatic, near-native English; invite complex, abstract discussion.",
}


def _system_prompt(level: str) -> str:
    """Системный промпт генератора вопроса, адаптированный под уровень."""
    hint = _LEVEL_HINTS.get(level, _LEVEL_HINTS["B1"])
    return (
        "You generate ONE short conversational question in English for English practice "
        "at the weekly colleagues' meetup. The question is lively, about everyday life "
        "(food, movies, travel, hobbies, funny moments). Invites a short 1-2 minute story. "
        "The person's interests are just one possible guide, don't fixate on them. "
        f"Level: {level}. {hint} "
        'Return strict JSON of the form {"question_text": "question text"}. No comments or markup.'
    )


def _get_api_key() -> str:
    from app.config import get_settings

    return get_settings().openrouter_api_key


def _get_model() -> str:
    from app.config import get_settings

    return get_settings().llm_model


def parse_generated_json(content: str) -> str | None:
    """Извлечь question_text из ответа LLM; при любой проблеме — None."""
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    text = data.get("question_text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    return None


def generate_personal_question(
    interests: list[str],
    *,
    api_key: str | None = None,
    model: str | None = None,
    timeout: float = 10.0,
    avoid: list[str] | None = None,
    level: str = "A2",
) -> str | None:
    """Сгенерировать персональный вопрос по интересам участника.

    avoid — прошлые вопросы участника; LLM просят их не повторять.
    Возвращает None при: пустом ключе, сетевой ошибке, таймауте, невалидном JSON.
    Синхронная — транспорт проекта (requests) тоже синхронный.
    """
    api_key = api_key if api_key is not None else _get_api_key()
    model = model if model is not None else _get_model()
    if not api_key or not model:
        return None

    interests_text = ", ".join(interests) if interests else "no clear preferences"
    user_prompt = (
        f"The person's interests: {interests_text}. "
        "DON'T fixate on interests — ask an easy question on ANY lively everyday topic "
        "(food, travel, habits, music, funny moments, hobbies), only occasionally touching on interests. "
        "Pick a new topic each time."
    )
    if avoid:
        user_prompt += (
            " DON'T repeat these past questions: " + "; ".join(avoid) + ". Come up with a new one on a different topic."
        )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _system_prompt(level)},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 1.2,
        "max_tokens": 1024,
    }
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        resp = requests.post(OPENROUTER_URL, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
        question = parse_generated_json(content)
        logger.info("llm_question_generated ok=%s", question is not None)
        return question
    except Exception:
        logger.warning("llm_generate_failed", exc_info=True)
        return None