# tests/test_onboarding_units.py
import asyncio
from unittest.mock import patch

from app.models import Profile
from app.services.space_onboarding import onboard_space_members, plan_onboarding


def test_plan_onboarding_split():
    members = ["users/a", "users/b", "users/c", "users/d"]
    profiles = {"users/a": "dm", "users/b": "mention", "users/c": "done"}
    r = plan_onboarding(profiles, members)
    assert r["dm"] == ["users/a"]
    assert r["mention"] == ["users/b", "users/d"]  # "done" пропущен, без профиля — mention


def test_plan_onboarding_skips_done():
    profiles = {"users/a": "done", "users/b": "dm"}
    r = plan_onboarding(profiles, ["users/a", "users/b"])
    assert r["dm"] == ["users/b"]
    assert r["mention"] == []


def test_plan_onboarding_all_mention_without_profiles():
    # Нет профилей — нет DM с ботом: все уходят в @упоминание
    r = plan_onboarding({}, ["users/a", "users/b"])
    assert r["dm"] == []
    assert r["mention"] == ["users/a", "users/b"]


class _FakeScalars:
    def __init__(self, profiles):
        self._profiles = profiles

    def all(self):
        return self._profiles


class _FakeResult:
    def __init__(self, profiles):
        self._profiles = profiles

    def scalars(self):
        return _FakeScalars(self._profiles)


class _FakeDB:
    def __init__(self, profiles):
        self._profiles = profiles

    async def execute(self, *args, **kwargs):
        return _FakeResult(self._profiles)


def _memberships(*user_ids):
    return [{"member": {"name": uid, "type": "HUMAN"}} for uid in user_ids]


def test_onboard_space_members_classifies_dm_vs_mention():
    # Профиль с DM и без онбординга → dm; без DM → mention; онборднут → done (пропуск).
    profiles = [
        Profile(
            workspace_user_id="users/a",
            user_email="a@example.com",
            chat_space_id="spaces/dm-a",
            onboarding_completed=False,
        ),
        Profile(
            workspace_user_id="users/b",
            user_email="b@example.com",
            chat_space_id=None,
            onboarding_completed=False,
        ),
        Profile(
            workspace_user_id="users/c",
            user_email="c@example.com",
            chat_space_id="spaces/dm-c",
            onboarding_completed=True,
        ),
    ]
    db = _FakeDB(profiles)
    with patch(
        "app.services.chat_sender.list_space_members",
        return_value=_memberships("users/a", "users/b", "users/c"),
    ):
        plan = asyncio.run(onboard_space_members(db, "spaces/group"))
    assert plan["dm"] == ["users/a"]
    assert plan["mention"] == ["users/b"]  # "users/c" онборднут — не упоминаем
