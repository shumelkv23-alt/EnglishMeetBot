"""Генерация персональных вопросов через Azati (Anthropic Messages API).

Провайдер: Azati (`llm_api_key` + `llm_games_model`, endpoint `/v1/messages`).
Приватность: в промпт уходят только interests из профиля
(это данные, которые пользователь сам указал для подбора тем).
Любой сбой генерации возвращает None — вызывающий код использует банк (REQ-10).
"""
import json
import logging

import requests

from app.config import get_settings

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://llm.azati.ai"
ANTHROPIC_VERSION = "2023-06-01"

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


def _extract_text(resp_json: dict) -> str:
    """Собрать все text-блоки из `content` ответа Messages API."""
    content = resp_json.get("content")
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts)


def parse_generated_json(content: str) -> str | None:
    """Извлечь question_text из ответа LLM (убирает markdown-обёртки)."""
    if not content:
        return None
    text = content.strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    q = data.get("question_text")
    if isinstance(q, str) and q.strip():
        return q.strip()
    return None


def generate_personal_question(
    interests: list[str],
    *,
    api_key: str | None = None,
    model: str | None = None,
    timeout: float = 60.0,
    avoid: list[str] | None = None,
    level: str = "A2",
    theme: str | None = None,
) -> str | None:
    """Сгенерировать персональный вопрос по интересам участника.

    avoid — прошлые вопросы участника; LLM просят их не повторять.
    Возвращает None при: пустом ключе, сетевой ошибке, таймауте, невалидном JSON.
    Синхронная — транспорт проекта (requests) тоже синхронный.
    """
    settings = get_settings()
    api_key = api_key if api_key is not None else settings.llm_api_key
    model = model if model is not None else settings.llm_games_model
    if not api_key or not model:
        return None

    interests_text = ", ".join(interests) if interests else "no clear preferences"
    user_prompt = f"The person's interests: {interests_text}. "
    if theme:
        user_prompt += f"This week's meetup theme: {theme}. "
    user_prompt += (
        "DON'T fixate on interests — ask an easy question on ANY lively everyday topic "
        "(food, travel, habits, music, funny moments, hobbies), only occasionally touching on interests or the theme. "
        "Pick a new topic each time."
    )
    if avoid:
        user_prompt += (
            " DON'T repeat these past questions: " + "; ".join(avoid) + ". Come up with a new one on a different topic."
        )

    payload = {
        "model": model,
        "max_tokens": 1024,
        "system": _system_prompt(level),
        "messages": [{"role": "user", "content": user_prompt}],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    base_url = (settings.llm_base_url or DEFAULT_BASE_URL).rstrip("/")

    try:
        resp = requests.post(f"{base_url}/v1/messages", json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        content = _extract_text(resp.json())
        question = parse_generated_json(content)
        logger.info("llm_question_generated ok=%s", question is not None)
        return question
    except Exception:
        logger.warning("llm_generate_failed", exc_info=True)
        return None
