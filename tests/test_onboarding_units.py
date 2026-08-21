# tests/test_onboarding_units.py
from app.services.space_onboarding import plan_onboarding


def test_plan_onboarding_split():
    members = ["users/a", "users/b", "users/c"]
    profiles = {"users/a": True, "users/b": False}
    r = plan_onboarding(profiles, members)
    assert r["dm"] == ["users/a"]
    assert r["mention"] == ["users/b", "users/c"]


def test_plan_onboarding_all_mention_without_profiles():
    # Нет профилей — нет DM с ботом: все уходят в @упоминание
    r = plan_onboarding({}, ["users/a", "users/b"])
    assert r["dm"] == []
    assert r["mention"] == ["users/a", "users/b"]
