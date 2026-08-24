"""E2E еженедельного вопроса: сабмит и рассылка (прямые вызовы, БД).

Рассылка уходит всем активным профилям с DM, поэтому в этой БД могут быть
посторонние активные профили (реальные данные разработчика). Чтобы тест был
изолированным, смотрим только на отправки пользователям users/e2e_*.
"""
import pytest
from sqlalchemy import select

from app.models import Answer, Profile
from app.services.onboarding import get_or_create_profile
from app.services.weekly_questions import send_weekly_questions, submit_weekly_question

pytestmark = pytest.mark.e2e

FORM = {
    "q_llm": {"stringInputs": {"value": ["личный ответ"]}},
    "q_bank": {"stringInputs": {"value": ["общий ответ"]}},
}


def _e2e_sent(sent: list[str]) -> list[str]:
    """Отправки, адресованные e2e-профилям (остальные — посторонние данные БД)."""
    return [uid for uid in sent if uid.startswith("users/e2e_")]


async def test_submit_weekly_question_saves_two_answers(db):
    p = await get_or_create_profile(db, "users/e2e_wq_submit", chat_space_id="spaces/e2e_wq")
    result = await submit_weekly_question(db, p, FORM, "Личный?", "Общий?")
    assert result["ok"] is True
    answers = (await db.execute(select(Answer).where(Answer.profile_id == p.id))).scalars().all()
    texts = {(a.question_text, a.answer_text) for a in answers}
    assert ("Личный?", "личный ответ") in texts
    assert ("Общий?", "общий ответ") in texts


async def test_webhook_submit_weekly_question(client, db):
    event = {
        "commonEventObject": {
            "formInputs": FORM,
            "parameters": {
                "method": "submit_weekly_question",
                "q_llm_text": "Личный?",
                "q_bank_text": "Общий?",
            },
        },
        "chat": {
            "user": {"name": "users/e2e_wq_webhook", "displayName": "E2E", "email": "e2e@example.com"},
            "buttonClickedPayload": {"space": {"name": "spaces/e2e_wq", "type": "DM"}},
        },
    }
    resp = await client.post("/webhooks/google-chat", json=event)
    assert resp.status_code == 200
    body = resp.json()
    text = body["hostAppDataAction"]["chatDataAction"]["createMessageAction"]["message"]["text"]
    assert "Спасибо за ответ" in text
    answers = (
        await db.execute(
            select(Answer).join(Profile).where(Profile.workspace_user_id == "users/e2e_wq_webhook")
        )
    ).scalars().all()
    assert len(answers) == 2


async def test_submit_weekly_question_rejects_empty(db):
    p = await get_or_create_profile(db, "users/e2e_wq_empty", chat_space_id="spaces/e2e_wq")
    result = await submit_weekly_question(db, p, {}, "Личный?", "Общий?")
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
    await submit_weekly_question(db, p, FORM, "Вопрос", "Вопрос")
    await send_weekly_questions(db)
    assert _e2e_sent(sent) == []
