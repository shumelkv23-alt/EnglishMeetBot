"""Ответ бота на незнакомые сообщения в личке через LLM.

Провайдер: Azati (`https://llm.azati.ai`) — Anthropic-совместимый endpoint
`/v1/messages`, авторизация заголовком `x-api-key`. Те же настройки `llm_*`
из `.env`, что и в llm_questions.py / games_llm.py. Без ключа или при сбое —
None, вызывающий код подставляет вежливую заглушку.
"""
import asyncio
import logging

import requests

from app.config import get_settings

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://llm.azati.ai"
ANTHROPIC_VERSION = "2023-06-01"

_SYSTEM_PROMPT = (
    "You are English Meet Bot, a friendly bot that helps people practice English "
    "through meetups, games and weekly questions. Reply in English, keep it brief "
    "(1–3 sentences), warm and to the point, without addressing the user by name. "
    "If a message is unclear or off-topic, gently ask what they meant. If needed, "
    "remind them: `games` — games, `questions` — weekly questions."
)


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
    content = resp.json().get("content")
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts)


async def chat_reply(user_message: str) -> str | None:
    """Ответ LLM на сообщение пользователя. None при отсутствии ключа или сбое.

    Имя пользователя в промпт не подставляем: модель склонна начинать ответ
    «эхом» с имени и обрываться (напр. «Антон Иго»). Плюс одна повторная попытка
    на пустой ответ — модель иногда возвращает только thinking-блок без текста.
    """
    settings = get_settings()
    if not settings.llm_api_key or not settings.llm_model:
        return None

    payload = {
        "model": settings.llm_model,
        "max_tokens": 300,
        "system": _SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_message}],
    }
    for _ in range(2):
        try:
            content = await asyncio.to_thread(_post_messages, payload, 30.0)
        except Exception:
            logger.warning("chat_ai_call_failed", exc_info=True)
            return None
        text = (content or "").strip()
        if text:
            return text
    return None
