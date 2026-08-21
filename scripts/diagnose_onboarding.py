# scripts/diagnose_onboarding.py
"""Диагностика онбординга: вывод карточки и проверка submit без uvicorn."""
import asyncio
import json

from app.api.google_chat import _onboarding_card, _submit_onboarding
from app.services.onboarding_answers import parse_onboarding_form


def inspect_card() -> None:
    card = _onboarding_card("Тест")
    widgets_summary = []
    for card_v2 in card.get("cardsV2", []):
        for section in card_v2.get("card", {}).get("sections", []):
            for widget in section.get("widgets", []):
                if "selectionInput" in widget:
                    si = widget["selectionInput"]
                    widgets_summary.append(
                        f"selectionInput name={si['name']} type={si['type']} items={len(si['items'])}"
                    )
                elif "textInput" in widget:
                    ti = widget["textInput"]
                    widgets_summary.append(f"textInput name={ti['name']} label={ti.get('label')}")
                elif "buttonList" in widget:
                    buttons = widget["buttonList"].get("buttons", [])
                    names = [
                        b.get("onClick", {}).get("action", {}).get("function")
                        for b in buttons
                    ]
                    widgets_summary.append(f"buttonList functions={names}")
                elif "textParagraph" in widget:
                    widgets_summary.append("textParagraph")

    print("=== Карточка: структура виджетов ===")
    for line in widgets_summary:
        print(line)

    print("\n=== Карточка: полный JSON ===")
    print(json.dumps(card, ensure_ascii=False, indent=2))


async def inspect_submit() -> None:
    sample_form = {
        "q1": {"stringInputs": {"value": ["it", "travel"]}},
        "q1_other": {"stringInputs": {"value": ["космос"]}},
        "q2": {"stringInputs": {"value": ["chill"]}},
        "q2_other": {"stringInputs": {"value": []}},
        "q3": {"stringInputs": {"value": ["нейросети"]}},
        "q4": {"stringInputs": {"value": ["mon", "wed", "fri"]}},
        "q4_other": {"stringInputs": {"value": ["только вечером"]}},
        "q5": {"stringInputs": {"value": ["busy"]}},
        "q5_other": {"stringInputs": {"value": []}},
        "q6": {"stringInputs": {"value": ["anonymous"]}},
        "q7": {"stringInputs": {"value": ["soft"]}},
    }
    print("\n=== Парсинг formInputs ===")
    parsed = parse_onboarding_form(sample_form)
    for item in parsed:
        print(f"Q: {item['question'][:50]}... | choice={item['choice']} | text={item['text']}")

    user = {
        "name": "users/test_diagnose",
        "displayName": "Тест Диагност",
        "email": "test-diagnose@example.com",
    }
    response = await _submit_onboarding(user, "spaces/test_diagnose", sample_form)
    print("\n=== Ответ пользователю ===")
    print(response)


if __name__ == "__main__":
    inspect_card()
    asyncio.run(inspect_submit())
