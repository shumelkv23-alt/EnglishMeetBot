"""Память диалога для LLM: последние N сообщений на space (хранятся в БД).

Отдельная история на каждый space (DM и группа — разные ключи). При свободном
общении бот передаёт последние HISTORY_LIMIT сообщений в промпт как контекст.
"""
import logging

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChatMessage

logger = logging.getLogger(__name__)

# 5 сообщений бота + 5 сообщений человека.
HISTORY_LIMIT = 10
# Храним в БД чуть больше, чем отдаём, чтобы был запас при добавлении.
KEEP_PER_SPACE = 20


async def add_message(db: AsyncSession, space_id: str, role: str, text: str) -> None:
    """Добавить сообщение в историю space и обрезать старые."""
    if not text.strip():
        return
    db.add(ChatMessage(space_id=space_id, role=role, text=text))
    await db.flush()
    await _prune(db, space_id)


async def _prune(db: AsyncSession, space_id: str, keep: int = KEEP_PER_SPACE) -> None:
    """Удалить сообщения space сверх keep последних."""
    ids = (
        await db.execute(
            select(ChatMessage.id)
            .where(ChatMessage.space_id == space_id)
            .order_by(ChatMessage.id.desc())
            .offset(keep)
        )
    ).scalars().all()
    if ids:
        await db.execute(delete(ChatMessage).where(ChatMessage.id.in_(ids)))


async def get_history(db: AsyncSession, space_id: str, limit: int = HISTORY_LIMIT) -> list[tuple[str, str]]:
    """Последние limit сообщений space в хронологическом порядке: [(role, text), ...]."""
    rows = (
        await db.execute(
            select(ChatMessage)
            .where(ChatMessage.space_id == space_id)
            .order_by(ChatMessage.id.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [(m.role, m.text) for m in reversed(rows)]
