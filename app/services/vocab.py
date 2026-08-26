# app/services/vocab.py
"""Персональная лексика к занятию: генерация по уровню и рассылка в личку."""
import asyncio
import logging
from collections import defaultdict

from sqlalchemy.ext.asyncio import AsyncSession

from app.cards.generator.llm import _call_llm, _parse_json
from app.config import get_settings
from app.messaging import send_message
from app.models import MeetingInstance, Profile
from app.schemas import MessagePayload
from app.services.levels import CEFR_LEVELS

logger = logging.getLogger(__name__)

DEFAULT_LEVEL = "A2"

# Fallback-фразы по уровню (на случай сбоя LLM или пустого ключа).
_FALLBACK_VOCAB: dict[str, list[dict]] = {
    "A1": [
        {"phrase": "How are you?", "example": "How are you today?"},
        {"phrase": "I like ...", "example": "I like coffee."},
        {"phrase": "I think ...", "example": "I think it is good."},
    ],
    "A2": [
        {"phrase": "In my opinion, ...", "example": "In my opinion, this is a great idea."},
        {"phrase": "I agree / I disagree", "example": "I disagree with that."},
        {"phrase": "What do you think?", "example": "What do you think about it?"},
    ],
    "B1": [
        {"phrase": "It depends on ...", "example": "It depends on the situation."},
        {"phrase": "I'd rather ...", "example": "I'd rather talk about travel."},
        {"phrase": "To be honest, ...", "example": "To be honest, I'm not sure."},
    ],
    "B2": [
        {"phrase": "On the one hand ... on the other hand ...", "example": "On the one hand it's exciting, on the other hand it's risky."},
        {"phrase": "It's worth noting that ...", "example": "It's worth noting that opinions differ."},
        {"phrase": "From my perspective, ...", "example": "From my perspective, it's a good trade-off."},
    ],
    "C1": [
        {"phrase": "That raises the question of ...", "example": "That raises the question of what 'success' means."},
        {"phrase": "It goes without saying that ...", "example": "It goes without saying that context matters."},
        {"phrase": "Arguably, ...", "example": "Arguably, this is the most important factor."},
    ],
    "C2": [
        {"phrase": "To paint with a broad brush, ...", "example": "To paint with a broad brush, culture shapes how we argue."},
        {"phrase": "That's a nuanced point.", "example": "That's a nuanced point — it depends heavily on context."},
        {"phrase": "Let's not conflate A with B.", "example": "Let's not conflate correlation with causation."},
    ],
}


def _fallback(level: str) -> list[dict]:
    return _FALLBACK_VOCAB.get(level, _FALLBACK_VOCAB[DEFAULT_LEVEL])


async def generate_vocab(level: str, topic: str) -> list[dict]:
    """5–7 фраз по теме под уровень (LLM). Сбой/пустой ключ → fallback."""
    settings = get_settings()
    if not settings.llm_api_key or not settings.llm_games_model:
        return _fallback(level)
    payload = {
        "model": settings.llm_games_model,
        "max_tokens": 1024,
        "system": (
            "You prepare a short vocabulary list for an English learner before a "
            "conversation meetup. All content is strictly in English. Answer ONLY "
            "with valid JSON, no comments or markdown."
        ),
        "messages": [{
            "role": "user",
            "content": (
                f"Level: {level}. Topic: {topic}. "
                "Return strict JSON of the form {\"phrases\": [{\"phrase\": \"...\", \"example\": \"...\"}]} "
                "with 5-7 useful phrases for discussing this topic at this level. "
                "Examples are short, natural sentences in English."
            ),
        }],
    }
    content = await _call_llm(payload, timeout=60.0)
    if not content:
        return _fallback(level)
    data = _parse_json(content)
    phrases = [
        {"phrase": str(p.get("phrase") or "").strip(), "example": str(p.get("example") or "").strip()}
        for p in (data.get("phrases") or [])
        if isinstance(p, dict) and str(p.get("phrase") or "").strip()
    ]
    return phrases or _fallback(level)


def build_vocab_card(topic: str, phrases: list[dict]) -> dict:
    """DM-карточка «Vocabulary for today» со списком фраз."""
    widgets = [
        {"decoratedText": {"topLabel": p["phrase"], "text": p["example"], "wrapText": True}}
        for p in phrases
    ]
    widgets.append({"textParagraph": {"text": "Too easy or too hard? Send /level to adjust 🎯"}})
    return {
        "cardsV2": [{
            "cardId": "vocabCard",
            "card": {
                "header": {"title": f"📚 Vocabulary for today: {topic}"},
                "sections": [{"header": "Useful phrases", "widgets": widgets}],
            },
        }]
    }


def _group_level(profiles: list[Profile]) -> dict[str, list[Profile]]:
    """Сгруппировать профили по уровню; NULL → DEFAULT_LEVEL."""
    groups: dict[str, list[Profile]] = defaultdict(list)
    for p in profiles:
        level = p.english_level if p.english_level in CEFR_LEVELS else DEFAULT_LEVEL
        groups[level].append(p)
    return dict(groups)


async def send_vocab_dms(
    db: AsyncSession,
    meeting: MeetingInstance,
    topic: str,
    profiles: list[Profile],
) -> int:
    """Рассылка лексики участникам в личку (одна генерация на уровень)."""
    sent = 0
    for level, group in _group_level(profiles).items():
        phrases = await generate_vocab(level, topic)
        payload = MessagePayload(
            text=f"📚 Vocabulary for today: {topic}",
            card=build_vocab_card(topic, phrases),
        )
        for p in group:
            if not p.workspace_user_id:
                continue
            try:
                await asyncio.to_thread(send_message, p.workspace_user_id, payload)
                sent += 1
            except Exception:
                logger.exception("vocab_dm_failed profile=%s", p.id)
    logger.info("vocab_sent meeting=%s count=%s", meeting.id, sent)
    return sent
