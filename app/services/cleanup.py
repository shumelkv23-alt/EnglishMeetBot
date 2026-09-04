# app/services/cleanup.py
"""Периодическая очистка данных, которые больше не нужны.

Джоб запускается раз в сутки в непиковое время (по умолчанию 04:00). Удаляет только
то, что уже точно никому не нужно:

- Старые опросы: голоса и ответы опросов старше POLL_RETENTION_DAYS. Сами опросы и
  слоты оставляем — они крошечные (1 опрос + 21 слот в неделю), и на них ссылаются
  meeting_instances (встречи — это история, её не трогаем).
- Внутренности сыгранных игр старше GAME_RETENTION_DAYS: слово-логи, раунды, команды,
  участники, партии Alias/Snake Oil и завершённые/отменённые игровые сессии.

Живое состояние (активные игры, профили, встречи, leaderboard_ledger) НЕ трогаем.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    DailyPoll,
    Game,
    GamePlayer,
    GameRound,
    GameSession,
    GameTeam,
    GameWordEvent,
    PollResponse,
    PollSlot,
    PollVote,
    SnakeGame,
    SnakeOffer,
    SnakePlayer,
    SnakeRound,
)

logger = logging.getLogger(__name__)

POLL_RETENTION_DAYS = 28
GAME_RETENTION_DAYS = 30


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


async def cleanup_old_polls(db: AsyncSession) -> int:
    """Удалить голоса и ответы опросов старше POLL_RETENTION_DAYS.

    Возвращает число удалённых строк.
    """
    cutoff_date = (_now_utc() - timedelta(days=POLL_RETENTION_DAYS)).date()
    old_poll_ids = select(DailyPoll.id).where(DailyPoll.poll_date < cutoff_date)

    votes = await db.execute(
        delete(PollVote).where(
            PollVote.poll_slot_id.in_(
                select(PollSlot.id).where(PollSlot.poll_id.in_(old_poll_ids))
            )
        )
    )
    responses = await db.execute(
        delete(PollResponse).where(PollResponse.poll_id.in_(old_poll_ids))
    )

    deleted = (votes.rowcount or 0) + (responses.rowcount or 0)
    if deleted:
        logger.info(
            "cleanup_old_polls deleted=%s (votes=%s responses=%s)",
            deleted, votes.rowcount, responses.rowcount,
        )
    return deleted


async def cleanup_old_games(db: AsyncSession) -> int:
    """Удалить внутренности завершённых игр старше GAME_RETENTION_DAYS.

    Возвращает число удалённых строк.
    """
    cutoff = _now_utc() - timedelta(days=GAME_RETENTION_DAYS)
    deleted = 0

    # --- Alias (таблицы games / game_*) ---
    game_ids = (
        await db.execute(
            select(Game.id).where(Game.status == "finished", Game.created_at < cutoff)
        )
    ).scalars().all()
    if game_ids:
        round_ids = (
            await db.execute(select(GameRound.id).where(GameRound.game_id.in_(game_ids)))
        ).scalars().all()
        if round_ids:
            deleted += (
                await db.execute(
                    delete(GameWordEvent).where(GameWordEvent.round_id.in_(round_ids))
                )
            ).rowcount or 0
        deleted += (
            await db.execute(delete(GameRound).where(GameRound.game_id.in_(game_ids)))
        ).rowcount or 0
        deleted += (
            await db.execute(delete(GamePlayer).where(GamePlayer.game_id.in_(game_ids)))
        ).rowcount or 0
        deleted += (
            await db.execute(delete(GameTeam).where(GameTeam.game_id.in_(game_ids)))
        ).rowcount or 0
        deleted += (
            await db.execute(delete(Game).where(Game.id.in_(game_ids)))
        ).rowcount or 0

    # --- Snake Oil (snake_*) ---
    snake_ids = (
        await db.execute(
            select(SnakeGame.id).where(
                SnakeGame.status == "finished", SnakeGame.created_at < cutoff
            )
        )
    ).scalars().all()
    if snake_ids:
        snake_round_ids = (
            await db.execute(
                select(SnakeRound.id).where(SnakeRound.game_id.in_(snake_ids))
            )
        ).scalars().all()
        if snake_round_ids:
            deleted += (
                await db.execute(
                    delete(SnakeOffer).where(SnakeOffer.round_id.in_(snake_round_ids))
                )
            ).rowcount or 0
        deleted += (
            await db.execute(delete(SnakeRound).where(SnakeRound.game_id.in_(snake_ids)))
        ).rowcount or 0
        deleted += (
            await db.execute(delete(SnakePlayer).where(SnakePlayer.game_id.in_(snake_ids)))
        ).rowcount or 0
        deleted += (
            await db.execute(delete(SnakeGame).where(SnakeGame.id.in_(snake_ids)))
        ).rowcount or 0

    # --- Игровые сессии (Кто я? / Quiplash / crossword и т.д.) — только завершённые ---
    deleted += (
        await db.execute(
            delete(GameSession).where(
                GameSession.status.in_(["finished", "cancelled"]),
                GameSession.created_at < cutoff,
            )
        )
    ).rowcount or 0

    if deleted:
        logger.info("cleanup_old_games deleted=%s", deleted)
    return deleted


async def run_cleanup(db: AsyncSession) -> dict:
    """Полный проход очистки за раз. Возвращает сводку по категориям."""
    return {
        "polls": await cleanup_old_polls(db),
        "games": await cleanup_old_games(db),
    }
