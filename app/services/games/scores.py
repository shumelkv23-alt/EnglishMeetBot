# app/services/games/scores.py
"""Начисление очков в leaderboard_ledger (event_type='bonus')."""
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LeaderboardLedger


async def award_points(db: AsyncSession, profile_id: int, points: int, reason: str) -> None:
    """Записать начисление баллов. profile_id — int-ид профиля из БД, не workspace_user_id.

    meeting_instance_id=None: игры не привязаны к встрече, а UNIQUE-ограничение
    (profile_id, meeting_instance_id, event_type) с NULL не блокирует повторы.
    """
    db.add(
        LeaderboardLedger(
            profile_id=profile_id,
            meeting_instance_id=None,
            event_type="bonus",
            points=points,
            reason=reason,
            event_date=datetime.now(timezone.utc),
        )
    )
    await db.commit()
