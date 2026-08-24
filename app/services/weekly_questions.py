"""Еженедельный вопрос: карточка, выбор вопроса, сабмит и рассылка."""
import asyncio
import logging
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.messaging import send_message
from app.models import Answer, Profile
from app.schemas import MessagePayload
from app.services.form_parsing import parse_form_inputs
from app.services.llm_questions import generate_personal_question
from app.services.question_bank import bank_questions_for

logger = logging.getLogger(__name__)


def current_week_start() -> date:
    """Понедельник текущей недели в таймзоне приложения."""
    from app.services.weekly_poll import today

    t = today()
    return t - timedelta(days=t.weekday())


def question_for_profile(interests: list[str] | None, week_start: date) -> str:
    """Персональный вопрос: LLM по интересам, fallback — банк недели."""
    question = generate_personal_question(interests or [])
    if question is not None:
        return question
    return bank_questions_for(week_start)[0]


def build_weekly_question_card(question: str, action_url: str) -> dict:
    """Карточка еженедельного вопроса: текст + поле + кнопка «Отправить ответ»."""
    return {
        "cardsV2": [{
            "cardId": "weeklyQuestion",
            "card": {
                "header": {"title": "Вопрос недели 💭", "subtitle": "Ответь — из ответов соберём активность"},
                "sections": [
                    {"widgets": [{"textParagraph": {"text": question}}]},
                    {"widgets": [{"textInput": {"name": "answer", "label": "Твой ответ"}}]},
                    {"widgets": [{"buttonList": {"buttons": [{
                        "text": "Отправить ответ",
                        "onClick": {"action": {
                            "function": action_url or "submit_weekly_question",
                            "parameters": [
                                {"key": "method", "value": "submit_weekly_question"},
                                {"key": "question", "value": question},
                            ],
                        }},
                    }]}}]},
                ],
            },
        }]
    }


async def submit_weekly_question(
    db: AsyncSession, profile: Profile, form_inputs: dict, question_text: str
) -> dict:
    """Сохранить ответ на еженедельный вопрос в answers."""
    values = parse_form_inputs(form_inputs).get("answer", [])
    if not values:
        return {"ok": False, "reason": "empty"}
    db.add(Answer(
        profile_id=profile.id,
        question_text=question_text or "Вопрос недели",
        answer_text=values[0],
        week_start=current_week_start(),
    ))
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
                    Answer.profile_id == p.id, Answer.week_start == week_start,
                )
            )
        ).scalar_one()
        if answered:
            continue
        question = await asyncio.to_thread(question_for_profile, p.interests, week_start)
        send_message(
            p.workspace_user_id,
            MessagePayload(
                text="Вопрос недели 💭",
                card=build_weekly_question_card(question, get_settings().chat_app_audience),
            ),
        )
        sent += 1
    logger.info("weekly_questions_sent sent=%s", sent)
    return sent
