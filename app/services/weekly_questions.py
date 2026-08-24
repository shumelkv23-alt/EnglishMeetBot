"""Еженедельный вопрос: карточка, выбор вопроса, сабмит и рассылка."""
import logging
from datetime import date, timedelta

from app.config import get_settings
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
