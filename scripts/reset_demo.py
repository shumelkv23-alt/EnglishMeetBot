"""Сброс демо-режима в обычный: вернуть настройки и убрать демо-данные.

Откатывает то, что делает scripts/prep_demo.py:
- config fast_cycle=False, quorum_threshold=3, finish_voting_requested=False;
- удаляет демо-профили users/demo_* вместе с их голосами и ответами;
- помечает встречи текущего опроса как 'cancelled' (чтобы повторный прогон
  демо-цикла и обычный режим могли создать встречу заново; удаление самих
  встреч не делаем, чтобы не ловить FK по answers/attendance/ledger).

Запуск:
    venv/Scripts/python.exe -m scripts.reset_demo
"""
import asyncio

from sqlalchemy import delete, select, update

from app.database import AsyncSessionLocal
from app.models import MeetingInstance, PollResponse, PollVote, Profile
from app.services.weekly_poll import active_weekly_poll, get_or_create_config


async def main() -> None:
    async with AsyncSessionLocal() as db:
        # 1. Флаги — в обычный режим.
        for key, val in (
            ("fast_cycle", False),
            ("finish_voting_requested", False),
        ):
            cfg = await get_or_create_config(db, key, val)
            cfg.value = val
        qt = await get_or_create_config(db, "quorum_threshold", 3)
        qt.value = 3
        await db.commit()

        # 2. Демо-профили + их голоса/ответы.
        demo_ids = (
            await db.execute(
                select(Profile.id).where(Profile.workspace_user_id.like("users/demo_%"))
            )
        ).scalars().all()
        if demo_ids:
            await db.execute(delete(PollVote).where(PollVote.profile_id.in_(demo_ids)))
            await db.execute(delete(PollResponse).where(PollResponse.profile_id.in_(demo_ids)))
            await db.execute(delete(Profile).where(Profile.id.in_(demo_ids)))

        # 3. Встречи текущего опроса — в cancelled (не удаляем из-за FK).
        poll = await active_weekly_poll(db)
        if poll is not None:
            await db.execute(
                update(MeetingInstance)
                .where(MeetingInstance.poll_id == poll.id)
                .values(status="cancelled")
            )

        await db.commit()
        print("Демо сброшено: fast_cycle=False, quorum_threshold=3, демо-профили удалены, встречи отменены")


if __name__ == "__main__":
    asyncio.run(main())
