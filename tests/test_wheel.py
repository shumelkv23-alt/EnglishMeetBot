"""Тесты игры «Поле чудес» (Wheel of Fortune): подсказка к слову и чистые хелперы."""

from app.services.games import wheel_game
from app.services.games.banks.word_bank import WORDS


def _wheel_pool() -> list[str]:
    """Тот же пул слов, из которого выбирает pick_word."""
    return [w.lower() for w in WORDS if w.isalpha() and 4 <= len(w) <= 10]


def test_pick_word_is_single_alpha_word_4_to_10():
    import random

    rng = random.Random(1234)
    for _ in range(50):
        word = wheel_game.pick_word(rng)
        assert word.isalpha()
        assert 4 <= len(word) <= 10


def test_every_wheel_word_has_a_hint():
    # У каждого слова, доступного барабану, должна быть внятная подсказка,
    # а не заглушка «a common English word».
    for word in _wheel_pool():
        hint = wheel_game.word_hint(word)
        assert hint != "a common English word", word


def test_word_hint_known_categories():
    assert wheel_game.word_hint("elephant") == "an animal 🐾"
    assert wheel_game.word_hint("coffee") == "a drink 🥤"
    assert wheel_game.word_hint("jump") == "an action (verb) 🏃"
    assert wheel_game.word_hint("happy") == "a quality (adjective) ✨"
    assert wheel_game.word_hint("banana") == "a fruit or vegetable 🍎"


def _card_text(card: dict) -> str:
    widgets = card["cardsV2"][0]["card"]["sections"][0]["widgets"]
    return " | ".join(
        w["textParagraph"]["text"] for w in widgets if "textParagraph" in w
    )


def test_active_card_shows_word_hint():
    state = {
        "phase": "active",
        "word": "elephant",
        "revealed": [False] * 8,
        "players": ["u1", "u2"],
        "turn": 0,
        "scores": {"u1": 100, "u2": 200},
        "used_letters": [],
        "spin": None,
        "last_result": "",
    }
    names = {"u1": "Alice", "u2": "Bob"}
    text = _card_text(wheel_game.build_wheel_card(state, names, 1))
    assert "💡 It's an animal 🐾." in text
    # скрытое слово по-прежнему выводится маской
    assert "▢ ▢ ▢ ▢ ▢ ▢ ▢ ▢" in text
