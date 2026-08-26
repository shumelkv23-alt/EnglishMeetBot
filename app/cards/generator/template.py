"""Шаблонная генерация контента из контент-банка (ТЗ §6.4, MVP/fallback).

Каждый тип имеет свой формат `type_specific_payload`; здесь он собирается из
записи content_bank. Tier 2 типы (debate, news_reaction) используют только его.
"""
import random

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cards.models import ContentBank

# Общие разогревающие вопросы (если нет персонального).
_WARM_UP_POOL = [
    "What's one thing that made you smile this week?",
    "What have you been watching or reading lately?",
    "If you had a free evening tonight, what would you do?",
]

_WRAP_UP_POOL = [
    "What's one word or phrase you'll take away from today?",
    "What surprised you most in this conversation?",
    "What would you like to talk about next time?",
]


async def pick_bank_payload(
    db: AsyncSession, card_type_id: int, rng: random.Random | None = None
) -> dict | None:
    """Случайная одобренная запись контент-банка для типа (None — банк пуст)."""
    rng = rng or random
    rows = (
        await db.execute(
            select(ContentBank).where(
                ContentBank.card_type_id == card_type_id,
                ContentBank.is_approved.is_(True),
            )
        )
    ).scalars().all()
    if not rows:
        return None
    return rng.choice(rows).payload


def build_template_content(card_type_name: str, payload: dict | None, difficulty: str) -> dict:
    """Собрать полный `content` карточки из payload контент-банка.

    payload — запись content_bank (или None: тогда каркас без темы).
    Возвращает словарь в структуре ТЗ §4.2 (без card_type/meta — их добавит service).
    """
    payload = payload or {}
    topic = str(payload.get("topic") or payload.get("statement") or payload.get("headline") or "").strip()
    if not topic:
        topic = _fallback_topic(card_type_name)

    main = _main_content(card_type_name, topic, payload)
    return {
        "difficulty_level": difficulty,
        "warm_up": {"question": random.choice(_WARM_UP_POOL), "based_on_profile_field": None},
        "main_content": main,
        "vocab_box": _vocab_box(card_type_name, payload),
        "wrap_up_question": random.choice(_WRAP_UP_POOL),
    }


def _fallback_topic(card_type_name: str) -> str:
    """Каркасная тема, если банк пуст (не должно случаться на проде)."""
    return {
        "would_you_rather": "Would you rather…",
        "roleplay": "Everyday situations",
        "storytelling": "Once upon a time…",
        "hot_seat": "Hot seat",
        "two_truths": "Two truths and a lie",
        "time_capsule": "Time capsule",
        "game_day": "Game warm-up",
    }.get(card_type_name, "Conversation starter")


def _main_content(card_type_name: str, topic: str, p: dict) -> dict:
    """main_content: topic + sub_questions + type_specific_payload по типу."""
    sub = _sub_questions(card_type_name, p)
    specific = _type_specific(card_type_name, p)
    main: dict = {"topic": topic}
    if sub:
        main["sub_questions"] = sub
    if specific:
        main["type_specific_payload"] = specific
    return main


def _sub_questions(card_type_name: str, p: dict) -> list[dict]:
    """Под-вопросы: из банка (topic/hot_seat/time_capsule) или по механике типа."""
    if p.get("sub_questions"):
        return list(p["sub_questions"])
    if p.get("questions"):
        return [{"text": q, "level": "easy"} for q in p["questions"]]

    q = {
        "would_you_rather": "Which would you choose and why?",
        "debate": "Which side do you agree with, and why?",
        "news_reaction": "What's your reaction to this news?",
        "culture": "Does your culture have an equivalent? How is it different?",
        "storytelling": "What happens next?",
        "roleplay": "What would you say in this situation?",
        "two_truths": "Which statement is the lie?",
    }.get(card_type_name)
    return [{"text": q, "level": "medium"}] if q else []


def _type_specific(card_type_name: str, p: dict) -> dict:
    """type_specific_payload по типу карточки."""
    if card_type_name == "would_you_rather":
        return {"option_a": p.get("option_a", ""), "option_b": p.get("option_b", "")}
    if card_type_name == "roleplay":
        return {"scenario": p.get("scenario", ""), "roles": p.get("roles", [])}
    if card_type_name == "storytelling":
        return {"starter_sentence": p.get("starter_sentence", "")}
    if card_type_name == "culture":
        return {"idiom": p.get("idiom", ""), "meaning": p.get("meaning", ""), "example": p.get("example", "")}
    if card_type_name == "debate":
        return {"statement": p.get("statement", ""), "sides": p.get("sides", ["For", "Against"])}
    if card_type_name == "news_reaction":
        return {"headline": p.get("headline", ""), "summary": p.get("summary", "")}
    if card_type_name == "game_day":
        return {"activity_id": p.get("activity_id", "")}
    if card_type_name == "time_capsule":
        return {"prompt": p.get("prompt", "")}
    return {}


def _vocab_box(card_type_name: str, p: dict) -> list[dict]:
    """Полезная лексика: из банка (culture) или generic-фразы обсуждения."""
    if card_type_name == "culture" and p.get("idiom"):
        return [{"phrase": p["idiom"], "translation": p.get("meaning", ""), "example": p.get("example", "")}]
    if card_type_name == "news_reaction" and p.get("headline"):
        return [{"phrase": p["headline"].split()[0].strip(","), "translation": "", "example": p["headline"]}]
    return [
        {"phrase": "In my opinion, …", "translation": "по моему мнению", "example": "In my opinion, this is a great idea."},
        {"phrase": "I see what you mean, but …", "translation": "понимаю, о чём ты, но…", "example": "I see what you mean, but I disagree."},
    ]
