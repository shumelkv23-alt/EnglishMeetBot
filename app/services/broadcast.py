# app/services/broadcast.py
"""Рассылка сообщений: всем, у кого есть DM с ботом (из profiles),
или всем участникам конкретного space при наличии DM в profiles.
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Profile
from app.services.chat_sender import send_text

logger = logging.getLogger(__name__)


async def ensure_profile_dm(db: AsyncSession, profile: Profile) -> bool:
    """Заполнить chat_space_id профиля через API, если его ещё нет.

    True — DM известен (был или найден).
    """
    if profile.chat_space_id:
        return True
    from app.services.chat_sender import find_user_dm_space

    space = find_user_dm_space(profile.workspace_user_id or "")
    if space:
        profile.chat_space_id = space
        await db.commit()
        return True
    return False


def send_to_profile(profile: Profile, text: str) -> bool:
    """Отправить текст в DM профиля. True — ушло, False — DM нет/ошибка."""
    if not profile.chat_space_id:
        return False
    try:
        send_text(profile.chat_space_id, text)
        return True
    except Exception:
        logger.exception("send_to_profile_failed profile_id=%s", profile.id)
        return False


async def broadcast_to_writers(db: AsyncSession, text: str) -> dict:
    """Рассылка всем, кто писал боту (profiles с известным DM с ботом).

    DM без chat_space_id пытаемся найти через API.
    """
    profiles = (await db.execute(select(Profile))).scalars().all()
    sent, skipped = 0, 0
    for profile in profiles:
        if not await ensure_profile_dm(db, profile):
            skipped += 1
            continue
        if send_to_profile(profile, text):
            sent += 1
        else:
            skipped += 1
    logger.info("broadcast_writers done sent=%s skipped=%s", sent, skipped)
    return {"sent": sent, "skipped": skipped}


async def broadcast_to_space_members(
    db: AsyncSession, space_name: str, text: str
) -> dict:
    """Рассылка участникам space: шлём в DM только тем, у кого он есть в profiles.

    Остальных (без DM с ботом) пропускаем с пометкой skipped.
    """
    from app.services.chat_sender import list_space_members

    memberships = list_space_members(space_name)
    user_ids = [
        m["member"]["name"]
        for m in memberships
        if m.get("member", {}).get("type") == "HUMAN" and "users/" in m["member"].get("name", "")
    ]
    profiles = (
        await db.execute(
            select(Profile).where(Profile.workspace_user_id.in_(user_ids))
        )
    ).scalars().all()
    by_ws = {p.workspace_user_id: p for p in profiles}

    sent, skipped, missing = 0, 0, 0
    for uid in user_ids:
        profile = by_ws.get(uid)
        if profile is None:
            missing += 1
            continue
        if not await ensure_profile_dm(db, profile):
            missing += 1
            continue
        if send_to_profile(profile, text):
            sent += 1
        else:
            skipped += 1
    logger.info(
        "broadcast_space done space=%s members=%s sent=%s skipped=%s missing_dm=%s",
        space_name, len(user_ids), sent, skipped, missing,
    )
    return {"members": len(user_ids), "sent": sent, "skipped": skipped, "missing_dm": missing}