# tests/e2e/test_vocab_e2e.py
"""E2E: карточка + персональная лексика в личку, идемпотентность send_card."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.cards.seed import ensure_seeded
from app.cards.service import send_card
from app.models import MeetingInstance, PollSlot, PollVote
from app.services.onboarding import get_or_create_profile
from app.services.weekly_poll import submit_poll

pytestmark = pytest.mark.e2e

TODAY_DOW = datetime.now().weekday()
FORM_1500 = {"day": {"stringInputs": {"value": [str(TODAY_DOW)]}}, "time": {"stringInputs": {"value": ["15:00"]}}}


async def test_send_card_is_idempotent_and_sends_vocab(db, today_poll, monkeypatch):
    sent: list[tuple[str, str]] = []
    capture = lambda space, text="", cards_v2=None, cards=None: sent.append((space, text))
    # send_message связан в потребителях при импорте — патчим оба имени.
    monkeypatch.setattr("app.cards.service.send_message", capture)
    monkeypatch.setattr("app.services.vocab.send_message", capture)

    async def fake_config(session, key, default=None):
        return "spaces/group" if key == "space_id" else default

    monkeypatch.setattr("app.cards.service._config_value", fake_config)
    # Не ходим в сеть: карточка — по шаблону, лексика — из фиксированного списка.
    async def no_llm(*args, **kwargs):
        return None

    monkeypatch.setattr("app.cards.service.generate_llm_content", no_llm)

    async def fake_vocab(level, topic):
        return [{"phrase": "Hi", "example": "Hi there"}]

    monkeypatch.setattr("app.services.vocab.generate_vocab", fake_vocab)

    p = await get_or_create_profile(db, "users/e2e_vocab", email="v@x.com", chat_space_id="spaces/dm-v")
    p.english_level = "B1"
    await submit_poll(db, p, FORM_1500)

    voted_slot = (
        await db.execute(
            select(PollSlot)
            .join(PollVote, PollVote.poll_slot_id == PollSlot.id)
            .where(PollVote.profile_id == p.id)
        )
    ).scalar_one()

    meeting = MeetingInstance(
        poll_id=today_poll.id,
        selected_slot_id=voted_slot.id,
        scheduled_start=datetime.now(timezone.utc) + timedelta(hours=2),
        scheduled_end=datetime.now(timezone.utc) + timedelta(hours=3),
        location="Online (Meet)",
        status="scheduled",
    )
    db.add(meeting)
    await db.flush()
    await db.refresh(meeting)
    await db.commit()

    await ensure_seeded()

    # Первый вызов: карточка в группу + лексика в личку.
    await send_card(str(meeting.id))
    group = [s for s in sent if s[0] == "spaces/group"]
    dm = [s for s in sent if s[0] == "users/e2e_vocab"]
    assert len(group) == 1
    assert len(dm) == 1

    # Второй вызов: guard по Card.meeting_id — ничего не шлём.
    sent.clear()
    await send_card(str(meeting.id))
    assert sent == []
