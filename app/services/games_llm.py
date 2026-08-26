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
import re

import requests

from app.services.two_truths_bank import random_two_truths

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
    if not settings.llm_api_key or not settings.llm_games_model:
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
    model = settings.llm_games_model
    payload = {
        "model": model,
        "max_tokens": 4096,
        "system": "You generate a topic and prompts for Quiplash. ANSWER ONLY WITH JSON.",
        "messages": [
            {
                "role": "user",
                "content": (
                    f"Come up with a random meeting topic (1-4 words, EN) and {count} funny/"
                    "relatable open-ended prompts in English for Quiplash (players give "
                    "funny answers). Return strict JSON of the form "
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
    model = settings.llm_games_model
    payload = {
        "model": model,
        "max_tokens": 4096,
        "system": "You generate a topic and entities for 'Who am I?'. ANSWER ONLY WITH JSON.",
        "messages": [
            {
                "role": "user",
                "content": (
                    f"Come up with a random meeting topic (1-4 words, EN) and {count} entities "
                    "on this topic for 'Who am I?' (famous people, jobs, characters, "
                    "objects, animals). Each can be guessed with 'yes/no' questions. Return strict "
                    'JSON of the form {"topic": "...", "entities": ["...", "..."]}.'
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
    model = settings.llm_games_model
    payload = {
        "model": model,
        "max_tokens": 200,
        "system": "You judge 'Who am I?'. Answer only yes or no.",
        "messages": [
            {
                "role": "user",
                "content": (
                    f'The secret entity: "{secret}". The player guesses: "{guess}". '
                    "Are they the same? Answer only yes or no."
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
async def generate_two_truths_game() -> dict:
    """Один вызов LLM: набор «Две правды, одна ложь». Возврат {'topic', 'statements', 'lie'}.

    `lie` — 1-based индекс ложного утверждения. При сбое LLM или некорректном
    ответе — случайный набор из банка (two_truths_bank).
    """
    settings = _settings()
    model = settings.llm_games_model
    payload = {
        "model": model,
        "max_tokens": 4096,
        "system": "You generate 'Two Truths and a Lie' sets. ANSWER IN JSON ONLY.",
        "messages": [
            {
                "role": "user",
                "content": (
                    "Create a 'Two Truths and a Lie' set for English learners: pick a fun topic "
                    "and write three short statements in English (one sentence each). Exactly two "
                    "must be TRUE and one FALSE (the lie should be plausible, not obvious). Return "
                    'strictly JSON like {"topic": "...", "statements": ["...", "...", "..."], '
                    '"lie": 2} where lie is the 1-based index of the FALSE statement.'
                ),
            }
        ],
    }
    content = await _call_llm(payload, timeout=60.0)
    if content:
        data = _parse_json(content)
        statements = [str(s).strip() for s in (data.get("statements") or []) if str(s).strip()]
        topic = str(data.get("topic") or "").strip() or "Fun facts"
        try:
            lie = int(data.get("lie", 0))
        except (TypeError, ValueError):
            lie = 0
        if len(statements) == 3 and 1 <= lie <= 3:
            return {"topic": topic, "statements": statements, "lie": lie}
    return random_two_truths()


async def judge_translation(
    source: str,
    source_lang: str,
    target_lang: str,
    reference: str,
    guess: str,
) -> dict | None:
    """Вердикт LLM по переводу. Возврат {'correct': bool, 'note': str} или None.

    LLM принимает синонимы и даёт краткую подсказку, если ответ неверен или неточен.
    None — при сбое LLM (в сервисе перевод подставляется точное сравнение).
    """
    settings = _settings()
    model = settings.llm_games_model
    payload = {
        "model": model,
        "max_tokens": 300,
        "system": "You judge a translation exercise. ANSWER IN JSON ONLY.",
        "messages": [
            {
                "role": "user",
                "content": (
                    f"Source ({source_lang}): \"{source}\"\n"
                    f"Reference translation ({target_lang}): \"{reference}\"\n"
                    f"Player's translation: \"{guess}\"\n"
                    "Judge whether the player's translation is correct and acceptable "
                    f"(synonyms, rephrasing and minor word-order differences are fine). "
                    "Return strictly JSON like {\"correct\": true, \"note\": \"\"} where "
                    "correct is true/false. If correct, note is empty. If incorrect or "
                    "inaccurate, put a short hint in English in note (5-12 words)."
                ),
            }
        ],
    }
    content = await _call_llm(payload, timeout=30.0)
    if not content:
        return None
    data = _parse_json(content)
    if "correct" not in data:
        return None
    correct = bool(data.get("correct"))
    note = str(data.get("note") or "").strip()
    return {"correct": correct, "note": note}


async def judge_riddle_answer(riddle: str, answer: str, guess: str) -> bool | None:
    """Вердикт LLM: угадал ли игрок ответ на загадку. None — ошибка.

    Принимает синонимы и перефразировки (например, «keyboard» вместо «piano»).
    Фолбэк в сервисе — точное совпадение по нормализованной строке.
    """
    settings = _settings()
    model = settings.llm_games_model
    payload = {
        "model": model,
        "max_tokens": 200,
        "system": "You judge a riddle answer. Answer only yes or no.",
        "messages": [
            {
                "role": "user",
                "content": (
                    f'Riddle: "{riddle}"\n'
                    f'The answer: "{answer}".\n'
                    f'The player guesses: "{guess}".\n'
                    "Is the player's guess correct? Accept synonyms and rephrasing. "
                    "Answer only yes or no."
                ),
            }
        ],
    }
    content = await _call_llm(payload, timeout=30.0)
    if not content:
        return None
    lowered = content.strip().lower()
    if re.search(r"\byes\b", lowered):
        return True
    if re.search(r"\bno\b", lowered):
        return False
    return None


async def is_real_word(word: str) -> bool | None:
    """Проверка LLM: существует ли такое английское слово. None — ошибка.

    Используется в «Words of Wonders» для бонус-слов (слова не из банка, но
    собираемые из букв): если LLM подтверждает, слово идёт в счётчик.
    """
    settings = _settings()
    model = settings.llm_games_model
    payload = {
        "model": model,
        # reasoning-модель (Azati) тратит бюджет на thinking-блок — даём запас,
        # иначе «yes/no» обрезается и слово не проверяется.
        "max_tokens": 256,
        "system": "You verify English words. Answer only yes or no.",
        "messages": [
            {
                "role": "user",
                "content": (
                    f'Is "{word}" a real English word? Count any valid dictionary word, '
                    "including plurals, verb forms and informal words. Answer only yes or no."
                ),
            }
        ],
    }
    content = await _call_llm(payload, timeout=30.0)
    if not content:
        return None
    lowered = content.strip().lower()
    # Ищем «yes»/«no» как отдельные слова (модель может отвечать «No, it's not…»).
    if re.search(r"\byes\b", lowered):
        return True
    if re.search(r"\bno\b", lowered):
        return False
    return None


