# app/services/space_onboarding.py
"""Онбординг участников пространства: кому анкету в личку, кому @упоминание в группу.

Чистая функция plan_onboarding вынесена отдельно, чтобы юнит-тестами проверять
распределение по каналам без БД и сети.
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Profile

logger = logging.getLogger(__name__)


def plan_onboarding(profiles_by_ws: dict[str, bool], members: list[str]) -> dict:
    """Распределение участников по каналам онбординга.

    members — workspace_user_id участников группы ('users/...');
    profiles_by_ws — True, если у участника уже есть DM с ботом (chat_space_id)
    и онбординг ещё не пройден.

    Возвращает {'dm': [...], 'mention': [...]}.
    """
    dm = [m for m in members if profiles_by_ws.get(m)]
    mention = [m for m in members if not profiles_by_ws.get(m)]
    return {"dm": dm, "mention": mention}


async def onboard_space_members(db: AsyncSession, space_name: str) -> dict:
    """Спланировать онбординг участников пространства.

    Через list_space_members получает HUMAN-участников (member.name),
    находит их профили в БД и строит план plan_onboarding(...).

    Возвращает {'dm': [...], 'mention': [...]} — списки workspace_user_id.
    """
    from app.services.chat_sender import list_space_members

    memberships = list_space_members(space_name)
    member_ids = [
        m["member"]["name"]
        for m in memberships
        if m.get("member", {}).get("type") == "HUMAN"
        and "users/" in m["member"].get("name", "")
    ]
    profiles = (
        await db.execute(select(Profile).where(Profile.workspace_user_id.in_(member_ids)))
    ).scalars().all()
    by_ws = {
        p.workspace_user_id: bool(p.chat_space_id and not p.onboarding_completed)
        for p in profiles
    }
    return plan_onboarding(by_ws, member_ids)


async def mention_new_members(
    db: AsyncSession, space_name: str, member_ids: list[str] | None = None
) -> int:
    """Упомянуть в группе участников без DM с ботом, кроме уже упомянутых.

    member_ids — workspace_user_id кандидатов на упоминание. Если None,
    список берётся из onboard_space_members (участники без chat_space_id).
    Уже упомянутые хранятся в config["mentioned_members"] (JSON-список),
    чтобы не спамить одним и тем же при каждой сверке.

    Возвращает число новых упоминаний.
    """
    from app.services.chat_sender import send_text
    from app.services.weekly_poll import get_or_create_config

    if member_ids is None:
        plan = await onboard_space_members(db, space_name)
        member_ids = plan["mention"]
    if not member_ids:
        return 0

    cfg = await get_or_create_config(db, "mentioned_members", [])
    mentioned = list(cfg.value) if isinstance(cfg.value, list) else []
    new = [m for m in member_ids if m not in mentioned]
    if not new:
        return 0

    mentions = " ".join(f"<{m}>" for m in new)
    send_text(space_name, f"{mentions} — DM me to fill out the form 👋")

    mentioned.extend(new)
    cfg.value = mentioned
    await db.commit()
    logger.info("members_mentioned space=%s new=%d", space_name, len(new))
    return len(new)
