"""E2E: ADDED_TO_SPACE — регистрация профиля при первом контакте.

Проверяем только DM: сценарий группы пишет config["space_id"] (перезапишет
реальный), поэтому его покрываем руками в docs/e2e-scenarios.md.
"""
import pytest
from sqlalchemy import select

from app.models import Profile

pytestmark = pytest.mark.e2e


def _added_to_space(user_id: str, space_type: str, space_name: str) -> dict:
    return {
        "type": "ADDED_TO_SPACE",
        "user": {"name": user_id, "displayName": "E2E", "email": "e2e@example.com"},
        "space": {"name": space_name, "type": space_type},
    }


async def test_added_to_space_dm_registers_profile(client, db):
    user_id = "users/e2e_added"
    resp = await client.post(
        "/webhooks/google-chat",
        json=_added_to_space(user_id, "DM", "spaces/e2e_dm"),
    )
    assert resp.status_code == 200

    profile = (
        await db.execute(select(Profile).where(Profile.workspace_user_id == user_id))
    ).scalar_one_or_none()
    assert profile is not None
    # DM-пространство фиксируется — оно нужно для проактивных DM-рассылок
    assert profile.chat_space_id == "spaces/e2e_dm"
