# tests/e2e/test_games_spy.py
"""E2E полного раунда Шпиона: старт → раздача → голосование → очки в БД."""
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


def _card_click(user_id: str, method: str, space: str, params: list | None = None) -> dict:
    action_params = [{"key": "method", "value": method}] + (params or [])
    return {
        "type": "CARD_CLICKED",
        "user": {"name": user_id, "displayName": "E2E"},
        "space": {"name": space},
        "action": {"function": "https://x/hook", "parameters": action_params},
        "common": {"formInputs": {}},
    }


def _resp_text(resp) -> str:
    return resp.json()["hostAppDataAction"]["chatDataAction"]["createMessageAction"]["message"].get("text", "")


async def test_spy_full_round(client, db):
    space = "spaces/e2e_spy"
    players = ["users/e2e_spy_a", "users/e2e_spy_b", "users/e2e_spy_c"]

    resp = await client.post("/webhooks/google-chat", json=_message(players[0], "/spy", space))
    assert "cardsV2" in resp.json()

    for p in players:
        await client.post("/webhooks/google-chat", json=_card_click(p, "join_game", space))

    resp = await client.post("/webhooks/google-chat", json=_card_click(players[0], "start_game", space))
    card = resp.json()["hostAppDataAction"]["chatDataAction"]["createMessageAction"]["message"]["cardsV2"][0]["card"]
    assert card["header"]["title"].startswith("Тема:")

    resp = await client.post("/webhooks/google-chat", json=_card_click(players[0], "spy_start_vote", space))
    buttons = resp.json()["hostAppDataAction"]["chatDataAction"]["createMessageAction"]["message"]["cardsV2"][0]["card"]["sections"][0]["widgets"][0]["buttonList"]["buttons"]
    assert len(buttons) == 3

    # все голосуют за первого игрока (кто шпион — рандомно, тест не зависит от этого)
    for p in players:
        resp = await client.post(
            "/webhooks/google-chat",
            json=_card_click(p, "spy_vote", space, params=[{"key": "target", "value": players[0]}]),
        )
    text = _resp_text(resp)  # последний голос завершает раунд
    assert "Шпионом был" in text and "Слово:" in text
    assert "Голосование:" in text  # раскладка голосов в финале

    rows = (
        await db.execute(
            select(LeaderboardLedger)
            .join(Profile, LeaderboardLedger.profile_id == Profile.id)
            .where(Profile.workspace_user_id.in_(players))
        )
    ).scalars().all()
    # либо шпион +3 (1 строка), либо двое мирных +1+1 (2 строки)
    assert len(rows) in (1, 2)
    assert all(r.event_type == "bonus" and r.reason == "spy" for r in rows)
    assert sum(r.points for r in rows) in (2, 3)
