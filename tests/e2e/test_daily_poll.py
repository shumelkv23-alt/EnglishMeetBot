"""E2E: ежедневный опрос — сабмит голоса через HTTP (классический CARD_CLICKED).

Кнопки карточки шлют time в action.parameters, поэтому имитируем именно
CARD_CLICKED с parameters=[{method:submit_daily_poll},{time:...}].
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import PollResponse, PollSlot, PollVote, Profile

pytestmark = pytest.mark.e2e


def _daily_poll_click(user_id: str, time_value: str, message_name: str | None = None) -> dict:
    event = {
        "type": "CARD_CLICKED",
        "user": {"name": user_id, "displayName": "E2E", "email": "e2e@example.com"},
        "space": {"name": "spaces/e2e_dm", "type": "DM"},
        "action": {
            "function": "https://example.com/hook",
            "parameters": [
                {"key": "method", "value": "submit_daily_poll"},
                {"key": "time", "value": time_value},
            ],
        },
        "common": {"formInputs": {}},
    }
    if message_name:
        event["message"] = {"name": message_name}
    return event


async def _submit(client, user_id: str, time_value: str):
    return await client.post("/webhooks/google-chat", json=_daily_poll_click(user_id, time_value))


def _reply_text(resp) -> str:
    return resp.json()["hostAppDataAction"]["chatDataAction"]["createMessageAction"]["message"]["text"]


async def _votes_for(db, user_id: str) -> tuple[Profile, list[PollVote]]:
    profile = (
        await db.execute(select(Profile).where(Profile.workspace_user_id == user_id))
    ).scalar_one()
    votes = (
        await db.execute(select(PollVote).where(PollVote.profile_id == profile.id))
    ).scalars().all()
    return profile, votes


async def _slot_time(db, vote: PollVote) -> str:
    slot = (await db.execute(select(PollSlot).where(PollSlot.id == vote.poll_slot_id))).scalar_one()
    return slot.slot_start.strftime("%H:%M")


async def test_submit_slot_records_vote(client, db, today_poll):
    resp = await _submit(client, "users/e2e_poll", "15:00")
    assert resp.status_code == 200
    assert "Спасибо, учёл" in _reply_text(resp)

    _, votes = await _votes_for(db, "users/e2e_poll")
    assert len(votes) == 1
    assert await _slot_time(db, votes[0]) == "15:00"


async def test_revote_keeps_single_vote(client, db, today_poll):
    await _submit(client, "users/e2e_revote", "15:00")
    await _submit(client, "users/e2e_revote", "16:00")

    _, votes = await _votes_for(db, "users/e2e_revote")
    assert len(votes) == 1  # одно время на человека
    assert await _slot_time(db, votes[0]) == "16:00"


async def test_not_available_records_no_vote(client, db, today_poll):
    resp = await _submit(client, "users/e2e_na", "not_available")
    assert resp.status_code == 200
    assert "Спасибо, учёл" in _reply_text(resp)

    profile, votes = await _votes_for(db, "users/e2e_na")
    assert len(votes) == 0
    response = (
        await db.execute(select(PollResponse).where(PollResponse.profile_id == profile.id))
    ).scalar_one()
    assert response.status == "not_available"


async def test_submit_after_deadline_is_closed(client, db, today_poll):
    # сдвигаем дедлайн в прошлое, чтобы сабмит вернул "closed"
    today_poll.voting_deadline = datetime.now(timezone.utc) - timedelta(minutes=5)
    await db.commit()

    resp = await _submit(client, "users/e2e_closed", "15:00")
    assert resp.status_code == 200
    assert "Голосование уже закрыто" in _reply_text(resp)


async def test_submit_updates_card_with_counts(client, db, today_poll):
    resp = await client.post(
        "/webhooks/google-chat",
        json=_daily_poll_click("users/e2e_upd", "15:00", "spaces/e2e_msg/messages/1"),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "updateMessageAction" in body["hostAppDataAction"]["chatDataAction"]
    msg = body["hostAppDataAction"]["chatDataAction"]["updateMessageAction"]["message"]
    assert msg["name"] == "spaces/e2e_msg/messages/1"
    sections = msg["cardsV2"][0]["card"]["sections"]
    counts_text = sections[0]["widgets"][0]["textParagraph"]["text"]
    assert "15:00 — 1" in counts_text
