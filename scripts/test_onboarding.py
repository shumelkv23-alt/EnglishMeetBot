# scripts/test_onboarding.py
"""Проверка интерактивного онбординга: карточка + сохранение 7 ответов в БД."""
import asyncio
import logging

from sqlalchemy import select

from app.api.google_chat import _onboarding_card
from app.database import AsyncSessionLocal
from app.models import Answer, Profile
from app.services.onboarding import get_or_create_profile
from app.services.onboarding_answers import (
    QUESTIONS,
    parse_onboarding_form,
    save_onboarding_answers,
)

logging.basicConfig(level=logging.INFO)


def _collect_widgets(card: dict) -> list[dict]:
    """Собрать все виджеты карточки в плоский список."""
    widgets = []
    for card_v2 in card.get("cardsV2", []):
        for section in card_v2.get("card", {}).get("sections", []):
            widgets.extend(section.get("widgets", []))
    return widgets


def _has_widget_type(widgets: list[dict], widget_type: str) -> bool:
    return any(widget_type in widget for widget in widgets)


def _count_widget_type(widgets: list[dict], widget_type: str) -> int:
    return sum(1 for widget in widgets if widget_type in widget)


async def main() -> None:
    test_user_id = "users/test_onboarding_check"
    test_space = "spaces/test_onboarding_space"
    test_email = "test-onboarding@example.com"
    test_name = "Тестовый Пользователь"

    # 1. Проверяем структуру карточки
    card = _onboarding_card(test_name)
    widgets = _collect_widgets(card)

    assert _has_widget_type(widgets, "selectionInput"), "Нет selectionInput"
    assert _has_widget_type(widgets, "textInput"), "Нет textInput"
    assert _has_widget_type(widgets, "buttonList"), "Нет кнопки Submit"
    assert _count_widget_type(widgets, "selectionInput") == 6, "Должно быть 6 selectionInput"
    assert _count_widget_type(widgets, "textInput") == 5, "Должно быть 5 textInput (q3 + 4 поля 'Свой вариант')"
    print("[OK] Карточка интерактивная: 6 selectionInput, 5 textInput, 1 кнопка")

    # 2. Проверяем парсинг formInputs
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
    parsed = parse_onboarding_form(sample_form)
    assert len(parsed) == 7, f"Должно быть 7 ответов, получено {len(parsed)}"
    assert parsed[0]["choice"] == "it, travel"
    assert parsed[0]["text"] == "космос"
    assert parsed[2]["text"] == "нейросети"
    assert parsed[5]["choice"] == "anonymous"
    print("[OK] Парсинг formInputs работает — 7 ответов")

    # 3. Проверяем сохранение в БД (отдельная сессия, чтобы убедиться в персистентности)
    async with AsyncSessionLocal() as db:
        profile = await get_or_create_profile(
            db,
            workspace_user_id=test_user_id,
            email=test_email,
            display_name=test_name,
            chat_space_id=test_space,
        )
        answers = await save_onboarding_answers(db, profile, sample_form)
        assert len(answers) == 7, f"Должно быть 7 Answer-записей, получено {len(answers)}"
        print(f"[OK] Сохранено {len(answers)} ответов в answers")

    async with AsyncSessionLocal() as db:
        # Проверяем, что профиль обновился
        loaded_profile = (
            await db.execute(select(Profile).where(Profile.workspace_user_id == test_user_id))
        ).scalar_one()
        assert loaded_profile.onboarding_completed is True
        assert loaded_profile.interests == ["it", "travel", "космос"]
        assert loaded_profile.preferred_days == ["mon", "wed", "fri", "только вечером"]
        assert loaded_profile.public_consent is True
        assert loaded_profile.anonymize_answers is True
        assert loaded_profile.onboarding_answers is not None
        for q_text in QUESTIONS.values():
            assert q_text in loaded_profile.onboarding_answers, f"Не найден вопрос в onboarding_answers: {q_text}"
        print("[OK] Профиль обновлён: onboarding_completed, interests, preferred_days, consent")

        # Проверяем записи в answers
        loaded_answers = (
            await db.execute(
                select(Answer).where(Answer.profile_id == loaded_profile.id)
            )
        ).scalars().all()
        assert len(loaded_answers) == 7, f"В answers {len(loaded_answers)} записей вместо 7"
        questions = {a.question_text for a in loaded_answers}
        for q_text in QUESTIONS.values():
            assert q_text in questions, f"Не найден ответ на вопрос: {q_text}"
        print("[OK] Все 7 вопросов есть в таблице answers")

        # cleanup
        for answer in loaded_answers:
            await db.delete(answer)
        await db.delete(loaded_profile)
        await db.commit()
        print("[OK] Тестовые данные удалены")


if __name__ == "__main__":
    asyncio.run(main())
