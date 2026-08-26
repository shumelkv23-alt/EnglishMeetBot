"""Еженедельный вопрос: карточка, выбор вопросов, сабмит и рассылка."""
import asyncio
import logging
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.messaging import send_message
from app.models import Answer, Profile
from app.schemas import MessagePayload
from app.services.form_parsing import parse_form_inputs
from app.services.llm_questions import generate_personal_question
from app.services.levels import build_level_card
from app.services.onboarding import ONBOARDING_QUESTION
from app.services.onboarding_answers import QUESTIONS as ONBOARDING_QUESTIONS
from app.services.question_bank import bank_questions_for

logger = logging.getLogger(__name__)

# Ответы на анкету онбординга не считаем «ответами на вопросы недели».
_ONBOARDING_QUESTIONS = frozenset([ONBOARDING_QUESTION, *ONBOARDING_QUESTIONS.values()])


def current_week_start() -> date:
    """Понедельник текущей недели в таймзоне приложения."""
    from app.services.weekly_poll import week_monday

    return week_monday()


def questions_for_profile(
    interests: list[str] | None, week_start: date, level: str, avoid: list[str] | None = None
) -> tuple[str, str]:
    """Два вопроса недели: (персональный LLM по уровню, общий из банка).

    Персональный — по интересам и уровню, без повтора прошлых (avoid);
    при сбое LLM — запасной банковский (bank[1]). Общий — bank[0], одинаковый для всех.
    """
    bank = bank_questions_for(week_start)
    personal = generate_personal_question(interests or [], level=level, avoid=avoid)
    if personal is None:
        personal = bank[1]
    return personal, bank[0]


def build_weekly_question_card(personal_q: str, bank_q: str, action_url: str) -> dict:
    """Карточка недели: два вопроса + два поля + кнопка «Отправить ответы»."""
    return {
        "cardsV2": [{
            "cardId": "weeklyQuestion",
            "card": {
                "header": {"title": "Question of the week 💭", "subtitle": "Answer — we'll build an activity from the answers"},
                "sections": [
                    {"header": "Personal question", "widgets": [
                        {"textParagraph": {"text": personal_q}},
                        {"textInput": {"name": "q_llm", "label": "Your answer"}},
                    ]},
                    {"header": "General question", "widgets": [
                        {"textParagraph": {"text": bank_q}},
                        {"textInput": {"name": "q_bank", "label": "Your answer"}},
                    ]},
                    {"widgets": [{"buttonList": {"buttons": [{
                        "text": "Submit answers",
                        "onClick": {"action": {
                            "function": action_url or "submit_weekly_question",
                            "parameters": [
                                {"key": "method", "value": "submit_weekly_question"},
                                {"key": "q_llm_text", "value": personal_q},
                                {"key": "q_bank_text", "value": bank_q},
                            ],
                        }},
                    }]}}]},
                ],
            },
        }]
    }


async def submit_weekly_question(
    db: AsyncSession, profile: Profile, form_inputs: dict, q_llm_text: str, q_bank_text: str
) -> dict:
    """Сохранить ответы на оба вопроса недели в answers."""
    values = parse_form_inputs(form_inputs)
    llm_answer = values.get("q_llm", [])
    bank_answer = values.get("q_bank", [])
    if not llm_answer and not bank_answer:
        return {"ok": False, "reason": "empty"}
    week_start = current_week_start()
    if llm_answer:
        db.add(Answer(
            profile_id=profile.id,
            question_text=q_llm_text or "Personal question",
            answer_text=llm_answer[0],
            week_start=week_start,
        ))
    if bank_answer:
        db.add(Answer(
            profile_id=profile.id,
            question_text=q_bank_text or "General question",
            answer_text=bank_answer[0],
            week_start=week_start,
        ))
    from datetime import datetime, timezone

    from app.services.inactivity import touch_activity

    touch_activity(profile, datetime.now(timezone.utc))
    await db.commit()
    logger.info("weekly_question_answered profile=%s", profile.id)
    return {"ok": True, "reason": "saved"}


async def send_weekly_questions(db: AsyncSession) -> int:
    """Рассылка еженедельных вопросов активным профилям без ответа за неделю."""
    week_start = current_week_start()
    profiles = (
        await db.execute(
            select(Profile).where(
                Profile.is_active.is_(True),
                Profile.chat_space_id.isnot(None),
            )
        )
    ).scalars().all()

    sent = 0
    for p in profiles:
        answered = (
            await db.execute(
                select(func.count()).select_from(Answer).where(
                    Answer.profile_id == p.id,
                    Answer.week_start == week_start,
                    Answer.question_text.notin_(_ONBOARDING_QUESTIONS),
                )
            )
        ).scalar_one()
        if answered:
            continue
        if not p.english_level:
            # Ещё не указан уровень — сначала спрашиваем его, а не вопрос недели.
            send_message(
                p.workspace_user_id,
                MessagePayload(
                    text="Quick question about your English level 🙂",
                    card=build_level_card(None, get_settings().chat_app_audience),
                ),
            )
            sent += 1
            continue
        past = list((await db.execute(
            select(Answer.question_text).where(Answer.profile_id == p.id)
        )).scalars().all())
        personal_q, bank_q = await asyncio.to_thread(
            questions_for_profile, p.interests, week_start, p.english_level or "A2", past
        )
        send_message(
            p.workspace_user_id,
            MessagePayload(
                text="Question of the week 💭",
                card=build_weekly_question_card(personal_q, bank_q, get_settings().chat_app_audience),
            ),
        )
        sent += 1
    logger.info("weekly_questions_sent sent=%s", sent)
    return sent
