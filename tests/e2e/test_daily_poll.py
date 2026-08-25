"""E2E: недельный опрос — сабмит голоса (день+время) через HTTP (классический CARD_CLICKED).

Кнопки карточки шлют day и time в action.parameters, поэтому имитируем именно
CARD_CLICKED с parameters=[{method:submit_daily_poll},{day:...},{time:...}].
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import PollSlot, PollVote, Profile

pytestmark = pytest.mark.e2e


def _daily_poll_click(user_id: str, day: str, time_value: str, message_name: str | None = None) -> dict:
    event = {
        "type": "CARD_CLICKED",
        "user": {"name": user_id, "displayName": "E2E", "email": "e2e@example.com"},
        "space": {"name": "spaces/e2e_dm", "type": "DM"},
        "action": {
            "function": "https://example.com/hook",
            "parameters": [
                {"key": "method", "value": "submit_daily_poll"},
                {"key": "day", "value": day},
                {"key": "time", "value": time_value},
            ],
        },
        "common": {"formInputs": {}},
    }
    if message_name:
        event["message"] = {"name": message_name}
    return event


async def _submit(client, user_id: str, day: str, time_value: str):
    return await client.post("/webhooks/google-chat", json=_daily_poll_click(user_id, day, time_value))


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


async def _slot(db, vote: PollVote) -> PollSlot:
    return (await db.execute(select(PollSlot).where(PollSlot.id == vote.poll_slot_id))).scalar_one()


async def test_submit_slot_records_vote(client, db, today_poll):
    resp = await _submit(client, "users/e2e_poll", "0", "15:00")
    assert resp.status_code == 200
    assert "Thanks, noted" in _reply_text(resp)

    _, votes = await _votes_for(db, "users/e2e_poll")
    assert len(votes) == 1
    slot = await _slot(db, votes[0])
    assert slot.day_of_week == 0
    assert slot.slot_start.strftime("%H:%M") == "15:00"


async def test_revote_keeps_single_vote(client, db, today_poll):
    await _submit(client, "users/e2e_revote", "0", "15:00")
    await _submit(client, "users/e2e_revote", "1", "16:00")

    _, votes = await _votes_for(db, "users/e2e_revote")
    assert len(votes) == 1  # один слот на человека
    slot = await _slot(db, votes[0])
    assert slot.day_of_week == 1
    assert slot.slot_start.strftime("%H:%M") == "16:00"


async def test_submit_after_deadline_is_closed(client, db, today_poll):
    # сдвигаем дедлайн в прошлое, чтобы сабмит вернул "closed"
    today_poll.voting_deadline = datetime.now(timezone.utc) - timedelta(minutes=5)
    await db.commit()

    resp = await _submit(client, "users/e2e_closed", "0", "15:00")
    assert resp.status_code == 200
    assert "Voting is closed" in _reply_text(resp)


async def test_submit_updates_card_with_counts(client, db, today_poll):
    resp = await client.post(
        "/webhooks/google-chat",
        json=_daily_poll_click("users/e2e_upd", "0", "15:00", "spaces/e2e_msg/messages/1"),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "updateMessageAction" in body["hostAppDataAction"]["chatDataAction"]
    msg = body["hostAppDataAction"]["chatDataAction"]["updateMessageAction"]["message"]
    assert msg["name"] == "spaces/e2e_msg/messages/1"
    sections = msg["cardsV2"][0]["card"]["sections"]
    buttons = sections[0]["widgets"][0]["buttonList"]["buttons"]
    assert buttons[0]["text"] == "15:00 (1)"
