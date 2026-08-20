"""Еженедельный опрос: карточка, парсинг ответов, дедлайн, рассылка, сабмит.

Чистые функции в начале файла (тестируются юнитами), БД-функции ниже
(проверяются интеграционными скриптами на поднятом Postgres).
"""
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def slot_day_time(slot_start: datetime) -> tuple[str, str]:
    """День недели и время слота в формате схемы Slot: ("Wed", "19:00")."""
    return slot_start.strftime("%a"), slot_start.strftime("%H:%M")


def compute_deadline(slot_times: list[datetime], buffer_hours: int) -> datetime:
    """Дедлайн голосования: самый ранний слот минус буфер (REQ-2.3)."""
    return min(slot_times) - timedelta(hours=buffer_hours)


def parse_poll_form(form_inputs: dict) -> dict:
    """Разобрать formInputs карточки опроса.

    Возвращает {"answers": [("q_llm", "текст"), ("q_bank", "текст")],
    "slot_ids": [int, ...]}. Слоты — все значения полей, не начинающиеся с "q_".
    Обрабатывает оба формата Google: {name: {"stringInputs": {...}}} и
    add-on {name: {"": {"stringInputs": {...}}}}.
    """
    answers = []
    slot_ids = []
    for name, field in (form_inputs or {}).items():
        if not isinstance(field, dict):
            continue
        payload = field.get("stringInputs") or field.get("")
        if not isinstance(payload, dict):
            continue
        values = [v.strip() for v in payload.get("value", []) if isinstance(v, str) and v.strip()]
        if not values:
            continue
        if name.startswith("q_"):
            answers.append((name, values[0]))
        else:
            for v in values:
                try:
                    slot_ids.append(int(v))
                except (TypeError, ValueError):
                    logger.warning("poll_bad_slot_value value=%r", v)
    return {"answers": answers, "slot_ids": slot_ids}


def build_poll_card(personal_q: str, bank_q: str, slots: list[dict]) -> dict:
    """Cards V2 карточка опроса: 2 текстовых ответа + чекбоксы слотов."""
    question_widgets = []
    for name, label in (("q_llm", personal_q), ("q_bank", bank_q)):
        question_widgets.append({
            "textInput": {"name": name, "label": label, "multiline": True}
        })

    slot_widgets = [{
        "selectionInput": {
            "name": "slots",
            "label": "Отметь слоты, которые тебе подходят (можно несколько)",
            "type": "CHECK_BOX",
            "items": [
                {"text": s["label"], "value": str(s["id"]), "selected": False}
                for s in slots
            ],
        }
    }] if slots else [{
        "textParagraph": {
            "text": "На эту неделю слоты ещё не заданы — обсудим время на встрече."
        }
    }]

    return {
        "cardsV2": [
            {
                "cardId": "weeklyPoll",
                "card": {
                    "header": {
                        "title": "Еженедельный опрос 🗓️",
                        "subtitle": "Ответь на 2 вопроса и отметь удобное время",
                    },
                    "sections": [
                        {"header": "Вопросы недели", "widgets": question_widgets},
                        {"header": "Время встречи", "widgets": slot_widgets},
                        {
                            "widgets": [
                                {
                                    "buttonList": {
                                        "buttons": [
                                            {
                                                "text": "Отправить",
                                                "onClick": {
                                                    "action": {
                                                        "function": "weekly_poll_submit",
                                                        "parameters": [
                                                            {"key": "method", "value": "submit_weekly_poll"}
                                                        ],
                                                    }
                                                },
                                            }
                                        ]
                                    }
                                }
                            ]
                        },
                    ],
                },
            }
        ]
    }