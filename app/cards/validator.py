"""Валидация карточки: структурные проверки + safety tier (ТЗ §4.7)."""
import re

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

    for w in _safety_hits(_gather_text(content)):
        errors.append(f"stop-topic: {w}")

    return errors
