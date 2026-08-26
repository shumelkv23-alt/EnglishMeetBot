# tests/test_cards_plan_units.py
from app.cards.generator.template import build_template_content
from app.cards.service import build_card_message


def test_template_fills_stretch_challenge_for_all_types():
    from app.cards.catalog import CARD_TYPES

    for t in CARD_TYPES:
        content = build_template_content(t["name"], {}, "B1")
        assert content.get("stretch_challenge"), f"stretch missing for {t['name']}"


def test_build_card_message_renders_four_phases():
    content = build_template_content("topic", {}, "B1")
    content["stretch_challenge"] = "A harder question"
    card = build_card_message(content)
    s = str(card)
    assert "Warm-up" in s
    assert "Stretch" in s
    assert "Wrap-up" in s
