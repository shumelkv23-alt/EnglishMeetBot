"""Сид движка карточек: каталог 12 типов + стартовый контент-банк.

Контент-банк критичен для tier 2 типов (debate, news_reaction) — они генерируются
ТОЛЬКО из промодерированного банка (ТЗ §4.7). Для tier 1 банк — фолбэк при сбое LLM.
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cards.catalog import CARD_TYPES
from app.cards.models import CardType, ContentBank
from app.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

# Стартовый контент-банк: card_type -> список payload (формат зависит от типа).
CONTENT_BANK_SEED: dict[str, list[dict]] = {
    "topic": [
        {"topic": "Streaming vs. cinema",
         "sub_questions": [
             {"text": "Do you prefer watching films at home or in a cinema?", "level": "easy"},
             {"text": "How has streaming changed the way people watch films?", "level": "medium"},
             {"text": "Will cinemas still exist in 20 years? Why or why not?", "level": "hard"},
         ]},
        {"topic": "The way we travel",
         "sub_questions": [
             {"text": "What is your favourite kind of trip?", "level": "easy"},
             {"text": "How has travel changed in the last ten years?", "level": "medium"},
             {"text": "Should travel become cheaper or more restricted? Why?", "level": "hard"},
         ]},
        {"topic": "Food habits",
         "sub_questions": [
             {"text": "What is a typical meal you cook?", "level": "easy"},
             {"text": "Why do food trends spread so quickly?", "level": "medium"},
             {"text": "Will people cook more or order more in the future?", "level": "hard"},
         ]},
    ],
    "would_you_rather": [
        {"option_a": "Work remotely forever", "option_b": "Work in an office forever"},
        {"option_a": "Never watch films again", "option_b": "Never listen to music again"},
        {"option_a": "Travel to many places quickly", "option_b": "Live slowly in one beautiful place"},
        {"option_a": "Always speak a foreign language", "option_b": "Always understand animals"},
    ],
    "roleplay": [
        {"scenario": "Ordering food in a restaurant where the waiter got your order wrong",
         "roles": ["Customer", "Waiter"]},
        {"scenario": "Calling a hotel to change your booking at the last minute",
         "roles": ["Guest", "Receptionist"]},
        {"scenario": "Asking a colleague for help with a task you are stuck on",
         "roles": ["Colleague A", "Colleague B"]},
    ],
    "storytelling": [
        {"starter_sentence": "The train stopped in the middle of nowhere and the lights went out."},
        {"starter_sentence": "When I opened the door, I saw something I had lost ten years ago."},
        {"starter_sentence": "Everyone in the office fell silent when the message arrived."},
    ],
    "culture": [
        {"idiom": "to bite the bullet", "meaning": "to force yourself to do something unpleasant",
         "example": "I hate injections, but I'll just bite the bullet."},
        {"idiom": "to hit the nail on the head", "meaning": "to describe a situation exactly",
         "example": "You hit the nail on the head — that's exactly the problem."},
        {"idiom": "to be on the same page", "meaning": "to understand each other",
         "example": "Let's have a quick call to make sure we're on the same page."},
    ],
    "mystery": [
        {"topic": "Time"},
        {"topic": "Colours"},
        {"topic": "Doors"},
        {"topic": "The sea"},
    ],
    "time_capsule": [
        {"prompt": "Imagine your life ten years from now. Describe one ordinary day."},
        {"prompt": "What were you doing exactly ten years ago? What has changed since then?"},
        {"prompt": "What advice would you send back to your younger self?"},
    ],
    "hot_seat": [
        {"questions": [
            "What is a small habit you are proud of?",
            "What is something you have always wanted to learn?",
            "If you could master one skill overnight, what would it be?",
        ]},
        {"questions": [
            "What is your favourite way to relax?",
            "What is a place you would love to return to?",
            "What is the best piece of advice you have received?",
        ]},
    ],
    "debate": [
        {"statement": "Remote work makes teams more productive than office work.",
         "sides": ["For", "Against"]},
        {"statement": "Social media does more harm than good to friendships.",
         "sides": ["For", "Against"]},
        {"statement": "Learning a language is easier now than twenty years ago.",
         "sides": ["For", "Against"]},
        {"statement": "Team sports teach more than individual sports.",
         "sides": ["For", "Against"]},
    ],
    "news_reaction": [
        {"headline": "Language-learning apps add conversation features for real speaking practice.",
         "summary": "Apps are moving from vocabulary drills to live conversation, aiming to make practice feel closer to real life."},
        {"headline": "City libraries report a rise in visitors joining free language clubs.",
         "summary": "Libraries see more people attending casual meetups to practise languages in person."},
        {"headline": "Teams experiment with shorter, more focused meetings to stay engaged.",
         "summary": "Companies are cutting meeting length and testing new formats to reduce fatigue."},
    ],
}


async def seed_card_types(db: AsyncSession) -> int:
    """Вставить каталог типов (если таблица пуста). Вернуть число созданных строк."""
    existing = (await db.execute(select(CardType.id))).scalars().all()
    if existing:
        return 0
    db.add_all([CardType(**spec) for spec in CARD_TYPES])
    await db.commit()
    logger.info("card_types_seeded count=%s", len(CARD_TYPES))
    return len(CARD_TYPES)


async def seed_content_bank(db: AsyncSession) -> int:
    """Вставить стартовый контент-банк (если пуст). Вернуть число созданных строк."""
    existing = (await db.execute(select(ContentBank.id))).scalars().all()
    if existing:
        return 0

    types = (await db.execute(select(CardType))).scalars().all()
    name_to_id = {t.name: t.id for t in types}
    created = 0
    for name, payloads in CONTENT_BANK_SEED.items():
        type_id = name_to_id.get(name)
        if type_id is None:
            continue
        for payload in payloads:
            db.add(ContentBank(
                card_type_id=type_id,
                safety_tier=2 if name in {"debate", "news_reaction"} else 1,
                payload=payload,
                is_approved=True,
                added_by="seed",
            ))
            created += 1
    await db.commit()
    logger.info("content_bank_seeded count=%s", created)
    return created


async def seed(db: AsyncSession) -> dict:
    """Полный сид: каталог типов + контент-банк."""
    return {
        "card_types": await seed_card_types(db),
        "content_bank": await seed_content_bank(db),
    }


async def ensure_seeded() -> dict:
    """Идемпотентный сид из собственной сессии (для вызова в lifespan)."""
    async with AsyncSessionLocal() as db:
        return await seed(db)
