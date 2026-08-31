import pytest

from app.cards.catalog import CARD_TYPE_NAMES
from app.cards.generator.recipes import TYPE_RECIPES, type_payload_errors


VALID_PAYLOADS = {
    "topic": {},
    "debate": {"statement": "Four-day workweeks improve results.", "sides": ["For", "Against"]},
    "storytelling": {"starter_sentence": "The lift opened onto a beach nobody recognised."},
    "would_you_rather": {"option_a": "Pause time", "option_b": "Rewind ten minutes"},
    "roleplay": {"scenario": "Return a broken gift without a receipt.", "roles": ["Customer", "Clerk"]},
    "culture": {
        "idiom": "break the ice",
        "meaning": "make people feel more comfortable",
        "example": "A quick game helped us break the ice.",
    },
    "hot_seat": {},
    "game_day": {"activity_id": "alias"},
    "two_truths": {},
    "mystery": {},
    "news_reaction": {
        "headline": "Libraries add conversation-club evenings",
        "summary": "Local libraries are creating more spaces for informal language practice.",
    },
    "time_capsule": {"prompt": "Describe an ordinary morning in your city in 2040."},
}


def test_recipes_cover_the_complete_card_catalog():
    assert set(TYPE_RECIPES) == set(CARD_TYPE_NAMES)
    assert len(TYPE_RECIPES) == 12


@pytest.mark.parametrize("card_type", CARD_TYPE_NAMES)
def test_every_recipe_has_english_instructions_and_a_field_contract(card_type):
    recipe = TYPE_RECIPES[card_type]
    assert recipe["instructions"].strip()
    assert "type_specific_payload" in recipe["instructions"]
    assert isinstance(recipe["required_payload_fields"], tuple)


@pytest.mark.parametrize("card_type", CARD_TYPE_NAMES)
def test_valid_payload_for_every_card_type_passes(card_type):
    assert type_payload_errors(card_type, VALID_PAYLOADS[card_type]) == []


@pytest.mark.parametrize("card_type", CARD_TYPE_NAMES)
def test_every_required_field_is_rejected_when_missing(card_type):
    required = TYPE_RECIPES[card_type]["required_payload_fields"]
    for field in required:
        payload = dict(VALID_PAYLOADS[card_type])
        payload.pop(field)
        assert f"missing type_specific_payload.{field}" in type_payload_errors(card_type, payload)


@pytest.mark.parametrize(
    ("card_type", "field"),
    [
        (card_type, field)
        for card_type, recipe in TYPE_RECIPES.items()
        for field in recipe["required_payload_fields"]
    ],
)
def test_required_fields_cannot_be_blank(card_type, field):
    payload = dict(VALID_PAYLOADS[card_type])
    payload[field] = "   "
    assert type_payload_errors(card_type, payload) == [f"missing type_specific_payload.{field}"]


@pytest.mark.parametrize(
    ("card_type", "optional_payload"),
    [
        ("hot_seat", {"questions": ["What small adventure would you try tomorrow?"]}),
        (
            "two_truths",
            {
                "statements": ["I can juggle.", "I met an astronaut.", "I dislike chocolate."],
                "lie_index": 0,
            },
        ),
        (
            "mystery",
            {"clues": ["It travels.", "It has no feet.", "You can hear it."], "answer": "Sound"},
        ),
    ],
)
def test_forward_compatible_optional_payloads_are_accepted(card_type, optional_payload):
    assert type_payload_errors(card_type, optional_payload) == []


def test_none_payload_reports_all_required_fields_in_recipe_order():
    assert type_payload_errors("roleplay", None) == [
        "missing type_specific_payload.scenario",
        "missing type_specific_payload.roles",
    ]


def test_malformed_payload_and_unknown_type_are_explicit():
    assert type_payload_errors("roleplay", []) == ["type_specific_payload must be an object"]
    assert type_payload_errors("not_a_card", {}) == ["unknown card_type: not_a_card"]
