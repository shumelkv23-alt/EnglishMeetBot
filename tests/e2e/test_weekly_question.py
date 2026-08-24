"""E2E еженедельного вопроса: сабмит и рассылка (прямые вызовы, БД).

Рассылка уходит всем активным профилям с DM, поэтому в этой БД могут быть
посторонние активные профили (реальные данные разработчика). Чтобы тест был
изолированным, смотрим только на отправки пользователям users/e2e_*.
"""
import pytest
from sqlalchemy import select

from app.models import Answer
from app.services.onboarding import get_or_create_profile
from app.services.weekly_questions import send_weekly_questions, submit_weekly_question

pytestmark = pytest.mark.e2e

FORM = {"answer": {"stringInputs": {"value": ["мой ответ"]}}}


def _e2e_sent(sent: list[str]) -> list[str]:
    """Отправки, адресованные e2e-профилям (остальные — посторонние данные БД)."""
    return [uid for uid in sent if uid.startswith("users/e2e_")]


async def test_submit_weekly_question_saves_answer(db):
    p = await get_or_create_profile(db, "users/e2e_wq_submit", chat_space_id="spaces/e2e_wq")
    result = await submit_weekly_question(db, p, FORM, "Любимый фильм?")
    assert result["ok"] is True
    a = (await db.execute(select(Answer).where(Answer.profile_id == p.id))).scalar_one()
    assert a.question_text == "Любимый фильм?"
    assert a.answer_text == "мой ответ"


async def test_submit_weekly_question_rejects_empty(db):
    p = await get_or_create_profile(db, "users/e2e_wq_empty", chat_space_id="spaces/e2e_wq")
    result = await submit_weekly_question(db, p, {}, "Любимый фильм?")
    assert result["ok"] is False


async def test_send_weekly_questions_skips_answered(db, monkeypatch):
    sent = []
    monkeypatch.setattr("app.services.weekly_questions.send_message", lambda uid, payload: sent.append(uid))
    monkeypatch.setattr(
        "app.services.weekly_questions.generate_personal_question",
        lambda interests: "Вопрос",
    )
    # активный профиль с DM
    await get_or_create_profile(db, "users/e2e_wq_send", chat_space_id="spaces/e2e_wq")
    # неактивный — не должен попасть в рассылку
    inactive = await get_or_create_profile(db, "users/e2e_wq_inactive", chat_space_id="spaces/e2e_wq")
    inactive.is_active = False
    await db.commit()

    await send_weekly_questions(db)
    e2e_sent = _e2e_sent(sent)
    assert e2e_sent == ["users/e2e_wq_send"]
    assert "users/e2e_wq_inactive" not in e2e_sent


async def test_send_weekly_questions_skips_after_answer(db, monkeypatch):
    sent = []
    monkeypatch.setattr("app.services.weekly_questions.send_message", lambda uid, payload: sent.append(uid))
    monkeypatch.setattr(
        "app.services.weekly_questions.generate_personal_question",
        lambda interests: "Вопрос",
    )
    p = await get_or_create_profile(db, "users/e2e_wq_answered", chat_space_id="spaces/e2e_wq")
    await submit_weekly_question(db, p, FORM, "Вопрос")
    await send_weekly_questions(db)
    assert _e2e_sent(sent) == []

