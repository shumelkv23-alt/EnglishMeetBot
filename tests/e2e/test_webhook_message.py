"""E2E: MESSAGE — echo и запрос анкеты в DM против группы."""
import pytest

pytestmark = pytest.mark.e2e


def _message(user_id: str, text: str, space_type: str = "DM") -> dict:
    return {
        "type": "MESSAGE",
        "user": {"name": user_id, "displayName": "E2E", "email": "e2e@example.com"},
        "message": {"text": text},
        "space": {"name": "spaces/e2e_dm", "type": space_type},
    }


async def test_message_greeting_echo(client):
    resp = await client.post("/webhooks/google-chat", json=_message("users/e2e_msg", "привет"))
    assert resp.status_code == 200
    assert "Привет" in resp.json()["text"]


async def test_message_unknown_echo(client):
    resp = await client.post("/webhooks/google-chat", json=_message("users/e2e_msg2", "пока"))
    assert resp.status_code == 200
    assert "пока" in resp.json()["text"]


async def test_onboarding_command_in_dm_returns_card(client):
    resp = await client.post("/webhooks/google-chat", json=_message("users/e2e_msg3", "анкета", "DM"))
    assert resp.status_code == 200
    # в личке показываем саму карточку анкеты
    assert "cardsV2" in resp.json()


async def test_onboarding_command_in_group_returns_text(client):
    resp = await client.post("/webhooks/google-chat", json=_message("users/e2e_msg4", "анкета", "ROOM"))
    assert resp.status_code == 200
    # в группу карточку не шлём — просим написать в личку
    assert "Напиши мне в личку" in resp.json()["text"]
