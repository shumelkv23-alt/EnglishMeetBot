# app/services/space_onboarding.py
"""Онбординг участников пространства: кому анкету в личку, кому @упоминание в группу.

Чистая функция plan_onboarding вынесена отдельно, чтобы юнит-тестами проверять
распределение по каналам без БД и сети.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Profile


def plan_onboarding(profiles_by_ws: dict[str, str | None], members: list[str]) -> dict:
    """Распределение участников по каналам онбординга.

    members — workspace_user_id участников группы ('users/...');
    profiles_by_ws — статус участника (workspace_user_id -> статус):
      "done"    — онбординг уже пройден, не трогаем;
      "dm"      — есть DM с ботом, анкету не заполнял → анкета в личку;
      "mention" — нет DM с ботом → @упоминание в группу;
      None      — профиля нет → @упоминание (попросить написать в личку).

    Возвращает {'dm': [...], 'mention': [...]}.
    """
    dm = [m for m in members if profiles_by_ws.get(m) == "dm"]
    mention = [m for m in members if profiles_by_ws.get(m) in ("mention", None)]
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
    by_ws: dict[str, str | None] = {}
    for p in profiles:
        if p.onboarding_completed:
            by_ws[p.workspace_user_id] = "done"
        elif p.chat_space_id:
            by_ws[p.workspace_user_id] = "dm"
        else:
            by_ws[p.workspace_user_id] = "mention"
    return plan_onboarding(by_ws, member_ids)


async def check_new_members(db: AsyncSession, space_name: str, force: bool = False) -> dict:
    """Найти участников и спланировать приглашение в онбординг.

    В отличие от onboard_space_members, помечает onboarding_invite_sent,
    чтобы повторный поллинг не тегал одних и тех же людей. Возвращает
    {'dm': [...], 'mention': [...]} для НОВЫХ участников.

    force=True — онбордить ВСЕХ участников (не только новых): пропускает
    проверку onboarding_completed/onboarding_invite_sent. Нужно демо-циклу.
    """
    from app.services.chat_sender import list_space_members
    from app.services.onboarding import get_or_create_profile

    memberships = list_space_members(space_name)
    member_ids = [
        m["member"]["name"]
        for m in memberships
        if m.get("member", {}).get("type") == "HUMAN"
        and "users/" in m["member"].get("name", "")
    ]

    dm, mention = [], []
    for ws in member_ids:
        profile = await get_or_create_profile(db, workspace_user_id=ws)
        if not force and (profile.onboarding_completed or profile.onboarding_invite_sent):
            continue
        if profile.chat_space_id:
            dm.append(ws)
        else:
            mention.append(ws)
        profile.onboarding_invite_sent = True
    await db.commit()
    return {"dm": dm, "mention": mention}
