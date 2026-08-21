# app/services/poll_card.py
"""Карточки (Cards V2) ежедневного голосования «в тот же день».

Чистые функции — без БД, сети и asyncio. Только строят JSON карточек.
Три карточки:
  1. build_attendance_card  — «Сможешь сегодня прийти?» [Да / Нет]
  2. build_time_card        — выбор ОДНОГО слота (15–16 / 16–17 / 17–18)
  3. build_checkin_card     — «Ты был(а) на встрече?» [Да / Нет] в конце дня

Кнопки используют action-методы, которые диспатчит вебхук
(app/api/google_chat.py): submit_attendance_yes/no, submit_time,
submit_checkin_yes/no. Паттерн кнопки — как в онбординге.
"""
from datetime import date

from app.services.poll_logic import build_daily_slots, time_label

# Имена action-методов (должны совпадать с обработчиками в google_chat.py)
METHOD_ATTENDANCE_YES = "submit_attendance_yes"
METHOD_ATTENDANCE_NO = "submit_attendance_no"
METHOD_SUBMIT_TIME = "submit_time"
METHOD_CHECKIN_YES = "submit_checkin_yes"
METHOD_CHECKIN_NO = "submit_checkin_no"


def _button(text: str, method: str) -> dict:
    """Кнопка, чей клик диспатчится по параметру method."""
    return {
        "text": text,
        "onClick": {
            "action": {
                "function": method,
                "parameters": [{"key": "method", "value": method}],
            }
        },
    }


def build_attendance_card(user_name: str = "друг") -> dict:
    """Карточка «Сможешь сегодня прийти?» с кнопками Да/Нет."""
    return {
        "cardsV2": [
            {
                "cardId": "dailyAttendance",
                "card": {
                    "header": {
                        "title": f"Привет, {user_name}! 👋",
                        "subtitle": "Ежедневная встреча по английскому",
                        "imageUrl": "https://fonts.gstatic.com/s/i/googlematerialicons/event/v1/24px.svg",
                        "imageType": "CIRCLE",
                    },
                    "sections": [
                        {
                            "widgets": [
                                {
                                    "textParagraph": {
                                        "text": (
                                            "Сегодня в 15:00–18:00 будут встречи "
                                            "по английскому. Сможешь прийти?"
                                        )
                                    }
                                }
                            ]
                        },
                        {
                            "widgets": [
                                {
                                    "buttonList": {
                                        "buttons": [
                                            _button("Да, приду 🙌", METHOD_ATTENDANCE_YES),
                                            _button("Нет, не смогу", METHOD_ATTENDANCE_NO),
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


def build_time_card(user_name: str, day: date) -> dict:
    """Карточка выбора одного слота времени (RADIO_BUTTON + кнопка)."""
    slots = build_daily_slots(day)
    items = [
        {"text": time_label(s), "value": s.slot_key, "selected": False}
        for s in slots
    ]
    return {
        "cardsV2": [
            {
                "cardId": "dailyTime",
                "card": {
                    "header": {
                        "title": "Отлично! Выбери время ⏰",
                        "subtitle": "Можно выбрать одно время",
                        "imageUrl": "https://fonts.gstatic.com/s/i/googlematerialicons/schedule/v1/24px.svg",
                        "imageType": "CIRCLE",
                    },
                    "sections": [
                        {
                            "widgets": [
                                {
                                    "selectionInput": {
                                        "name": "time",
                                        "label": "Когда тебе удобно?",
                                        "type": "RADIO_BUTTON",
                                        "items": items,
                                    }
                                }
                            ]
                        },
                        {
                            "widgets": [
                                {
                                    "buttonList": {
                                        "buttons": [
                                            _button("Записаться 🚀", METHOD_SUBMIT_TIME)
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


def build_checkin_card(user_name: str, meeting_time_label: str) -> dict:
    """Карточка чек-ина в конце дня: «Ты был(а) на встрече?» [Да / Нет]."""
    return {
        "cardsV2": [
            {
                "cardId": "dailyCheckin",
                "card": {
                    "header": {
                        "title": "Чек-ин 📝",
                        "subtitle": "Отметь, был(а) ли ты на встрече",
                        "imageUrl": "https://fonts.gstatic.com/s/i/googlematerialicons/fact_check/v1/24px.svg",
                        "imageType": "CIRCLE",
                    },
                    "sections": [
                        {
                            "widgets": [
                                {
                                    "textParagraph": {
                                        "text": (
                                            f"Привет, {user_name}! Ты был(а) сегодня "
                                            f"на встрече по английскому {meeting_time_label}?"
                                        )
                                    }
                                }
                            ]
                        },
                        {
                            "widgets": [
                                {
                                    "buttonList": {
                                        "buttons": [
                                            _button("Да, был(а) ✅", METHOD_CHECKIN_YES),
                                            _button("Нет, не смог(ла) 🙁", METHOD_CHECKIN_NO),
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
