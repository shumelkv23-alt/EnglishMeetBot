# tests/test_card_llm_prompt_units.py
from app.cards.generator.llm import _build_card_prompt


def test_prompt_includes_type_and_theme():
    prompt = _build_card_prompt("topic", "B1", "likes food", theme="Food and cooking")
    assert "Card type: topic" in prompt
    assert "Group level: B1" in prompt
    assert "This week's theme: Food and cooking" in prompt


def test_prompt_without_theme_has_no_theme_line():
    prompt = _build_card_prompt("topic", "B1", "likes food")
    assert "This week's theme" not in prompt


def test_prompt_lists_recent_topics():
    prompt = _build_card_prompt(
        "topic", "B1", "likes food",
        recent_topics=["Food and Travel", "Street food"],
    )
    assert "do NOT repeat" in prompt
    assert "- Food and Travel" in prompt
    assert "- Street food" in prompt


def test_prompt_without_recent_topics_has_no_block():
    prompt = _build_card_prompt("topic", "B1", "likes food", recent_topics=None)
    assert "do NOT repeat" not in prompt
