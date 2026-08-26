# tests/test_levels_units.py
from app.services.levels import (
    CEFR_LEVELS,
    CEFR_ORDER,
    build_level_card,
    level_choice_items,
    normalize_level,
)


def test_normalize_level_accepts_cefr_code():
    assert normalize_level("A1") == "A1"
    assert normalize_level("  c2 ") == "C2"


def test_normalize_level_rejects_unknown():
    assert normalize_level("X9") is None
    assert normalize_level("") is None


def test_level_choice_items_covers_all_cefr():
    codes = [item["value"] for item in level_choice_items()]
    assert codes == list(CEFR_LEVELS.keys())


def test_build_level_card_contains_current_level():
    card = build_level_card("B1", "aud")
    assert "Current level: B1" in str(card)
    assert "set_level" in str(card)


def test_build_level_card_without_level():
    card = build_level_card(None, "aud")
    assert "Current level:" not in str(card)


def test_cefr_order_is_monotonic():
    assert CEFR_ORDER["A1"] < CEFR_ORDER["C2"]
