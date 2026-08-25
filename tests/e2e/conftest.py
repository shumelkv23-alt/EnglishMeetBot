"""Фикстуры e2e-тестов: HTTP-клиент к поднятому uvicorn + сессия БД.

Прогон (нужен поднятый бот и Postgres):

    $env:SKIP_JWT_VALIDATION="true"; uvicorn app.main:app --port 8000
    pytest -m e2e

Тесты изолированы префиксом user_id "users/e2e_": фикстура `db` в teardown
удаляет профили с этим префиксом и всё связанное. Ежедневный опрос
(`today_poll`) сбрасывает/пересоздаёт опрос дня и чистит за собой.
Live-тесты (маркер live) БД не трогают и работают без поднятого Postgres.
"""
import os
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import delete, select

from app.database import AsyncSessionLocal
from app.models import (
    Answer,
    Attendance,
    DailyPoll,
    LeaderboardLedger,
    MeetingInstance,
    PollQuestion,
    PollResponse,
    PollSlot,
    PollVote,
    Profile,
)
from app.services.weekly_poll import slot_datetime, week_monday

BASE_URL = os.getenv("E2E_BASE_URL", "http://localhost:8000")
E2E_PREFIX = "users/e2e_"


async def _delete_e2e(db) -> None:
    """Удалить профили users/e2e_* и всё, что на них ссылается."""
    ids = (
        await db.execute(
            select(Profile.id).where(Profile.workspace_user_id.like(f"{E2E_PREFIX}%"))
        )
    ).scalars().all()
    if not ids:
        await db.rollback()
        return
    for model in (Answer, PollVote, PollResponse, Attendance, PollQuestion, LeaderboardLedger):
        await db.execute(delete(model).where(model.profile_id.in_(ids)))
    await db.execute(delete(Profile).where(Profile.id.in_(ids)))
    await db.commit()


async def _delete_polls(db, poll_ids: list[int]) -> None:
    """Каскадно удалить опросы и всё, что на них ссылается (от детей к родителю)."""
    if not poll_ids:
        return
    meeting_ids = select(MeetingInstance.id).where(MeetingInstance.poll_id.in_(poll_ids))
    await db.execute(delete(Attendance).where(Attendance.meeting_instance_id.in_(meeting_ids)))
    await db.execute(delete(LeaderboardLedger).where(LeaderboardLedger.meeting_instance_id.in_(meeting_ids)))
    await db.execute(
        delete(PollVote).where(
            PollVote.poll_response_id.in_(
                select(PollResponse.id).where(PollResponse.poll_id.in_(poll_ids))
            )
        )
    )
    await db.execute(delete(MeetingInstance).where(MeetingInstance.poll_id.in_(poll_ids)))
    await db.execute(delete(PollResponse).where(PollResponse.poll_id.in_(poll_ids)))
    await db.execute(delete(PollSlot).where(PollSlot.poll_id.in_(poll_ids)))
    await db.execute(delete(PollQuestion).where(PollQuestion.poll_id.in_(poll_ids)))
    await db.execute(delete(DailyPoll).where(DailyPoll.id.in_(poll_ids)))


@pytest.fixture
def base_url() -> str:
    """Базовый URL поднятого uvicorn (переопределяется через E2E_BASE_URL)."""
    return BASE_URL


@pytest.fixture
async def client() -> httpx.AsyncClient:
    """Async HTTP-клиент к боту."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15.0) as c:
        yield c


@pytest.fixture
async def db():
    """Сессия БД (та же Postgres, что и у поднятого бота) + очистка e2e-данных."""
    async with AsyncSessionLocal() as session:
        yield session
        await _delete_e2e(session)


@pytest.fixture
async def today_poll(db):
    """Сбросить и пересоздать недельный опрос: активный DailyPoll на понедельник + 7 дней × 3 слота.

    Дедлайн ставим на +2 часа в будущее, чтобы submit_poll не вернул "closed".
    В teardown удаляем созданный опрос и всё, что с ним связано.
    """
    today = datetime.now(timezone.utc).date()
    monday = week_monday(today)

    # Сбрасываем существующий опрос недели (любого статуса).
    old_ids = (
        await db.execute(select(DailyPoll.id).where(DailyPoll.poll_date == monday))
    ).scalars().all()
    if old_ids:
        await _delete_polls(db, old_ids)
        await db.commit()

    poll = DailyPoll(
        poll_date=monday,
        voting_deadline=datetime.now(timezone.utc) + timedelta(hours=2),
        status="active",
    )
    db.add(poll)
    await db.flush()
    for dow in range(7):
        for t in ("15:00", "16:00", "17:00"):
            start = slot_datetime(t)
            db.add(
                PollSlot(
                    poll_id=poll.id,
                    day_of_week=dow,
                    slot_start=start,
                    slot_end=start + timedelta(minutes=60),
                    location="Онлайн (Meet)",
                )
            )
    await db.commit()
    await db.refresh(poll)

    yield poll

    await _delete_polls(db, [poll.id])
    await db.commit()
