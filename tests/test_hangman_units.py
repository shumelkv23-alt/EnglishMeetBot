"""Юнит-тесты hangman: повторная буква не должна падать с NameError."""
from app.services.games.hangman import _apply_guess


class _Session:
    id = 123


async def test_apply_guess_repeated_letter_no_error():
    state = {"word": "cat", "guessed": ["a"], "wrong": [], "wrong_count": 0, "max_wrong": 6}
    result = await _apply_guess(None, _Session(), state, None, "a", as_word=False)
    assert "already tried" in result["text"]
    assert "cardsV2" in result
