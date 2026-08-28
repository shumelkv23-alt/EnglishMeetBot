# tests/test_wordle_units.py
from app.services.wordle import _sanitize_llm_word


def test_sanitize_valid_word_unchanged():
    assert _sanitize_llm_word("crane", 5) == "crane"


def test_sanitize_lowercases_and_strips_quotes():
    assert _sanitize_llm_word('"CRANE"', 5) == "crane"
    assert _sanitize_llm_word("'crane'.", 5) == "crane"


def test_sanitize_takes_first_word():
    assert _sanitize_llm_word("crane because it is common", 5) == "crane"


def test_sanitize_rejects_wrong_length():
    assert _sanitize_llm_word("cat", 5) is None
    assert _sanitize_llm_word("banana", 5) is None


def test_sanitize_rejects_non_alpha():
    assert _sanitize_llm_word("c-r-a-n", 5) is None
    assert _sanitize_llm_word("слово", 5) is None
    assert _sanitize_llm_word("12345", 5) is None


def test_sanitize_rejects_empty():
    assert _sanitize_llm_word("", 5) is None
    assert _sanitize_llm_word(None, 5) is None
