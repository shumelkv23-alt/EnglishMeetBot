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

_SYSTEM_PROMPT = (
    "Ты генерируешь один КОРОТКИЙ и ЛЁГКИЙ разговорный вопрос по-русски для "
    "практики английского на еженедельной встрече коллег. Вопрос простой, живой, "
    "про повседневное (еда, фильмы, путешествия, хобби, смешные случаи) — без "
    "абстрактных и философских тем. Располагает к короткому рассказу на 1-2 минуты. "
    "Учитывай интересы собеседника. Верни строго JSON вида "
    '{"question_text": "текст вопроса"}. Без комментариев и разметки.'
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

    interests_text = ", ".join(interests) if interests else "нет явных предпочтений"
    user_prompt = (
        f"Интересы собеседника: {interests_text}. "
        "Сформулируй один вопрос, связанный с этими интересами."
    )
    if avoid:
        user_prompt += (
            " НЕ повторяй эти прошлые вопросы: " + "; ".join(avoid) + ". Придумай новый, на другую тему."
        )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
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