"""Генерация персональных вопросов через LLM (Anthropic Messages API).

Провайдер: Azati (`https://llm.azati.ai`) — Anthropic-совместимый endpoint
`/v1/messages`, авторизация заголовком `x-api-key`. Модель по умолчанию
"Azati Fast" (быстрая, без мышления — подходит для синхронного ответа в чат).
Модели с расширенным мышлением ("Azati Pro") тоже работают: в `content` тогда
лежат блоки `thinking` и `text`; нас интересуют только `text`-блоки.

Приватность: в промпт уходят только интересы/уровень/прошлые ответы — данные,
которые пользователь сам указал для подбора тем. Любой сбой генерации
возвращает None — вызывающий код использует детерминированный банк (REQ-10).
"""
import json
import logging

import requests

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://llm.azati.ai"
ANTHROPIC_VERSION = "2023-06-01"

_SYSTEM_PROMPT = (
    "Ты генерируешь один лёгкий разговорный вопрос по-русски для практики "
    "английского языка на еженедельной встрече коллег. Вопрос должен быть "
    "личным, конкретным и располагать к короткому рассказу (2-3 минуты). "
    "Учитывай интересы собеседника. Верни строго JSON вида "
    '{"question_text": "текст вопроса"}. Без комментариев и разметки.'
)


def _get_api_key() -> str:
    from app.config import get_settings

    return get_settings().llm_api_key


def _get_model() -> str:
    from app.config import get_settings

    return get_settings().llm_model


def _get_base_url() -> str:
    from app.config import get_settings

    return get_settings().llm_base_url or DEFAULT_BASE_URL


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


def _post_messages(payload: dict, *, api_key: str, base_url: str, timeout: float) -> str:
    """POST в /v1/messages; вернуть собранный text-контент (или поднять ошибку)."""
    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    resp = requests.post(
        f"{base_url.rstrip('/')}/v1/messages",
        json=payload,
        headers=headers,
        timeout=timeout,
    )
    resp.raise_for_status()
    return _extract_text(resp.json())


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
    timeout: float = 30.0,
    base_url: str | None = None,
) -> str | None:
    """Сгенерировать персональный вопрос по интересам участника.

    Возвращает None при: пустом ключе, сетевой ошибке, таймауте, невалидном JSON.
    Синхронная — транспорт проекта (requests) тоже синхронный.
    """
    api_key = api_key if api_key is not None else _get_api_key()
    if not api_key:
        return None
    model = model if model is not None else _get_model()
    base_url = base_url if base_url is not None else _get_base_url()
    if not model:
        return None

    interests_text = ", ".join(interests) if interests else "нет явных предпочтений"
    user_prompt = (
        f"Интересы собеседника: {interests_text}. "
        "Сформулируй один вопрос, связанный с этими интересами."
    )
    payload = {
        "model": model,
        "max_tokens": 1024,
        "system": _SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_prompt}],
    }

    try:
        text = _post_messages(payload, api_key=api_key, base_url=base_url, timeout=timeout)
        question = parse_generated_json(text)
        logger.info("llm_question_generated ok=%s", question is not None)
        return question
    except Exception:
        logger.warning("llm_generate_failed", exc_info=True)
        return None


def generate_weekly_questions(
    context: str,
    *,
    api_key: str | None = None,
    model: str | None = None,
    timeout: float = 60.0,
    base_url: str | None = None,
) -> list[str] | None:
    """Сгенерировать два персональных вопроса недели по контексту участника.

    context — строковое описание (интересы, уровень, прошлые ответы). Возвращает
    список из двух вопросов или None при сбое/пустом ключе — тогда вызывающий
    код использует детерминированный банк (REQ-10).
    """
    api_key = api_key if api_key is not None else _get_api_key()
    if not api_key:
        return None
    model = model if model is not None else _get_model()
    base_url = base_url if base_url is not None else _get_base_url()
    if not model:
        return None

    system = (
        "Ты придумываешь два лёгких разговорных вопроса по-русски для практики "
        "английского языка на еженедельной встрече коллег. Вопросы должны быть "
        "личными, конкретными, опираться на интересы и прошлые ответы собеседника "
        "и располагать к короткому рассказу (2–3 минуты). Не повторяй прошлые темы. "
        'Верни строго JSON вида {"questions": ["вопрос 1", "вопрос 2"]}. '
        "Без комментариев и разметки."
    )
    payload = {
        "model": model,
        "max_tokens": 2048,
        "system": system,
        "messages": [
            {"role": "user", "content": f"Контекст участника:\n{context}\n\nСформулируй два вопроса."}
        ],
    }

    try:
        text = _post_messages(payload, api_key=api_key, base_url=base_url, timeout=timeout)
        data = json.loads(text)
        questions = data.get("questions") if isinstance(data, dict) else None
        if (
            isinstance(questions, list)
            and len(questions) >= 2
            and all(isinstance(q, str) and q.strip() for q in questions)
        ):
            result = [q.strip() for q in questions[:2]]
            logger.info("llm_weekly_questions_generated ok=true")
            return result
        logger.warning("llm_weekly_questions_bad_payload")
        return None
    except Exception:
        logger.warning("llm_weekly_questions_failed", exc_info=True)
        return None
