"""Data-driven LLM recipes for every lesson-card type.

The recipe tells the generator what makes a card type distinct and which keys
must be present in ``main_content.type_specific_payload``.  The field names for
the existing mechanics match the Google Chat renderer.  The three mechanics
that did not previously have a complete payload (hot seat, two truths, and
mystery) describe optional, forward-compatible fields without making them
mandatory for the current renderer.
"""
from collections.abc import Mapping
from typing import Any, TypedDict

__all__ = ["CardTypeRecipe", "TYPE_RECIPES", "type_payload_errors"]


class CardTypeRecipe(TypedDict):
    """Prompt instruction and required type-specific JSON keys."""

    instructions: str
    required_payload_fields: tuple[str, ...]


TYPE_RECIPES: dict[str, CardTypeRecipe] = {
    "topic": {
        "instructions": (
            "Create one fresh, specific open-discussion topic. The three main questions "
            "must progress from an easy personal entry point to comparison and then deeper "
            "reflection. Use an empty type_specific_payload object."
        ),
        "required_payload_fields": (),
    },
    "debate": {
        "instructions": (
            "Create a safe but genuinely debatable statement with no obviously correct side. "
            "Put the statement in type_specific_payload.statement and exactly two concise "
            "opposing positions in type_specific_payload.sides."
        ),
        "required_payload_fields": ("statement", "sides"),
    },
    "storytelling": {
        "instructions": (
            "Create a vivid collaborative-story opening that immediately gives the group a "
            "character, situation, and unresolved surprise. Put it in "
            "type_specific_payload.starter_sentence."
        ),
        "required_payload_fields": ("starter_sentence",),
    },
    "would_you_rather": {
        "instructions": (
            "Create a playful, balanced dilemma whose alternatives are meaningfully different "
            "and invite explanation. Put the alternatives in type_specific_payload.option_a "
            "and type_specific_payload.option_b."
        ),
        "required_payload_fields": ("option_a", "option_b"),
    },
    "roleplay": {
        "instructions": (
            "Create a concrete everyday scenario with a useful communication challenge. Put "
            "the setup in type_specific_payload.scenario and the two distinct participant roles "
            "in type_specific_payload.roles."
        ),
        "required_payload_fields": ("scenario", "roles"),
    },
    "culture": {
        "instructions": (
            "Choose a useful English idiom that fits the topic and can prompt a respectful "
            "cross-cultural comparison. Put the expression, plain-English meaning, and one "
            "natural example in type_specific_payload.idiom, meaning, and example."
        ),
        "required_payload_fields": ("idiom", "meaning", "example"),
    },
    "hot_seat": {
        "instructions": (
            "Create five to seven quick, safe personal questions for one participant in the hot "
            "seat. They should start easy and become more imaginative without requesting "
            "sensitive information. Use the main sub_questions for the current renderer; "
            "type_specific_payload may be empty, or may optionally contain questions for a "
            "future richer renderer."
        ),
        "required_payload_fields": (),
    },
    "game_day": {
        "instructions": (
            "Choose the group game that best reinforces the topic and language goal. Put one "
            "supported id in type_specific_payload.activity_id: alias, snake_oil, quiplash, "
            "who_am_i, spy, or guesspionage."
        ),
        "required_payload_fields": ("activity_id",),
    },
    "two_truths": {
        "instructions": (
            "Guide participants to share two true statements and one lie about themselves, then "
            "ask useful follow-up questions. Never invent claims about real participants. "
            "type_specific_payload may be empty; as a forward-compatible option it may contain "
            "three fictional example statements and a zero-based lie_index."
        ),
        "required_payload_fields": (),
    },
    "mystery": {
        "instructions": (
            "Create an unexpected but approachable mystery topic and questions that reveal it "
            "gradually. type_specific_payload may be empty; as a forward-compatible option it "
            "may contain three progressively clearer clues and a concise answer."
        ),
        "required_payload_fields": (),
    },
    "news_reaction": {
        "instructions": (
            "Create a neutral, timeless news-style item that is safe to discuss without live "
            "fact checking. Put its headline and two-sentence context in "
            "type_specific_payload.headline and type_specific_payload.summary."
        ),
        "required_payload_fields": ("headline", "summary"),
    },
    "time_capsule": {
        "instructions": (
            "Create one concrete past-or-future imagination task with a clear time horizon and "
            "something participants can describe. Put it in type_specific_payload.prompt."
        ),
        "required_payload_fields": ("prompt",),
    },
}


def _is_blank(value: Any) -> bool:
    """Whether a required JSON value carries no usable content."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, Mapping):
        return not value
    if isinstance(value, (list, tuple, set, frozenset)):
        return not value or all(_is_blank(item) for item in value)
    return False


def type_payload_errors(card_type: str, payload: Mapping[str, Any] | None) -> list[str]:
    """Return deterministic contract errors for a type-specific payload.

    ``None`` is equivalent to an empty object, which is valid for ``topic`` and
    produces missing-field errors for mechanics that require their own data.
    """
    recipe = TYPE_RECIPES.get(card_type)
    if recipe is None:
        return [f"unknown card_type: {card_type}"]
    if payload is None:
        payload = {}
    elif not isinstance(payload, Mapping):
        return ["type_specific_payload must be an object"]

    return [
        f"missing type_specific_payload.{field}"
        for field in recipe["required_payload_fields"]
        if field not in payload or _is_blank(payload[field])
    ]
