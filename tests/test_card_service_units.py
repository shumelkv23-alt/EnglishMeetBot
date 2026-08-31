from types import SimpleNamespace

from app.cards.service import _build_context, _eligible_card_types


def test_build_context_anonymizes_names_and_clips_answers():
    profiles = [
        SimpleNamespace(
            id=1,
            user_name="Alice Example",
            english_level="B1",
            interests=["cooking", "travel"],
        )
    ]
    answers = [
        SimpleNamespace(
            profile_id=1,
            question_text="What did you enjoy this week?",
            answer_text="I visited a tiny bakery " + ("with amazing cinnamon rolls " * 30),
        )
    ]

    context = _build_context(profiles, answers)

    assert "Participant 1" in context
    assert "Alice Example" not in context
    assert "cooking" in context
    assert len(context) < 700


def test_eligible_card_types_respects_group_size_and_level():
    card_types = [
        SimpleNamespace(name="debate", min_group_size=4, max_group_size=None, cefr_min="B1", cefr_max="C1"),
        SimpleNamespace(name="would_you_rather", min_group_size=2, max_group_size=None, cefr_min="A1", cefr_max="B1"),
    ]
    profiles = [
        SimpleNamespace(id=1, english_level="A2"),
        SimpleNamespace(id=2, english_level="B1"),
    ]

    eligible = _eligible_card_types(card_types, profiles)

    assert [card_type.name for card_type in eligible] == ["would_you_rather"]
