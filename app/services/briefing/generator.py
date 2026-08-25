"""Генерация брифинга встречи через LLM (Anthropic Messages API / Azati).

По ответам участников на вопросы недели LLM придумывает на английском:
- topic — тема встречи (короткая фраза);
- statements — ровно два дискуссионных утверждения по теме;
- news — короткие «свежие» новости по теме (генерируются LLM, не проверяются).

Провайдер и настройки те же, что в llm_questions.py / games_llm.py: endpoint
`/v1/messages`, заголовок `x-api-key`, модель из `llm_games_model`. Любой сбой или
отсутствие ключа возвращают детерминированный фолбэк, чтобы брифинг уходил
в группу даже без LLM (REQ-10: fallback-контент).
"""
import asyncio
import json
import logging

import requests

from app.config import get_settings

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://llm.azati.ai"
ANTHROPIC_VERSION = "2023-06-01"

STATEMENTS_COUNT = 2
NEWS_COUNT = 3
PHRASES_COUNT = 5

_FALLBACK = {
    "topic": "Life and interests",
    "statements": [
        "Small daily habits change our lives more than big decisions.",
        "Technology brings us closer together and further apart at the same time.",
    ],
    "news": [
        "More people are choosing flexible schedules to fit learning around life.",
        "Language apps keep adding conversation features for real speaking practice.",
        "Teams are experimenting with shorter, focused meetings to stay engaged.",
    ],
    "phrases": [
        "In my opinion, …",
        "I see what you mean, but …",
        "That's a good point.",
        "Could you elaborate on that?",
        "On the other hand, …",
    ],
}


def _fallback() -> dict:
    """Свежая копия фолбэка (не делим изменяемые списки между вызовами)."""
    return {
        "topic": _FALLBACK["topic"],
        "statements": list(_FALLBACK["statements"]),
        "news": list(_FALLBACK["news"]),
        "phrases": list(_FALLBACK["phrases"]),
    }


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


def _post_messages(payload: dict, timeout: float) -> str:
    """POST в /v1/messages; вернуть собранный text-контент (или поднять ошибку)."""
    settings = get_settings()
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
    """Асинхронная обёртка над _post_messages. None при любом сбое/пустом ключе."""
    settings = get_settings()
    if not settings.llm_api_key or not settings.llm_games_model:
        return None
    try:
        return await asyncio.to_thread(_post_messages, payload, timeout)
    except Exception:
        logger.warning("briefing_llm_call_failed", exc_info=True)
        return None


async def generate_briefing(
    context: str,
    *,
    news_count: int = NEWS_COUNT,
    phrases_count: int = PHRASES_COUNT,
) -> dict:
    """Сгенерировать брифинг по контексту участников.

    context — строковый список «Имя (уровень): ответ» участников встречи.
    Возвращает {"topic", "statements", "phrases", "news"} (всё на английском).
    При сбое — детерминированный фолбэк.
    """
    settings = get_settings()
    if not settings.llm_api_key or not settings.llm_games_model:
        return _fallback()

    payload = {
        "model": settings.llm_games_model,
        "max_tokens": 2048,
        "system": (
            "Ты готовишь бриф встречи разговорного английского клуба. "
            "Всё содержимое строго на английском языке. "
            "Отвечай ТОЛЬКО валидным JSON без комментариев и markdown-разметки."
        ),
        "messages": [
            {
                "role": "user",
                "content": (
                    "Ниже — ответы участников на вопросы недели:\n\n"
                    f"{context}\n\n"
                    "На основе этих ответов придумай: (1) тему встречи — короткая фраза "
                    "на английском (1-6 слов), (2) ровно два дискуссионных утверждения "
                    "(statements) по этой теме на английском, (3) три коротких свежих "
                    "новости по этой теме на английском (2-3 предложения каждая), и "
                    "(4) пять полезных фраз/выражений на английском для обсуждения этой "
                    "темы (phrases — короткие разговорные обороты). "
                    'Верни строго JSON вида {"topic": "...", "statements": ["...", "..."], '
                    '"news": ["...", "...", "..."], "phrases": ["...", "...", "...", "...", "..."]}.'
                ),
            }
        ],
    }
    content = await _call_llm(payload, timeout=60.0)
    if content:
        data = _parse_json(content)
        topic = str(data.get("topic") or "").strip()
        statements = data.get("statements")
        news = data.get("news")
        phrases = data.get("phrases")
        # LLM может вернуть строку вместо списка — это не валидный ответ, фолбэк.
        if not isinstance(statements, list) or not isinstance(news, list):
            return _fallback()
        statements = [str(s).strip() for s in statements if str(s).strip()]
        news = [str(n).strip() for n in news if str(n).strip()]
        phrases = [str(p).strip() for p in phrases if str(p).strip()] if isinstance(phrases, list) else []
        if topic and len(statements) >= STATEMENTS_COUNT and news:
            return {
                "topic": topic,
                "statements": statements[:STATEMENTS_COUNT],
                "news": news[:news_count],
                "phrases": (phrases or _FALLBACK["phrases"])[:phrases_count],
            }
    return _fallback()
