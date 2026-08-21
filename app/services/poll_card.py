# app/services/poll_card.py
"""Карточка (Cards V2) для еженедельного голосования за день встречи.

Чистая функция — без БД, сети и asyncio. Только строит JSON карточки.
Время на карточке пока фиксированное: 13:00–14:00 (по требованию ТЗ
сейчас один слот времени на день).

Вызывающий слой (вебхук) отправляет карточку в DM через chat_sender /
onboarding-паттерн и обрабатывает submit с method='submit_poll_vote'.

Формат ответа готов и для классического Chat App ({"cardsV2": [...]}),
и для Workspace Add-on (нужно обернуть в hostAppDataAction —
это делает вызывающий слой, здесь только содержимое карточки).
"""
from datetime import date

from app.services.poll_logic import RU_DAYS, week_dates

TIME_LABEL = "13:00–14:00"
# Плейсхолдеры тематических вопросов — заменятся, когда появятся
# реальные вопросы из ТЗ (ответы пойдут в таблицу answers).
DEFAULT_THEME_QUESTIONS = (
    "Какая тема тебе интересна на этой встрече?",
    "Что бы ты хотел(а) обсудить или попрактиковать?",
)


def _day_item(d: date) -> dict:
    """Пункт выбора дня: подпись с эмодзи, value = ISO-дата (маппится
    на слот дня в poll_slots через slot_key 'YYYY-MM-DDT1300')."""
    return {"text": f"{RU_DAYS[d.weekday()]} {d.day:02d}.{d.month:02d}", "value": d.isoformat(), "selected": False}


def build_poll_card(
    week_start: date,
    user_name: str = "друг",
    quorum: int = 3,
    action_function: str = "submit_poll_vote",
    action_method: str = "submit_poll_vote",
    theme_questions: tuple[str, str] = DEFAULT_THEME_QUESTIONS,
) -> dict:
    """Собрать cardsV2 для голосования за день встречи.

    Секции:
      1. приветствие + правила (ближайший день с кворумом, время 13:00)
      2. выбор дня (CHECK_BOX, можно несколько дней)
      3. время (фиксированное 13:00–14:00)
      4. тематика (2 вопроса-плейсхолдера)
      5. кнопка «Забронировать день»
      6. примечание о приватности
    """
    days = week_dates(week_start)

    widgets_intro = [
        {
            "textParagraph": {
                "text": (
                    "Привет, {name}! Выбери день, когда тебе удобно встретиться 🗓\n\n"
                    "Встреча пройдёт в ПЕРВЫЙ день, когда наберётся минимум {quorum} "
                    "участника. Время пока одно на всех — {time}.".format(
                        name=user_name, quorum=quorum, time=TIME_LABEL
                    )
                )
            }
        }
    ]

    widgets_days = [
        {
            "selectionInput": {
                "name": "days",
                "label": "Выбери день (можно несколько)",
                "type": "CHECK_BOX",
                "items": [_day_item(d) for d in days],
            }
        }
    ]

    widgets_time = [
        {
            "textParagraph": {
                "text": f"🕐 Время: {TIME_LABEL} (фиксированное, пока одно)"
            }
        }
    ]

    widgets_themes = [
        {
            "textInput": {
                "name": f"q_theme{i + 1}",
                "label": q,
            }
        }
        for i, q in enumerate(theme_questions)
    ]

    widgets_submit = [
        {
            "buttonList": {
                "buttons": [
                    {
                        "text": "Забронировать день 🚀",
                        "onClick": {
                            "action": {
                                "function": action_function,
                                "parameters": [{"key": "method", "value": action_method}],
                            }
                        },
                    }
                ]
            }
        }
    ]

    widgets_privacy = [
        {
            "textParagraph": {
                "text": (
                    "🔒 Твои ответы по темам могут звучать на встречах. "
                    "Если не хочешь — просто напиши об этом в ответе."
                )
            }
        }
    ]

    card = {
        "header": {
            "title": f"Привет, {user_name}! Выбери день 🗓",
            "subtitle": "Помогаем договориться, когда соберёмся говорить по-английски",
            "imageUrl": "https://fonts.gstatic.com/s/i/googlematerialicons/event/v1/24px.svg",
            "imageType": "CIRCLE",
        },
        "sections": [
            {"widgets": widgets_intro},
            {"header": "1. День", "widgets": widgets_days},
            {"header": "2. Время", "widgets": widgets_time},
            {"header": "3. Тематика (поможет выбрать активность)", "widgets": widgets_themes},
            {"widgets": widgets_submit},
            {"widgets": widgets_privacy},
        ],
    }

    return {
        "cardsV2": [
            {
                "cardId": "weeklyPollForm",
                "card": card,
            }
        ]
    }