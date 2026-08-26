import asyncio
import random
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.cards.activity_matcher import GAMES, match_activity
from app.cards.catalog import CARD_TYPES
from app.cards.generator.llm import generate_llm_content
from app.cards.generator.template import build_template_content
from app.cards.rotation import compute_weight, select_card_type
from app.cards.validator import validate_card

CT = namedtuple("CT", ["name", "base_weight", "cooldown"])


def _types() -> list:
    return [CT(t["name"], t["base_weight"], t["cooldown"]) for t in CARD_TYPES]


# --- Rotation Engine ---


def test_compute_weight_zero_on_cooldown():
    topic = CT("topic", 1.0, 3)
    now = datetime.now(timezone.utc)
    history = [
        ("topic", now - timedelta(minutes=30)),
        ("debate", now - timedelta(minutes=20)),
        ("debate", now - timedelta(minutes=10)),
    ]
    assert compute_weight(topic, history) == 0.0


def test_compute_weight_decays_after_cooldown():
    topic = CT("topic", 1.0, 3)
    now = datetime.now(timezone.utc)
    history = [("topic", now - timedelta(minutes=60))] + [
        ("debate", now - timedelta(minutes=m)) for m in (50, 40, 30, 20)
    ]
    # since = 4 встречи после topic; decay = min(1, 4/6) = 2/3
    assert abs(compute_weight(topic, history) - 2 / 3) < 1e-9


def test_compute_weight_full_weight_when_unused():
    topic = CT("topic", 1.0, 3)
    assert compute_weight(topic, [("debate", datetime.now(timezone.utc))]) == 1.0


def test_select_card_type_fallback_when_all_on_cooldown():
    types = [CT("a", 1.0, 3), CT("b", 1.0, 3)]
    now = datetime.now(timezone.utc)
    history = [("a", now), ("b", now)]
    rng = random.Random(1)
    assert select_card_type(types, history, rng) is not None


# --- Validator ---


def test_validator_missing_fields():
    errors = validate_card({"difficulty_level": "B1", "main_content": {"topic": "x"}})
    assert "missing card_type" in errors


def test_validator_stop_topic():
    content = {
        "card_type": "topic",
        "difficulty_level": "B1",
        "main_content": {"topic": "Religion and politics"},
    }
    assert any("stop-topic" in e for e in validate_card(content))


def test_validator_stop_topic_in_wrapup_and_vocab():
    content = {
        "card_type": "topic",
        "difficulty_level": "B1",
        "main_content": {"topic": "A safe topic"},
        "wrap_up_question": "What do you think about politics?",
        "vocab_box": [{"phrase": "election", "translation": "выборы", "example": "x"}],
    }
    errors = validate_card(content)
    assert any("stop-topic" in e for e in errors)


# --- Template generator ---


def test_template_all_types_valid():
    for t in CARD_TYPES:
        content = build_template_content(t["name"], {"topic": "A test topic"}, "B1")
        errors = validate_card({**content, "card_type": t["name"]})
        assert errors == [], f"{t['name']}: {errors}"


def test_template_would_you_rather_payload():
    content = build_template_content(
        "would_you_rather", {"option_a": "Tea forever", "option_b": "Coffee forever"}, "A2"
    )
    payload = content["main_content"]["type_specific_payload"]
    assert payload["option_a"] == "Tea forever"
    assert payload["option_b"] == "Coffee forever"


# --- Activity matcher ---


def test_match_activity_by_tags():
    r = match_activity("Let's talk about vocabulary and describing words")
    assert r["activity_id"] == "alias"


def test_match_activity_fallback():
    r = match_activity("A completely unrelated topic", rng=random.Random(1))
    assert r["activity_id"] in {g["activity_id"] for g in GAMES}


# --- LLM generator ---


def test_llm_fallback_without_key(monkeypatch):
    fake = SimpleNamespace(llm_api_key="", llm_games_model="m/x", llm_base_url="https://t.local")
    monkeypatch.setattr("app.cards.generator.llm.get_settings", lambda: fake)
    assert asyncio.run(generate_llm_content("topic", "B1", "ctx")) is None
