"""Валидация карточки: структурные проверки + safety tier (ТЗ §4.7)."""
import re

from app.cards.activity_matcher import game_by_id
from app.cards.generator.recipes import type_payload_errors
from app.cards.schemas import normalise_card_text

# Tier 3 — исключено полностью. Проверяем по целым словам (без ложных срабатываний).
STOP_WORDS = frozenset({
    "politics", "politician", "election",
    "religion", "religious",
    "salary", "income", "debt", "bankruptcy",
    "suicide", "cancer", "disease",
    "terrorism",
})

MAX_TOPIC_LEN = 200
MAX_QUESTION_LEN = 500
QUESTION_LEVELS = ("easy", "medium", "hard")
REQUIRED_FIELDS = ("card_type", "difficulty_level")


def _safety_hits(text: str) -> list[str]:
    """Стоп-слова, встретившиеся в тексте (по целым словам)."""
    lowered = text.lower()
    return [w for w in STOP_WORDS if re.search(rf"\b{re.escape(w)}\b", lowered)]


def _gather_text(content: dict) -> str:
    """Собрать все текстовые поля карточки (которые реально рендерятся) в строку."""
    parts: list[str] = []

    warm = content.get("warm_up") or {}
    if isinstance(warm, dict):
        parts.append(str(warm.get("question") or ""))

    main = content.get("main_content") or {}
    parts.append(str(main.get("topic") or ""))
    for q in main.get("sub_questions") or []:
        parts.append(q.get("text") if isinstance(q, dict) else str(q))
    for s in main.get("statements") or []:
        parts.append(str(s))
    payload = main.get("type_specific_payload") or {}
    if isinstance(payload, dict):
        parts.extend(str(v) for v in payload.values())

    for v in content.get("vocab_box") or []:
        if isinstance(v, dict):
            parts.append(str(v.get("phrase") or ""))
            parts.append(str(v.get("translation") or ""))
            parts.append(str(v.get("example") or ""))

    parts.append(str(content.get("stretch_challenge") or ""))
    parts.append(str(content.get("wrap_up_question") or ""))
    return "\n".join(parts)


def validate_card(content: dict) -> list[str]:
    """Вернуть список ошибок (пустой список — карточка валидна)."""
    errors: list[str] = []

    for field in REQUIRED_FIELDS:
        if not content.get(field):
            errors.append(f"missing {field}")

    main = content.get("main_content") or {}
    topic = str(main.get("topic") or "").strip()
    if not topic:
        errors.append("missing main_content.topic")
    elif len(topic) > MAX_TOPIC_LEN:
        errors.append("main_content.topic too long")

    for i, q in enumerate(main.get("sub_questions") or [], 1):
        text_q = q.get("text") if isinstance(q, dict) else str(q)
        if len(str(text_q)) > MAX_QUESTION_LEN:
            errors.append(f"sub_question[{i}] too long")
    _validate_sub_questions(main.get("sub_questions"), errors)
    _validate_vocab_box(content.get("vocab_box"), errors)
    _validate_type_payload(str(content.get("card_type") or ""), main.get("type_specific_payload"), errors)

    for w in _safety_hits(_gather_text(content)):
        errors.append(f"stop-topic: {w}")

    return errors


def _validate_sub_questions(value, errors: list[str]) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        errors.append("main_content.sub_questions must be a list")
        return
    if len(value) != 3:
        errors.append("main_content.sub_questions must contain exactly 3 questions")
        return
    levels: list[str] = []
    questions: list[str] = []
    for i, item in enumerate(value, 1):
        if not isinstance(item, dict):
            errors.append(f"sub_question[{i}] must be an object")
            continue
        text = str(item.get("text") or "").strip()
        level = str(item.get("level") or "").strip()
        if not text:
            errors.append(f"sub_question[{i}] missing text")
        if level:
            levels.append(level)
        questions.append(normalise_card_text(text))
    if levels and tuple(levels) != QUESTION_LEVELS:
        errors.append("main_content.sub_questions must be ordered easy, medium, hard")
    if len([q for q in questions if q]) != len(set(q for q in questions if q)):
        errors.append("main_content.sub_questions must be unique")


def _validate_vocab_box(value, errors: list[str]) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        errors.append("vocab_box must be a list")
        return
    if not 2 <= len(value) <= 3:
        errors.append("vocab_box must contain 2 or 3 items")
        return
    phrases: list[str] = []
    for i, item in enumerate(value, 1):
        if not isinstance(item, dict):
            errors.append(f"vocab_box[{i}] must be an object")
            continue
        for field in ("phrase", "translation", "example"):
            if not str(item.get(field) or "").strip():
                errors.append(f"vocab_box[{i}] missing {field}")
        phrases.append(normalise_card_text(item.get("phrase") or ""))
    if len([p for p in phrases if p]) != len(set(p for p in phrases if p)):
        errors.append("vocab_box phrases must be unique")


def _validate_type_payload(card_type: str, payload, errors: list[str]) -> None:
    if not card_type:
        return
    errors.extend(type_payload_errors(card_type, payload))
    if card_type == "game_day":
        activity_id = (payload or {}).get("activity_id") if isinstance(payload, dict) else None
        if activity_id and game_by_id(str(activity_id)) is None:
            errors.append("invalid type_specific_payload.activity_id")
