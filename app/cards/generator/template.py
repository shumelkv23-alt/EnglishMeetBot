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

_STRETCH_BY_TYPE = {
    "topic": "Go deeper: argue the opposite side of your own answer for a minute.",
    "debate": "Switch sides and defend the position you disagree with.",
    "storytelling": "Add an unexpected plot twist to the story.",
    "would_you_rather": "Argue for the option you did NOT choose.",
    "roleplay": "Swap roles and replay the scene.",
    "culture": "Teach a phrase from your own language that has no English equivalent.",
    "hot_seat": "Ask the person in the hot seat one personal follow-up question.",
    "game_day": "Invent a quick rule variation for the game you just played.",
    "two_truths": "Invent a convincing lie about yourself and make the group guess.",
    "mystery": "Speculate on the weirdest possible answer to today's topic.",
    "news_reaction": "Predict how this news might look in ten years.",
    "time_capsule": "Write a one-sentence message your future self would understand.",
}

_QUESTION_LEVELS = ("easy", "medium", "hard")

# Полный и безопасный fallback: даже без LLM карточка остаётся готовым
# 4-фазным планом с нарастающей сложностью вопросов.
_DEFAULT_SUB_QUESTIONS: dict[str, list[str]] = {
    "topic": ["What comes to mind when you hear this topic?", "Why do people have different opinions about it?", "How might it change in the future?"],
    "debate": ["Which side feels more natural to you at first?", "What is the strongest argument for the other side?", "What would make you change your mind?"],
    "storytelling": ["Who is the main character in this story?", "What problem could this character face next?", "What surprising ending would make the story memorable?"],
    "would_you_rather": ["Which option would you choose?", "What is one advantage and one disadvantage of your choice?", "Could your choice be different in ten years? Why?"],
    "roleplay": ["What would you say first in this situation?", "How could you solve the problem politely?", "How would the conversation change if the first solution failed?"],
    "culture": ["Have you heard a similar expression before?", "When could you use this expression naturally?", "What does this expression reveal about culture or communication?"],
    "hot_seat": ["What is an easy question everyone can answer?", "What follow-up question would make the answer more interesting?", "What could the group learn from a different answer?"],
    "game_day": ["What is the quickest way to explain a difficult word?", "Which strategy would help your team communicate better?", "How could you make the game harder without making it less fun?"],
    "two_truths": ["What is one harmless fact you could share about yourself?", "How can you make a believable lie without making it too obvious?", "What questions would help you spot a convincing lie?"],
    "mystery": ["What is your first guess?", "Which clue would you want to know next?", "What is the most surprising explanation that could still make sense?"],
    "news_reaction": ["What is your first reaction to this story?", "Who could benefit from this change, and who might not?", "How could this trend affect everyday life in the future?"],
    "time_capsule": ["What is one detail you would include?", "What would surprise a person from another time?", "What advice would you leave for your future or past self?"],
}

_GENERIC_VOCAB = [
    {"phrase": "In my opinion, …", "translation": "по моему мнению", "example": "In my opinion, this is a great idea."},
    {"phrase": "I see what you mean, but …", "translation": "понимаю, о чём ты, но…", "example": "I see what you mean, but I disagree."},
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
        "stretch_challenge": _STRETCH_BY_TYPE.get(card_type_name, _STRETCH_BY_TYPE["topic"]),
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
    """Вернуть ровно три уникальных вопроса easy → medium → hard."""
    raw = p.get("sub_questions") or p.get("questions") or []
    if not isinstance(raw, list):
        raw = []

    questions: list[dict] = []
    seen: set[str] = set()
    for item in raw:
        text = item.get("text") if isinstance(item, dict) else item
        text = str(text or "").strip()
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        questions.append({"text": text, "level": _QUESTION_LEVELS[len(questions)]})
        if len(questions) == 3:
            return questions

    for text in _DEFAULT_SUB_QUESTIONS.get(card_type_name, _DEFAULT_SUB_QUESTIONS["topic"]):
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        questions.append({"text": text, "level": _QUESTION_LEVELS[len(questions)]})
        if len(questions) == 3:
            break
    return questions


def _type_specific(card_type_name: str, p: dict) -> dict:
    """type_specific_payload по типу карточки."""
    if card_type_name == "would_you_rather":
        return {
            "option_a": p.get("option_a", "Spend a year without music"),
            "option_b": p.get("option_b", "Spend a year without films"),
        }
    if card_type_name == "roleplay":
        return {
            "scenario": p.get("scenario", "You need to solve a small misunderstanding politely."),
            "roles": p.get("roles", ["Person A", "Person B"]),
        }
    if card_type_name == "storytelling":
        return {"starter_sentence": p.get("starter_sentence", "A surprising message arrived just before sunset.")}
    if card_type_name == "culture":
        return {
            "idiom": p.get("idiom", "to be on the same page"),
            "meaning": p.get("meaning", "to understand each other in the same way"),
            "example": p.get("example", "Let's talk so we can be on the same page."),
        }
    if card_type_name == "debate":
        return {
            "statement": p.get("statement", "A four-day work week would improve everyday life."),
            "sides": p.get("sides", ["For", "Against"]),
        }
    if card_type_name == "news_reaction":
        return {
            "headline": p.get("headline", "Language clubs explore new ways to practise speaking."),
            "summary": p.get("summary", "The group discusses a safe, general trend in language practice."),
        }
    if card_type_name == "game_day":
        return {"activity_id": p.get("activity_id", "alias")}
    if card_type_name == "time_capsule":
        return {"prompt": p.get("prompt", "Imagine one ordinary day in your life ten years from now.")}
    return {}


def _vocab_box(card_type_name: str, p: dict) -> list[dict]:
    """Полезная лексика: из банка (culture) или generic-фразы обсуждения."""
    if card_type_name == "culture" and p.get("idiom"):
        return [
            {"phrase": p["idiom"], "translation": p.get("meaning", ""), "example": p.get("example", "")},
            *_GENERIC_VOCAB,
        ]
    return list(_GENERIC_VOCAB)
