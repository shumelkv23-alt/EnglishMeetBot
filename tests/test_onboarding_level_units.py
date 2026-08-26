# tests/test_onboarding_level_units.py
import asyncio

from app.models import Profile
from app.services.onboarding_answers import (
    parse_onboarding_form,
    update_profile_from_onboarding,
)


def _form_with_level(level: str) -> dict:
    return {"q8": {"stringInputs": {"value": [level]}}}


def test_parse_onboarding_form_reads_q8():
    parsed = parse_onboarding_form(_form_with_level("B1"))
    q8 = next(item for item in parsed if item["question"].startswith("8."))
    assert q8["choice"] == "B1"


def test_update_profile_sets_english_level():
    profile = Profile(workspace_user_id="users/x", user_email="x@example.com")
    parsed = parse_onboarding_form(_form_with_level("C1"))
    asyncio.run(update_profile_from_onboarding(None, profile, parsed))
    assert profile.english_level == "C1"
