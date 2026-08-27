"""Лидерборд: начисление и агрегация баллов (leaderboard_ledger).

Идемпотентность начислений гарантирует UNIQUE(profile_id, meeting_instance_id,
event_type): повторное начисление за ту же встречу не создаёт дубль (REQ-9.7).
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Config, LeaderboardLedger, Profile

logger = logging.getLogger(__name__)


async def award_points(
    db: AsyncSession,
    profile_id: int,
    event_type: str,
    points: int,
    meeting_instance_id: int | None = None,
    reason: str | None = None,
    metadata: dict | None = None,
) -> bool:
    """Идемпотентно начислить баллы. Возвращает True, если запись добавлена (не дубль)."""
    if points == 0:
        return False
    values = dict(
        profile_id=profile_id,
        meeting_instance_id=meeting_instance_id,
        event_type=event_type,
        points=points,
        reason=reason,
        event_metadata=metadata or {},
        event_date=datetime.now(timezone.utc),
    )
    if meeting_instance_id is None:
        # NULL ≠ NULL в UNIQUE — идемпотентность держит частичный индекс
        # (profile_id, event_type) WHERE meeting_instance_id IS NULL.
        conflict = dict(
            index_elements=["profile_id", "event_type"],
            index_where=text("meeting_instance_id IS NULL"),
        )
    else:
        conflict = dict(
            index_elements=["profile_id", "meeting_instance_id", "event_type"]
        )
    stmt = pg_insert(LeaderboardLedger).values(**values).on_conflict_do_nothing(**conflict)
    result = await db.execute(stmt)
    return bool(result.rowcount)


async def award_attendance(db: AsyncSession, profile_id: int, meeting_instance_id: int) -> int:
    """Начислить баллы за подтверждённое посещение (config['points_attendance']).

    Возвращает начисленное количество (0, если запись уже была — дубль).
    """
    cfg = (
        await db.execute(select(Config).where(Config.key == "points_attendance"))
    ).scalar_one_or_none()
    points = int(cfg.value or 3) if cfg is not None else 3
    awarded = await award_points(
        db,
        profile_id,
        "attendance",
        points,
        meeting_instance_id=meeting_instance_id,
        reason="Meeting attendance",
    )
    if awarded:
        logger.info("points_awarded profile=%s meeting=%s points=%s", profile_id, meeting_instance_id, points)
    return points if awarded else 0


async def get_leaderboard(db: AsyncSession, top_n: int = 10) -> list[dict]:
    """Топ-N участников по сумме баллов: [{'name': str, 'points': int}, ...]."""
    rows = await db.execute(
        select(
            Profile.user_name,
            func.sum(LeaderboardLedger.points).label("total"),
        )
        .join(LeaderboardLedger, LeaderboardLedger.profile_id == Profile.id)
        .where(~Profile.user_email.like("%@test.local"))
        .group_by(Profile.id, Profile.user_name)
        .order_by(func.sum(LeaderboardLedger.points).desc(), Profile.user_name.asc())
        .limit(top_n)
    )
    return [{"name": name, "points": int(total)} for name, total in rows.all()]
