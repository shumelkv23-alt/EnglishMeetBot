# app/services/levels.py
"""Уровни английского (CEFR): константы, валидация и карточка выбора уровня.

Единый источник описаний уровней для онбординга, команды /level и backfill.
Не импортирует ничего из app — чистый модуль, чтобы не плодить циклические импорты.
"""
CEFR_LEVELS: dict[str, str] = {
    "A1": "Beginner — I know a few words and simple phrases.",
    "A2": "Elementary — I can talk about everyday things in simple sentences.",
    "B1": "Intermediate — I can hold a conversation on familiar topics.",
    "B2": "Upper-Intermediate — I speak fairly fluently, with some mistakes.",
    "C1": "Advanced — I speak fluently on complex topics.",
    "C2": "Proficient — I speak nearly like a native speaker.",
}

CEFR_ORDER: dict[str, int] = {code: i for i, code in enumerate(CEFR_LEVELS)}


def normalize_level(value: str) -> str | None:
    """Канонизировать значение уровня из формы. 'A1'/'a1' → 'A1'; мусор → None."""
    code = (value or "").strip().upper()
    return code if code in CEFR_LEVELS else None


def level_choice_items() -> list[dict]:
    """Опции radio для карточки уровня: text = 'A1 — Beginner', value = 'A1'."""
    return [
        {"text": f"{code} — {CEFR_LEVELS[code].split(' — ')[0]}", "value": code, "selected": False}
        for code in CEFR_LEVELS
    ]


def levels_description() -> str:
    """Расшифровка уровней одним текстом для пояснительного блока."""
    return "\n".join(f"{code} · {desc}" for code, desc in CEFR_LEVELS.items())


def build_level_card(current_level: str | None, action_url: str) -> dict:
    """Карточка выбора уровня (radio + Save). current_level — для строки «Current level»."""
    sections: list[dict] = [
        {
            "widgets": [
                {
                    "textParagraph": {
                        "text": (
                            "We'll use your level to send you questions and vocabulary "
                            "that fit you. This is the only reason we ask."
                        )
                    }
                },
                {"divider": {}},
            ]
        }
    ]
    if current_level:
        sections.append({
            "widgets": [{"textParagraph": {"text": f"Current level: {current_level}"}}]
        })
    sections.append({
        "header": "Pick your level",
        "widgets": [
            {
                "selectionInput": {
                    "name": "q_level",
                    "label": "CEFR level",
                    "type": "RADIO_BUTTON",
                    "items": level_choice_items(),
                }
            },
            {"textParagraph": {"text": levels_description()}},
        ],
    })
    sections.append({
        "widgets": [{
            "buttonList": {"buttons": [{
                "text": "Save",
                "onClick": {"action": {
                    "function": action_url or "set_level",
                    "parameters": [{"key": "method", "value": "set_level"}],
                }},
            }]}
        }]
    })
    return {
        "cardsV2": [{
            "cardId": "levelCard",
            "card": {"header": {"title": "Your English level"}, "sections": sections},
        }]
    }
