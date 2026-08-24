# tests/e2e/test_games_framework.py
"""E2E каркаса игр: слеш-команда, регистрация, начисление очков."""
import pytest
from sqlalchemy import select

from app.models import LeaderboardLedger, Profile

pytestmark = pytest.mark.e2e


def _message(user_id: str, text: str, space: str) -> dict:
    return {
        "type": "MESSAGE",
        "user": {"name": user_id, "displayName": "E2E"},
        "message": {"text": text},
        "space": {"name": space, "type": "ROOM"},
    }


def _card_click(user_id: str, method: str, space: str) -> dict:
    return {
        "type": "CARD_CLICKED",
        "user": {"name": user_id, "displayName": "E2E"},
        "space": {"name": space},
        "action": {"function": "https://x/hook", "parameters": [{"key": "method", "value": method}]},
        "common": {"formInputs": {}},
    }


async def test_slash_command_creates_lobby(client):
    resp = await client.post("/webhooks/google-chat", json=_message("users/e2e_g1", "/guesspionage", "spaces/e2e_g1"))
    assert resp.status_code == 200
    assert "cardsV2" in resp.json()


async def test_join_and_start_flow(client):
    space = "spaces/e2e_g2"
    await client.post("/webhooks/google-chat", json=_message("users/e2e_g2", "/spy", space))
    await client.post("/webhooks/google-chat", json=_card_click("users/e2e_g2a", "join_game", space))
    await client.post("/webhooks/google-chat", json=_card_click("users/e2e_g2b", "join_game", space))
    # всего 2 игрока — для шпиона нужно 3, старт не должен пройти
    resp = await client.post("/webhooks/google-chat", json=_card_click("users/e2e_g2", "start_game", space))
    assert "минимум 3" in resp.json()["hostAppDataAction"]["chatDataAction"]["createMessageAction"]["message"]["text"]


async def test_award_points_writes_ledger(db):
    from app.services.games.scores import award_points

    profile = Profile(workspace_user_id="users/e2e_award", user_email="e2e_award@example.com")
    db.add(profile)
    await db.commit()
    await db.refresh(profile)

    await award_points(db, profile.id, 3, "guesspionage")

    rows = (await db.execute(select(LeaderboardLedger).where(LeaderboardLedger.profile_id == profile.id))).scalars().all()
    assert len(rows) == 1
    assert rows[0].points == 3
    assert rows[0].event_type == "bonus"
    assert rows[0].reason == "guesspionage"
    assert rows[0].meeting_instance_id is None
