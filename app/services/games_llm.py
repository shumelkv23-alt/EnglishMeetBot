"""Генерация контента для игр «Кто я?» и Quiplash через LLM.

Провайдер: Azati (`https://llm.azati.ai`) — Anthropic-совместимый endpoint
`/v1/messages`, авторизация заголовком `x-api-key`. Те же настройки `llm_*`
из `.env`, что и в llm_questions.py (модель по умолчанию "Azati Fast").

Функции асинхронные: синхронный transport (requests) крутится в потоке через
asyncio.to_thread, чтобы не блокировать event-loop. Любой сбой генерации
возвращает детерминированный фолбэк (банк промптов/сущностей), поэтому игра
запускается даже без LLM.
"""
import asyncio
import json
import logging
import random

import requests

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://llm.azati.ai"
ANTHROPIC_VERSION = "2023-06-01"

# Дефолтные сущности/промпты, когда LLM недоступен (детерминированный банк).
_FALLBACK_ENTITIES = [
    "a cat",
    "a teacher",
    "a chef",
    "a famous actor",
    "a dog",
    "a superhero",
    "a tourist",
    "a programmer",
]

_FALLBACK_PROMPTS = [
    "The worst thing that can happen during a work meeting is…",
    "The one thing I secretly judge my colleagues for is…",
    "A phrase that should be banned from every meeting:",
    "My spirit animal during a Monday standup is…",
    "The most overrated thing about team building is…",
]

# Произвольные темы (fallback, когда LLM недоступен).
_TOPIC_BANK = [
    "Office life",
    "Travel and holidays",
    "Food and cooking",
    "Modern technology",
    "Pets and animals",
    "Sports and fitness",
    "Movies and TV",
    "Daily routines",
]


def _settings():
    from app.config import get_settings

    return get_settings()


def _extract_text(resp_json: dict) -> str:
    """Собрать все text-блоки из `content` ответа Messages API (без thinking)."""
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


def _post_messages(payload: dict, timeout: float) -> str:
    """POST в /v1/messages; вернуть собранный text-контент (или поднять ошибку)."""
    settings = _settings()
    headers = {
        "x-api-key": settings.llm_api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    base_url = (settings.llm_base_url or DEFAULT_BASE_URL).rstrip("/")
    resp = requests.post(
        f"{base_url}/v1/messages",
        json=payload,
        headers=headers,
        timeout=timeout,
    )
    resp.raise_for_status()
    return _extract_text(resp.json())


async def _call_llm(payload: dict, timeout: float) -> str | None:
    """Асинхронная обёртка над _post_messages. None при любом сбое."""
    settings = _settings()
    if not settings.llm_api_key or not settings.llm_model:
        return None
    try:
        return await asyncio.to_thread(_post_messages, payload, timeout)
    except Exception:
        logger.warning("games_llm_call_failed", exc_info=True)
        return None


def _parse_json(content: str) -> dict:
    """Достать JSON-объект из ответа LLM (убирает markdown-обёртки)."""
    if not content:
        return {}
    text = content.strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return {}
        try:
            data = json.loads(text[start : end + 1])
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}


def _pad(items: list[str], n: int) -> list[str]:
    """Дополнить список до n элементов повторением."""
    if not items or n <= len(items):
        return items[:n]
    return (items * ((n // len(items)) + 1))[:n]


async def generate_quiplash_game(count: int = 10) -> dict:
    """Один вызов: произвольная тема + промпты Quiplash. Возврат {'topic', 'prompts'}.

    Тема теперь не зависит от ответов участников — генерируется «с нуля» тем же
    LLM (Azati), что и еженедельные вопросы.
    """
    settings = _settings()
    model = settings.llm_model
    payload = {
        "model": model,
        "max_tokens": 4096,
        "system": "Ты генерируешь тему и промпты для игры Quiplash. ОТВЕЧАЙ ТОЛЬКО JSON.",
        "messages": [
            {
                "role": "user",
                "content": (
                    f"Придумай произвольную тему встречи (1-4 слова, EN) и {count} смешных/"
                    "жизненных открытых промптов на английском для Quiplash (игроки дают "
                    "смешные ответы). Верни строго JSON вида "
                    '{"topic": "...", "prompts": ["...", "..."]}.'
                ),
            }
        ],
    }
    content = await _call_llm(payload, timeout=60.0)
    if content:
        data = _parse_json(content)
        topic = str(data.get("topic") or "").strip() or "General conversation"
        prompts = [str(p).strip() for p in (data.get("prompts") or []) if str(p).strip()][:count]
        if prompts:
            return {"topic": topic, "prompts": _pad(prompts, count)}
    return {"topic": random.choice(_TOPIC_BANK), "prompts": _pad(_fallback_prompts(""), count)}


async def generate_who_am_i_game(count: int) -> dict:
    """Один вызов: произвольная тема + сущности для «Кто я?». Возврат {'topic', 'entities'}."""
    settings = _settings()
    model = settings.llm_model
    payload = {
        "model": model,
        "max_tokens": 4096,
        "system": "Ты генерируешь тему и сущности для игры «Кто я?». ОТВЕЧАЙ ТОЛЬКО JSON.",
        "messages": [
            {
                "role": "user",
                "content": (
                    f"Придумай произвольную тему встречи (1-4 слова, EN) и {count} сущностей "
                    "на эту тему для игры «Кто я?» (известные люди, профессии, персонажи, "
                    "предметы, животные). Каждую можно угадать вопросами «да/нет». Верни строго "
                    'JSON вида {"topic": "...", "entities": ["...", "..."]}.'
                ),
            }
        ],
    }
    content = await _call_llm(payload, timeout=60.0)
    if content:
        data = _parse_json(content)
        topic = str(data.get("topic") or "").strip() or "General conversation"
        entities = [str(e).strip() for e in (data.get("entities") or []) if str(e).strip()][:count]
        if entities:
            return {"topic": topic, "entities": _pad(entities, count)}
    return {"topic": random.choice(_TOPIC_BANK), "entities": _pad(_fallback_entities, count)}


async def judge_guess(secret: str, guess: str) -> bool | None:
    """Вердикт LLM: совпадает ли догадка с секретом. None — ошибка (fallback)."""
    settings = _settings()
    model = settings.llm_model
    payload = {
        "model": model,
        "max_tokens": 200,
        "system": "Ты судишь игру «Кто я?». Отвечай только yes или no.",
        "messages": [
            {
                "role": "user",
                "content": (
                    f'Загаданная сущность: "{secret}". Игрок предполагает: "{guess}". '
                    "Это одно и то же? Ответь только yes или no."
                ),
            }
        ],
    }
    content = await _call_llm(payload, timeout=30.0)
    if not content:
        return None
    lowered = content.strip().lower()
    if lowered.startswith("yes"):
        return True
    if lowered.startswith("no"):
        return False
    return None


def _fallback_entities(topic: str) -> list[str]:
    """Банк сущностей по умолчанию."""
    return list(_FALLBACK_ENTITIES)


def _fallback_prompts(topic: str) -> list[str]:
    """Банк промптов по умолчанию (самодостаточные, без подстановки темы)."""
    return list(_FALLBACK_PROMPTS)
