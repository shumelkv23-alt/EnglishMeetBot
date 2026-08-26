"""Занятие-карточка: генерация темы + плана занятия, рендер карточки, reroll.

Поток:
  - generate_and_post_lesson — авто-генерация при сборке встречи (13:00): выбрать
    случайный формат, получить план (LLM → банк), сохранить LessonSession, постить
    карточку в группу;
  - reroll_lesson — по кнопке «Different topic/format» перегенерировать план и
    обновить карточку на месте (message_name патчится).

Дедупликация тем: использованные темы — это topic существующих LessonSession.
"""
import asyncio
import logging
import random

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LessonSession
from app.services.chat_sender import send_message as send_space_message
from app.services.lesson_bank import bank_lesson
from app.services.llm_lesson import (
    ALL_FORMATS,
    FORMAT_LABELS,
    generate_lesson,
)

logger = logging.getLogger(__name__)

DEFAULT_LEVEL = "B1"
DURATION_MIN = 45
CARD_ID = "lessonCard"


def _bullets(items: list[str]) -> str:
    """Список строк как буллеты в одном textParagraph."""
    return "\n".join(f"• {x}" for x in items)


def _random_format(exclude: str | None = None) -> str:
    formats = [f for f in ALL_FORMATS if f != exclude]
    return random.choice(formats)


async def used_topics(db: AsyncSession, exclude_session: int | None = None) -> list[str]:
    """Темы уже сгенерированных карточек (для дедупликации)."""
    q = select(LessonSession.topic)
    if exclude_session is not None:
        q = q.where(LessonSession.id != exclude_session)
    rows = (await db.execute(q)).scalars().all()
    return [t for t in rows if t]


async def _generate_content(
    format: str,
    level: str,
    exclude_topics: list[str],
) -> dict | None:
    """План занятия: сначала LLM, при сбое — детерминированный банк (REQ-10)."""
    lesson = await asyncio.to_thread(generate_lesson, format, level, exclude_topics)
    if lesson is not None:
        return lesson
    logger.info("lesson_using_bank format=%s", format)
    return bank_lesson(format, set(exclude_topics), offset=len(exclude_topics))


def build_lesson_card(
    content: dict,
    format: str,
    action_url: str = "",
    session_id: int | None = None,
) -> dict:
    """Рендер карточки занятия в `{"cardsV2": [...]}`.

    Кнопки reroll шлют method=lesson_reroll_topic / lesson_reroll_format + session.
    """
    label = FORMAT_LABELS.get(format, format)
    topic = content["topic"]
    level = content.get("level", DEFAULT_LEVEL)

    sections = [
        {
            "header": "🗣 Warm-up (5 min)",
            "widgets": [{"textParagraph": {"text": content["warmup"]}}],
        },
        {
            "header": "💬 Words to know",
            "widgets": [{"textParagraph": {"text": " · ".join(content["words"])}}],
        },
        {
            "header": f"⚔️ Main: {label}",
            "widgets": [
                {"textParagraph": {"text": content["main_instruction"]}},
                {"textParagraph": {"text": _bullets(content["main_items"])}},
            ],
        },
        {
            "header": "💡 Useful phrases",
            "widgets": [{"textParagraph": {"text": " · ".join(content["phrases"])}}],
        },
        {
            "header": "🔁 Keep it going",
            "widgets": [{"textParagraph": {"text": _bullets(content["follow_ups"])}}],
        },
        {
            "header": "🎯 Wrap-up (10 min)",
            "widgets": [{"textParagraph": {"text": content["wrapup"]}}],
        },
    ]

    if action_url and session_id is not None:
        sections.append({
            "widgets": [{"buttonList": {"buttons": [
                {
                    "text": "🎲 Different topic",
                    "onClick": {"action": {
                        "function": action_url,
                        "parameters": [
                            {"key": "method", "value": "lesson_reroll_topic"},
                            {"key": "session", "value": str(session_id)},
                        ],
                    }},
                },
                {
                    "text": "🎲 Different format",
                    "onClick": {"action": {
                        "function": action_url,
                        "parameters": [
                            {"key": "method", "value": "lesson_reroll_format"},
                            {"key": "session", "value": str(session_id)},
                        ],
                    }},
                },
            ]}}],
        })

    return {
        "cardsV2": [{
            "cardId": CARD_ID,
            "card": {
                "header": {
                    "title": f"📖 {topic}",
                    "subtitle": f"{label} · {level} · ~{DURATION_MIN} min",
                },
                "sections": sections,
            },
        }]
    }


async def generate_and_post_lesson(
    db: AsyncSession,
    meeting_id: int,
    space_id: str,
    action_url: str = "",
    level: str = DEFAULT_LEVEL,
) -> LessonSession | None:
    """Сгенерировать и постить карточку занятия для встречи; None при сбое.

    Сначала сохраняем LessonSession (нужен id для кнопок), затем строим карточку,
    постим в группу и запоминаем имя сообщения для последующего patch.
    """
    if not space_id:
        return None
    used = await used_topics(db)
    format = _random_format()
    content = await _generate_content(format, level, used)
    if content is None:
        logger.warning("lesson_generate_empty meeting=%s", meeting_id)
        return None

    session = LessonSession(
        meeting_instance_id=meeting_id,
        topic=content["topic"],
        format=format,
        level=content.get("level", level),
        content=content,
    )
    db.add(session)
    await db.flush()  # нужен session.id для параметров кнопок

    card = build_lesson_card(content, format, action_url, session_id=session.id)
    try:
        resp = send_space_message(space_id, text="📖 Today's lesson is ready!", cards_v2=card["cardsV2"])
    except Exception:
        logger.exception("lesson_post_failed meeting=%s", meeting_id)
        return None
    name = resp.get("name")
    if name:
        session.message_name = name
    await db.commit()
    logger.info("lesson_posted session=%s topic=%r format=%s", session.id, content["topic"], format)
    return session


async def reroll_lesson(
    db: AsyncSession,
    session_id: int,
    change: str,
    action_url: str = "",
) -> dict | None:
    """Перегенерировать карточку: change='topic' — новый топик (тот же формат),
    change='format' — новый формат. Возвращает новую `{"cardsV2": [...]}` или None.
    """
    session = await db.get(LessonSession, session_id)
    if session is None:
        logger.warning("lesson_reroll_no_session id=%s", session_id)
        return None

    used = await used_topics(db, exclude_session=session.id)
    exclude = used + [session.topic]
    new_format = session.format if change == "topic" else _random_format(session.format)
    content = await _generate_content(new_format, session.level, exclude)
    if content is None:
        return None

    session.topic = content["topic"]
    session.format = new_format
    session.level = content.get("level", session.level)
    session.content = content
    await db.commit()
    logger.info("lesson_rerolled session=%s change=%s topic=%r", session.id, change, content["topic"])
    return build_lesson_card(content, new_format, action_url, session_id=session.id)
