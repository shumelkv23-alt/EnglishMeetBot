"""Генерация «занятие-карточки» (тема + план занятия) через LLM.

Провайдер тот же, что у llm_questions: Azati (Anthropic-совместимый /v1/messages).
Один промпт покрывает все 8 форматов занятия — отличие только в том, ЧТО лежит
в main_items (вопросы-лесенкой, утверждение для дебатов, роли и т.д.).

Приватность: в промпт уходят только формат, уровень и список уже использованных
тем (для дедупликации). Любой сбой → None, вызывающий код берёт банк (REQ-10).

Транспортные хелперы переиспользуем из llm_questions, чтобы не дублировать
настройку ключа/модели/base_url/разбора text-блоков.
"""
import json
import logging

from app.services.llm_questions import (
    _extract_text,
    _get_api_key,
    _get_base_url,
    _get_model,
    _post_messages,
)

logger = logging.getLogger(__name__)

# --- Метаданные форматов (общие для llm_lesson / lesson_bank / lesson_plan) ---

ALL_FORMATS = (
    "discussion", "debate", "four_hats", "roleplay",
    "ranking", "would_you_rather", "story", "taboo", "dilemma", "speed_dating",
)

# Название формата в шапке карточки (English).
FORMAT_LABELS = {
    "discussion": "Discussion ladder",
    "debate": "Debate",
    "four_hats": "Four hats",
    "roleplay": "Role-play",
    "ranking": "Ranking",
    "would_you_rather": "Would you rather",
    "story": "Story circle",
    "taboo": "Taboo",
    "dilemma": "Dilemma",
    "speed_dating": "Speed dating",
}

# Чем заполнять main_items и что писать в main_instruction — по формату.
FORMAT_GUIDANCE = {
    "discussion": (
        "main_items = 4 open questions that go from easy to more personal "
        "(a discussion ladder). main_instruction = take turns and always "
        "follow up with a question of your own."
    ),
    "debate": (
        "main_items = one debatable statement as the first item, then 2-3 "
        "spark questions. main_instruction = split into For / Against and "
        "defend your side with reasons and examples."
    ),
    "four_hats": (
        "main_items = one question, then 4 different points of view on it "
        "(optimist, skeptic, emotional, practical). main_instruction = argue "
        "the same question from all four hats."
    ),
    "roleplay": (
        "main_items = a short situation plus 3-4 roles, each with a goal. "
        "main_instruction = pick a role and improvise the scene together."
    ),
    "ranking": (
        "main_items = 4-5 things to rank and discuss. main_instruction = rank "
        "them from best to worst and explain your choice."
    ),
    "story": (
        "main_items = 3-4 one-line story starters. main_instruction = tell a "
        "short personal story starting from one of the starters."
    ),
    "dilemma": (
        "main_items = one dilemma scenario, then 2-3 'what would you do' "
        "questions. main_instruction = discuss the dilemma and defend your choice."
    ),
    "speed_dating": (
        "main_items = 4-5 short round prompts. main_instruction = talk 3 minutes "
        "per round, then switch partners."
    ),
    "would_you_rather": (
        "main_items = 5 'Would you rather A or B?' questions. "
        "main_instruction = take turns answering and explaining your choice."
    ),
    "taboo": (
        "main_items = 4-5 words to describe, each with 3 forbidden words, written "
        "like 'describe X without saying: a, b, c'. main_instruction = one person "
        "describes the word, others guess — don't say the forbidden words."
    ),
}

_REQUIRED_KEYS = (
    "topic", "warmup", "words", "main_instruction", "main_items",
    "phrases", "follow_ups", "wrapup",
)
_LIST_KEYS = ("words", "main_items", "phrases", "follow_ups")


def _system_prompt(format: str) -> str:
    guidance = FORMAT_GUIDANCE.get(format, FORMAT_GUIDANCE["discussion"])
    return (
        "You are an English conversation club facilitator. Generate one complete "
        "lesson plan for a group English meetup. Everything must be in English. "
        f"Activity format: {FORMAT_LABELS.get(format, format)}.\n"
        f"{guidance}\n\n"
        'Return STRICT JSON only (no commentary, no markdown) with exactly these keys:\n'
        '{\n'
        '  "topic": "short topic title",\n'
        '  "level": "B1",\n'
        '  "warmup": "one easy opening question",\n'
        '  "words": ["5-7 key words or phrases for this topic"],\n'
        '  "main_instruction": "one short instruction telling participants what to do",\n'
        '  "main_items": ["3-6 items for the main activity"],\n'
        '  "phrases": ["3-5 useful English phrases for the activity"],\n'
        '  "follow_ups": ["3 follow-up questions/stems to keep the conversation going"],\n'
        '  "wrapup": "one closing question"\n'
        "}\n"
        "Keep the topic neutral and workplace-friendly. Keep questions at the "
        "requested level — short, concrete, easy to answer."
    )


def _parse_lesson(content: str) -> dict | None:
    """Разобрать JSON-ответ LLM; при любой проблеме/неполноте — None."""
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    for key in _REQUIRED_KEYS:
        if key not in data:
            return None
    topic = data.get("topic")
    if not (isinstance(topic, str) and topic.strip()):
        return None
    for key in ("warmup", "main_instruction", "wrapup"):
        v = data.get(key)
        if not (isinstance(v, str) and v.strip()):
            return None
    for key in _LIST_KEYS:
        v = data.get(key)
        if not (isinstance(v, list) and v and all(isinstance(x, str) and x.strip() for x in v)):
            return None
    return {
        "topic": topic.strip(),
        "level": str(data.get("level") or "B1").strip(),
        "warmup": data["warmup"].strip(),
        "words": [x.strip() for x in data["words"]],
        "main_instruction": data["main_instruction"].strip(),
        "main_items": [x.strip() for x in data["main_items"]],
        "phrases": [x.strip() for x in data["phrases"]],
        "follow_ups": [x.strip() for x in data["follow_ups"]],
        "wrapup": data["wrapup"].strip(),
    }


def generate_lesson(
    format: str,
    level: str,
    exclude_topics: list[str],
    *,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    timeout: float = 60.0,
) -> dict | None:
    """Сгенерировать план занятия по формату; None при сбое/пустом ключе.

    Синхронная (транспорт requests), как и llm_questions. Вызывающий код
    оборачивает в asyncio.to_thread.
    """
    api_key = api_key if api_key is not None else _get_api_key()
    if not api_key:
        return None
    model = model if model is not None else _get_model()
    base_url = base_url if base_url is not None else _get_base_url()
    if not model:
        return None

    if format not in ALL_FORMATS:
        return None

    exclude_text = ", ".join(exclude_topics) if exclude_topics else "none"
    user_prompt = (
        f"Format: {format}\nLevel: {level}\n"
        f"Recently used topics (do NOT reuse them): {exclude_text}\n\n"
        "Generate the lesson plan now."
    )
    payload = {
        "model": model,
        "max_tokens": 3000,
        "system": _system_prompt(format),
        "messages": [{"role": "user", "content": user_prompt}],
    }

    try:
        text = _post_messages(payload, api_key=api_key, base_url=base_url, timeout=timeout)
        lesson = _parse_lesson(text)
        logger.info("llm_lesson_generated ok=%s format=%s", lesson is not None, format)
        return lesson
    except Exception:
        logger.warning("llm_lesson_failed format=%s", format, exc_info=True)
        return None
