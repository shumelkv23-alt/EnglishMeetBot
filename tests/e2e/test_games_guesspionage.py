# tests/e2e/test_games_guesspionage.py
"""E2E полного раунда Guesspionage: старт → догадка → голос → очки в БД."""
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


def _card_click(user_id: str, method: str, space: str, params: list | None = None, form_inputs: dict | None = None) -> dict:
    action_params = [{"key": "method", "value": method}] + (params or [])
    return {
        "type": "CARD_CLICKED",
        "user": {"name": user_id, "displayName": "E2E"},
        "space": {"name": space},
        "action": {"function": "https://x/hook", "parameters": action_params},
        "common": {"formInputs": form_inputs or {}},
    }


def _resp_text(resp) -> str:
    return resp.json()["hostAppDataAction"]["chatDataAction"]["createMessageAction"]["message"].get("text", "")


async def test_guesspionage_full_round(client, db):
    space = "spaces/e2e_gp"
    guesser = "users/e2e_gp_guesser"
    voter = "users/e2e_gp_voter"

    # 1. старт
    resp = await client.post("/webhooks/google-chat", json=_message(guesser, "/guesspionage", space))
    assert "cardsV2" in resp.json()

    # 2. двое в деле
    await client.post("/webhooks/google-chat", json=_card_click(guesser, "join_game", space))
    await client.post("/webhooks/google-chat", json=_card_click(voter, "join_game", space))

    # 3. начать
    resp = await client.post("/webhooks/google-chat", json=_card_click(guesser, "start_game", space))
    assert "percentage" in _resp_text(resp)

    # 4. называющий шлёт 60 (в личке, параметр space = группа)
    guess_inputs = {"guess": {"stringInputs": {"value": ["60"]}}}
    resp = await client.post(
        "/webhooks/google-chat",
        json=_card_click(guesser, "submit_guesspionage_guess", space, params=[{"key": "space", "value": space}], form_inputs=guess_inputs),
    )
    assert "Принято" in _resp_text(resp)

    # 5. единственный не-называющий голосует «выше» → раунд завершается
    resp = await client.post(
        "/webhooks/google-chat",
        json=_card_click(voter, "guesspionage_higher_lower", space, params=[{"key": "choice", "value": "higher"}]),
    )
    assert "Правильный ответ: 70%" in _resp_text(resp)

    # 6. очки в БД: называющий +2 (|60-70|=10), голосовавший +1 (60 < 70, higher верно)
    rows = (
        await db.execute(
            select(LeaderboardLedger)
            .join(Profile, LeaderboardLedger.profile_id == Profile.id)
            .where(Profile.workspace_user_id.in_([guesser, voter]))
        )
    ).scalars().all()
    points_by_user = {r.profile_id: r.points for r in rows}
    assert sorted(points_by_user.values()) == [1, 2]
    assert all(r.event_type == "bonus" and r.reason == "guesspionage" for r in rows)
