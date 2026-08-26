"""Еженедельные вопросы в личку: генерация (LLM + банк-фолбэк) и отправка.

Вопросы персональные: LLM (Azati) опирается на интересы, уровень и прошлые
ответы участника. Заданные вопросы сохраняются в `weekly_questions`, чтобы не
повторяться — и LLM (через контекст), и банк (через exclude) исключают ранее
заданные. Если ключа нет или генерация упала — детерминированный банк.
"""
import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Answer, Profile, WeeklyQuestion
from app.services import llm_questions
from app.services.chat_sender import send_message
from app.services.onboarding import current_week_start
from app.services.question_bank import bank_questions_for

logger = logging.getLogger(__name__)

# Сколько последних заданных вопросов учитывать, чтобы не повторяться.
_RECENT_QUESTIONS_LIMIT = 20


async def _recent_answers(db: AsyncSession, profile_id: int, limit: int = 6) -> list[str]:
    """Последние свободные ответы участника (для персонализации вопросов)."""
    rows = (
        await db.execute(
            select(Answer)
            .where(Answer.profile_id == profile_id, Answer.answer_text.isnot(None))
            .order_by(Answer.answered_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [r.answer_text.strip() for r in rows if r.answer_text and r.answer_text.strip()]


async def _recent_asked_questions(
    db: AsyncSession, profile_id: int, limit: int = _RECENT_QUESTIONS_LIMIT
) -> list[str]:
    """Последние заданные участнику вопросы (для исключения повторов)."""
    rows = (
        await db.execute(
            select(WeeklyQuestion.question_text)
            .where(WeeklyQuestion.profile_id == profile_id)
            .order_by(WeeklyQuestion.asked_at.desc(), WeeklyQuestion.id.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [q for q in rows if q]


async def latest_questions_for(
    db: AsyncSession, profile_id: int, within_days: int = 7
) -> list[str]:
    """Вопросы последней рассылки (в пределах `within_days` дней), или пусто.

    Нужно, чтобы понять, что свободное сообщение пользователя — это ответ на
    вопросы недели, и связать этот ответ с заданными вопросами.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=within_days)
    rows = (
        await db.execute(
            select(WeeklyQuestion.question_text)
            .where(
                WeeklyQuestion.profile_id == profile_id,
                WeeklyQuestion.asked_at >= cutoff,
            )
            .order_by(WeeklyQuestion.asked_at.desc(), WeeklyQuestion.id.desc())
            .limit(2)
        )
    ).scalars().all()
    # Сначала вернулись последние (по id) — разворачиваем в хронологический
    # порядок, чтобы первый вопрос шёл первым (важно для карточки с полями).
    questions = [q for q in rows if q]
    questions.reverse()
    return questions


def _build_context(profile: Profile, recent_answers: list[str], asked: list[str]) -> str:
    """Строковый контекст участника для LLM (с уже заданными вопросами)."""
    lines: list[str] = []
    if profile.interests:
        lines.append("Interests: " + ", ".join(profile.interests))
    if profile.english_level:
        lines.append("English level: " + profile.english_level)
    onboarding = profile.onboarding_answers or {}
    if isinstance(onboarding, dict):
        for question, answer in onboarding.items():
            if not isinstance(answer, dict):
                continue
            value = " ".join(x for x in (answer.get("choice", ""), answer.get("text", "")) if x)
            if value:
                lines.append(f"{question}: {value}")
    if recent_answers:
        lines.append("Recent answers: " + " | ".join(recent_answers))
    if asked:
        lines.append("Already asked (don't repeat these): " + " | ".join(asked))
    return "\n".join(lines) or "no participant data"


def _finalize_questions(candidates: list[str], asked: set[str], week: date) -> list[str]:
    """Убрать повторы и добить до двух вопросов из банка."""
    result: list[str] = []
    for q in candidates:
        if q and q not in asked and q not in result:
            result.append(q)
    if len(result) < 2:
        extra = bank_questions_for(week, exclude=asked | set(result))
        for q in extra:
            if q not in result:
                result.append(q)
            if len(result) == 2:
                break
    return result[:2]


async def _persist_questions(db: AsyncSession, profile_id: int, questions: list[str]) -> None:
    """Сохранить заданные вопросы в историю, чтобы не повторяться."""
    week_start = current_week_start()
    for q in questions:
        db.add(WeeklyQuestion(profile_id=profile_id, question_text=q, week_start=week_start))
    await db.commit()


async def weekly_questions_for(db: AsyncSession, profile: Profile) -> list[str]:
    """Два вопроса недели для участника: LLM по контексту, иначе банк. Без повторов."""
    recent_answers = await _recent_answers(db, profile.id)
    asked = await _recent_asked_questions(db, profile.id)
    asked_set = set(asked)
    context = _build_context(profile, recent_answers, asked)

    generated: list[str] = []
    try:
        generated = await asyncio.to_thread(llm_questions.generate_weekly_questions, context)
    except Exception:
        logger.exception("weekly_questions_llm_failed profile=%s", profile.id)
        generated = []
    if not generated:
        generated = []

    week = datetime.now(timezone.utc).date()
    questions = _finalize_questions(generated, asked_set, week)
    await _persist_questions(db, profile.id, questions)
    return questions


def build_weekly_questions_card(
    questions: list[str], action_url: str, answered: bool = False
) -> dict:
    """Карточка «Вопросы недели»: поля для ответов + кнопка «Отправить».

    После отправки (answered=True) поля и кнопка заменяются сообщением
    «Ответ отправлен» — так кнопку нельзя нажать повторно (submit один раз).
    """
    if answered:
        sections = [
            {
                "widgets": [
                    {
                        "textParagraph": {
                            "text": "✅ Answers sent! Saved — we'll discuss them at the next meeting."
                        }
                    }
                ]
            }
        ]
    else:
        sections = [
            {
                "header": "Answer both questions",
                "widgets": [
                    {
                        "textParagraph": {
                            "text": (
                                "Write in English (any language works) — "
                                "practice is what matters 🙂"
                            )
                        }
                    }
                ],
            }
        ]
        for i, q in enumerate(questions, 1):
            sections.append(
                {
                    "header": f"{i}. {q}",
                    "widgets": [
                        {
                            "textInput": {
                                "name": f"answer{i}",
                                "label": "Your answer",
                                "type": "MULTIPLE_LINE",
                                "hintText": "e.g. I’d love to talk about…",
                            }
                        }
                    ],
                }
            )
        sections.append(
            {
                "widgets": [
                    {
                        "buttonList": {
                            "buttons": [
                                {
                                    "text": "Submit answers",
                                    "color": {
                                        "red": 0.16,
                                        "green": 0.52,
                                        "blue": 0.96,
                                        "alpha": 1,
                                    },
                                    "onClick": {
                                        "action": {
                                            "function": action_url or "submit_weekly_questions",
                                            "parameters": [
                                                {
                                                    "key": "method",
                                                    "value": "submit_weekly_questions",
                                                }
                                            ],
                                        }
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        )
    return {
        "cardsV2": [
            {
                "cardId": "weeklyQuestions",
                "card": {
                    "header": {
                        "title": "🎯 Questions of the week",
                        "subtitle": "We'll discuss your answers at the next meeting",
                    },
                    "sections": sections,
                },
            }
        ]
    }


async def has_answered_questions(
    db: AsyncSession, profile_id: int, questions: list[str]
) -> bool:
    """True, если участник уже отвечал хотя бы на один из `questions` (через карточку)."""
    if not questions:
        return False
    row = (
        await db.execute(
            select(Answer.id)
            .where(
                Answer.profile_id == profile_id,
                Answer.question_text.in_(questions),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return row is not None


async def send_weekly_questions(db: AsyncSession, profile: Profile) -> bool:
    """Отправить карточку «Вопросы недели» в личку участника. True при отправке."""
    if not profile.chat_space_id:
        return False
    questions = await weekly_questions_for(db, profile)
    card = build_weekly_questions_card(questions, get_settings().chat_app_audience)
    send_message(
        profile.chat_space_id,
        text="🎯 Questions of the week",
        cards_v2=card["cardsV2"],
    )
    logger.info("weekly_questions_sent profile=%s", profile.id)
    return True
