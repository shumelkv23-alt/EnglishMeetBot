"""E2E: сабмит анкеты онбординга через buttonClickedPayload (add-on формат)."""
import pytest
from sqlalchemy import select

from app.models import Answer, Profile
from app.services.onboarding_answers import QUESTIONS

pytestmark = pytest.mark.e2e

FORM_INPUTS = {
    "q1": {"stringInputs": {"value": ["it"]}},
    "q2": {"stringInputs": {"value": ["chill"]}},
    "q3": {"stringInputs": {"value": ["нейросети"]}},
    "q4": {"stringInputs": {"value": ["mon"]}},
    "q5": {"stringInputs": {"value": ["busy"]}},
    "q6": {"stringInputs": {"value": ["yes"]}},
    "q7": {"stringInputs": {"value": ["soft"]}},
    "q8": {"stringInputs": {"value": ["B1"]}},
}


def _button_click(user_id: str, form_inputs: dict) -> dict:
    return {
        "commonEventObject": {
            "formInputs": form_inputs,
            "parameters": {"method": "submit_onboarding"},
        },
        "chat": {
            "user": {"name": user_id, "displayName": "E2E", "email": "e2e@example.com"},
            "buttonClickedPayload": {
                "space": {"name": "spaces/e2e_dm", "type": "DM"},
            },
        },
    }


async def _profile_and_answer_count(db, user_id: str) -> tuple[Profile | None, int]:
    profile = (
        await db.execute(select(Profile).where(Profile.workspace_user_id == user_id))
    ).scalar_one_or_none()
    if profile is None:
        return None, 0
    count = (
        await db.execute(select(Answer).where(Answer.profile_id == profile.id))
    ).scalars().all()
    return profile, len(count)


async def test_onboarding_submit_saves_8_answers(client, db):
    user_id = "users/e2e_onb"
    resp = await client.post("/webhooks/google-chat", json=_button_click(user_id, FORM_INPUTS))
    assert resp.status_code == 200
    body = resp.json()
    assert "hostAppDataAction" in body
    text = body["hostAppDataAction"]["chatDataAction"]["createMessageAction"]["message"]["text"]
    assert "Thanks, your form is saved!" in text

    profile, count = await _profile_and_answer_count(db, user_id)
    assert profile is not None
    assert profile.onboarding_completed is True
    assert profile.english_level == "B1"
    assert count == 8
    # все 8 вопросов анкеты на месте
    questions = {
        a.question_text
        for a in (await db.execute(select(Answer).where(Answer.profile_id == profile.id))).scalars().all()
    }
    assert questions == set(QUESTIONS.values())


async def test_onboarding_repeat_appends_history(client, db):
    user_id = "users/e2e_onb_repeat"
    for _ in range(2):
        resp = await client.post("/webhooks/google-chat", json=_button_click(user_id, FORM_INPUTS))
        assert resp.status_code == 200
    _, count = await _profile_and_answer_count(db, user_id)
    # история ответов растёт (8 -> 16), а не перезаписывается
    assert count == 16
