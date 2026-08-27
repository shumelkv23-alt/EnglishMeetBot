"""Помощник занятия: общается про карточку, тему, игры, переводит (гибрид).

- «topic»/«what are we discussing» → текущая тема + вопросы (текст).
- «how to play X» / «rules of X» → правила игры (текст).
- «what can we do» / «suggest» / «stuck» → карточка с 2-3 короткими идеями (LLM).
- перевод, «не понимаю», любой вопрос → LLM-ответ текстом (с контекстом карточки).

Возвращает message-dict ({'text': ...} или {'cardsV2': ...}) либо None.
"""
import asyncio
import json
import logging

import requests
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cards.activity_matcher import GAMES
from app.cards.models import Card
from app.config import get_settings
from app.models import MeetingInstance

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://llm.azati.ai"
ANTHROPIC_VERSION = "2023-06-01"

# Правила групповых игр (краткие, на английском).
GAME_RULES: dict[str, str] = {
    "alias": "Alias: one player explains a word without saying it or its parts — the team guesses. Most words in the time limit wins.",
    "snake_oil": "Snake Oil: players combine two word cards into an invented 'product' and pitch it to a customer. The most convincing pitch wins.",
    "quiplash": "Quiplash: everyone answers a funny prompt, then the group votes for the best answer.",
    "who_am_i": "Who am I?: guess a secret person or character by asking yes/no questions until you figure it out.",
    "spy": "Spy: everyone knows a secret location except the spy. Players ask questions to find the spy, while the spy tries to blend in.",
    "guesspionage": "Guesspionage: estimate percentages (e.g. 'what % of people…'), and others try to guess the real number.",
}

# «имя в тексте» → activity_id игры.
_GAME_ALIASES: dict[str, str] = {
    "alias": "alias",
    "snake oil": "snake_oil",
    "snakeoil": "snake_oil",
    "quiplash": "quiplash",
    "who am i": "who_am_i",
    "spy": "spy",
    "guesspionage": "guesspionage",
}

_TOPIC_WORDS = ("topic", "theme", "what are we discussing", "what are we talking", "тема")
_NEW_TOPIC_WORDS = ("regenerate", "regenerate topic", "another topic", "change topic",
                    "new topic", "different topic", "change theme", "другую тему",
                    "другая тема", "смени тему", "сменить тему", "поменяй тему")
_RULES_WORDS = ("how to play", "how do you play", "rules", "правила", "как играть")
_QUESTION_WORDS = ("what", "how", "which", "why", "who", "can we", "tell me", "explain",
                   "что", "как", "почему", "кто", "какой", "зачем", "когда")
_TRANSLATE_WORDS = ("translate", "how do you say", "what does", "meaning of", "means",
                    "перевод", "переведи", "перевести", "как сказать", "как будет", "что значит",
                    "как переводится", "по-русски", "на русском", "in russian")
_SUGGEST_WORDS = ("what can we do", "what should we do", "what else", "suggest", "idea",
                  "stuck", "options", "чем заняться", "что делать", "подскажи")
_HELP_WORDS = ("help", "i don't understand", "не понимаю", "не понимаю тему")


def _is_topic_query(text: str) -> bool:
    return any(w in text.lower() for w in _TOPIC_WORDS)


def _is_new_topic_query(text: str) -> bool:
    """Пользователь просит сменить тему занятия на новую."""
    return any(w in text.lower() for w in _NEW_TOPIC_WORDS)


def _extract_game_for_rules(text: str) -> str | None:
    """activity_id игры, если текст — вопрос про её правила."""
    t = text.lower()
    if not any(w in t for w in _RULES_WORDS):
        return None
    for text_alias, activity_id in _GAME_ALIASES.items():
        if text_alias in t:
            return activity_id
    return None


def _is_question(text: str) -> bool:
    t = text.lower().strip()
    return t.endswith("?") or any(t.startswith(w) for w in _QUESTION_WORDS)


def _is_translation_query(text: str) -> bool:
    return any(w in text.lower() for w in _TRANSLATE_WORDS)


def _is_suggest_query(text: str) -> bool:
    return any(w in text.lower() for w in _SUGGEST_WORDS)


def _is_help_query(text: str) -> bool:
    return any(w in text.lower() for w in _HELP_WORDS)


async def _current_card(db: AsyncSession, space_id: str) -> Card | None:
    """Последняя сгенерированная карточка группы (или None)."""
    return (
        await db.execute(
            select(Card).where(Card.space_id == space_id).order_by(Card.created_at.desc()).limit(1)
        )
    ).scalars().first()


def _topic_and_questions(card: Card | None) -> tuple[str | None, list[str]]:
    if card is None:
        return None, []
    main = card.content.get("main_content") or {}
    topic = str(main.get("topic") or "").strip() or None
    questions = [str(q.get("text") or "").strip() for q in (main.get("sub_questions") or [])]
    return topic, [q for q in questions if q]


def _format_topic(topic: str | None, questions: list[str]) -> str:
    if not topic:
        return "There's no topic for this meeting yet — the activity card hasn't been generated."
    if not questions:
        return f"📚 Today's topic: {topic}"
    body = "\n".join(f"{i}. {q}" for i, q in enumerate(questions, 1))
    return f"📚 Today's topic: {topic}\n\n💬 Questions:\n{body}"


def _card_context(card: Card | None) -> str:
    """Контекст карточки для LLM: тема, вопросы, лексика, активность, игры."""
    if card is None:
        return "There is no activity card yet for this meeting."
    main = card.content.get("main_content") or {}
    topic = main.get("topic") or "not set"
    questions = [str(q.get("text") or "") for q in (main.get("sub_questions") or [])]
    vocab = [str(v.get("phrase") or "") for v in (card.content.get("vocab_box") or [])]
    activity = (card.content.get("suggested_activity") or {}).get("activity_id")
    games_list = ", ".join(g["name"] for g in GAMES)
    return (
        f"Current topic: {topic}. "
        f"Discussion questions: {questions or 'none'}. "
        f"Useful phrases: {vocab or 'none'}. "
        f"Suggested activity: {activity or 'none'}. "
        f"Available group games: {games_list}."
    )


def _extract_text(resp_json: dict) -> str:
    content = resp_json.get("content")
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts).strip()


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


async def _call_llm(payload: dict, timeout: float) -> str | None:
    """POST в /v1/messages; вернуть text-контент или None при сбое."""
    settings = get_settings()
    if not settings.llm_api_key or not settings.llm_games_model:
        return None
    headers = {
        "x-api-key": settings.llm_api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    base_url = (settings.llm_base_url or DEFAULT_BASE_URL).rstrip("/")
    try:
        resp = await asyncio.to_thread(
            requests.post, f"{base_url}/v1/messages", json=payload, headers=headers, timeout=timeout
        )
        resp.raise_for_status()
        return _extract_text(resp.json())
    except Exception:
        logger.warning("lesson_assistant_llm_failed", exc_info=True)
        return None


async def _llm_answer(question: str, context: str) -> str | None:
    """Ответ LLM на свободный вопрос/просьбу (английский, краткий)."""
    payload = {
        "model": get_settings().llm_games_model,
        "max_tokens": 800,
        "system": (
            "You are a helpful assistant in an English conversation club. "
            "Always answer in English. The only exception: if the user explicitly asks "
            "for Russian (e.g. 'переведи на русский', 'как это по-русски'), reply with a "
            "single brief message in Russian containing just the translation — nothing else. "
            "Keep answers short (1-3 sentences)."
        ),
        "messages": [{"role": "user", "content": f"Context:\n{context}\n\nUser message: {question}"}],
    }
    return await _call_llm(payload, timeout=60.0)


async def _llm_suggestions(context: str) -> list[dict] | None:
    """3 коротких предложения чем заняться (LLM возвращает JSON)."""
    payload = {
        "model": get_settings().llm_games_model,
        "max_tokens": 700,
        "system": (
            "You suggest activities for an English conversation club. "
            "Answer ONLY with valid JSON, no comments or markdown."
        ),
        "messages": [
            {
                "role": "user",
                "content": (
                    f"Context:\n{context}\n\n"
                    "Suggest 3 short things the group can do next. Each suggestion has a short "
                    "title (2-5 words) and a one-sentence description. "
                    'Return strict JSON of the form {"suggestions": [{"title": "...", "description": "..."}]}.'
                ),
            }
        ],
    }
    content = await _call_llm(payload, timeout=40.0)
    if not content:
        return None
    data = _parse_json(content)
    suggestions = data.get("suggestions")
    if not isinstance(suggestions, list):
        return None
    out = []
    for s in suggestions:
        if not isinstance(s, dict):
            continue
        title = str(s.get("title") or "").strip()
        desc = str(s.get("description") or "").strip()
        if title:
            out.append({"title": title, "description": desc})
    return out or None


def build_suggestions_card(suggestions: list[dict]) -> dict:
    """Карточка с идеями (нумерованные секции, по одной на идею)."""
    sections = []
    for i, s in enumerate(suggestions, 1):
        title = str(s.get("title") or "").strip()
        desc = str(s.get("description") or "").strip()
        if not title:
            continue
        sections.append({
            "header": f"{i}. {title}",
            "widgets": [{"decoratedText": {"text": desc, "wrapText": True}}],
        })
    if not sections:
        return {"text": "Try one of the discussion questions above, or start a group game! 🎲"}
    return {
        "cardsV2": [{
            "cardId": "lessonSuggestions",
            "card": {
                "header": {"title": "Here are a few ideas 💡", "subtitle": "Pick one and jump in"},
                "sections": sections,
            },
        }]
    }


async def _llm_new_topic(current_topic: str | None) -> str | None:
    """LLM придумывает одну свежую тему для занятия (не из банка, не текущая)."""
    settings = get_settings()
    if not settings.llm_api_key or not settings.llm_games_model:
        return None
    avoid = f" Avoid the current topic '{current_topic}'." if current_topic else ""
    payload = {
        "model": settings.llm_games_model,
        "max_tokens": 800,
        "system": (
            "You pick ONE fresh, engaging discussion topic for an English conversation club. "
            "Return only the topic title, up to 8 words, no extra punctuation or commentary."
        ),
        "messages": [{
            "role": "user",
            "content": f"Suggest a brand-new topic, different from common, overused ones.{avoid}",
        }],
    }
    content = await _call_llm(payload, timeout=60.0)
    if not content:
        return None
    topic = content.strip().strip('"').strip()
    return topic or None


async def _regenerate_async(space_id: str, meeting_id: int, old_topic: str | None) -> None:
    """Фоновая перегенерация темы: новая тема → карточка + лексика (проактивно)."""
    from app.cards.service import regenerate_card_for_topic
    from app.database import AsyncSessionLocal

    try:
        new_topic = await _llm_new_topic(old_topic)
        if not new_topic:
            return
        async with AsyncSessionLocal() as db:
            meeting = await db.get(MeetingInstance, meeting_id)
            if meeting is None:
                return
            await regenerate_card_for_topic(db, meeting, space_id, new_topic)
    except Exception:
        logger.exception("regenerate_async_failed space=%s", space_id)


async def handle_lesson_query(db: AsyncSession, text: str, space_id: str) -> dict | None:
    """Ответить на сообщение, если оно — про тему/игры/карточку. Иначе None.

    Возвращает message-dict: {'text': ...} или {'cardsV2': ...}.
    """
    card = await _current_card(db, space_id)
    topic, questions = _topic_and_questions(card)

    if _is_new_topic_query(text):
        if card is None:
            return {"text": "There's no activity card yet — finalize the meeting first."}
        # Генерация темы + карточки + лексики — долгая; уводим в фон,
        # иначе Google Chat таймаутит вебхук и показывает «бот не отвечает».
        asyncio.create_task(_regenerate_async(space_id, card.meeting_id, topic))
        return {"text": "🔄 Generating a new topic — the card and vocabulary will arrive in a moment..."}

    if _is_topic_query(text):
        return {"text": _format_topic(topic, questions)}

    game = _extract_game_for_rules(text)
    if game is not None:
        rule = GAME_RULES.get(game)
        return {"text": f"🎮 {rule}" if rule else "I don't have rules for that game."}

    if _is_suggest_query(text):
        suggestions = await _llm_suggestions(_card_context(card))
        if suggestions:
            return build_suggestions_card(suggestions)

    answer = await _llm_answer(text.strip(), _card_context(card))
    if answer:
        return {"text": answer}

    return None
