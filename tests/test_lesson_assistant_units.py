from app.services.lesson_assistant import (
    GAME_RULES,
    _extract_game_for_rules,
    _format_topic,
    _is_help_query,
    _is_question,
    _is_suggest_query,
    _is_topic_query,
    _is_translation_query,
    build_suggestions_card,
)


def test_is_topic_query():
    assert _is_topic_query("what is the topic today?")
    assert _is_topic_query("what are we discussing?")
    assert not _is_topic_query("let's play alias")


def test_extract_game_for_rules():
    assert _extract_game_for_rules("how to play spy?") == "spy"
    assert _extract_game_for_rules("rules of snake oil") == "snake_oil"
    assert _extract_game_for_rules("как играть в alias") == "alias"
    assert _extract_game_for_rules("what's the topic?") is None


def test_is_question():
    assert _is_question("what games can we play?")
    assert _is_question("which game is best?")
    assert not _is_question("I like travel")


def test_is_translation_query():
    assert _is_translation_query("how do you say 'apple' in English?")
    assert _is_translation_query("translate 'застрял' please")
    assert not _is_translation_query("let's play alias")


def test_is_suggest_query():
    assert _is_suggest_query("what can we do?")
    assert _is_suggest_query("suggest something")
    assert not _is_suggest_query("I like travel")


def test_is_help_query():
    assert _is_help_query("I don't understand")
    assert not _is_help_query("I like travel")


def test_format_topic_with_questions():
    text = _format_topic("Food and Travel", ["Which food do you love?", "Why?"])
    assert "Food and Travel" in text
    assert "Which food do you love?" in text


def test_format_topic_empty():
    assert "hasn't been generated" in _format_topic(None, [])


def test_build_suggestions_card():
    card = build_suggestions_card([{"title": "Play Alias", "description": "Guess words in teams"}])
    c = card["cardsV2"][0]["card"]
    assert c["header"]["title"] == "Here are a few ideas 💡"
    assert c["sections"][0]["header"].startswith("1.")


def test_build_suggestions_card_empty_fallback():
    card = build_suggestions_card([])
    assert "text" in card


def test_all_games_have_rules():
    for aid in ("alias", "snake_oil", "quiplash", "who_am_i", "spy", "guesspionage"):
        assert aid in GAME_RULES
        assert GAME_RULES[aid].strip()
