# tests/test_vocab_units.py
import asyncio

from app.models import Profile
from app.services.vocab import _fallback, _group_level, build_vocab_card, generate_vocab


def _profile(uid, level):
    return Profile(workspace_user_id=uid, user_email=f"{uid}@x.com", english_level=level)


def test_fallback_returns_phrases():
    phrases = _fallback("A1")
    assert len(phrases) >= 3
    assert all("phrase" in p and "example" in p for p in phrases)


def test_group_level_defaults_null_to_a2():
    groups = _group_level([
        _profile("users/a", None),
        _profile("users/b", "B1"),
        _profile("users/c", "A2"),
    ])
    assert set(groups) == {"A2", "B1"}
    assert len(groups["A2"]) == 2


def test_build_vocab_card_has_topic_and_phrases():
    card = build_vocab_card("Travel", [{"phrase": "Hi", "example": "Hi there"}])
    s = str(card)
    assert "Travel" in s
    assert "Hi" in s


def test_generate_vocab_no_key_returns_fallback(monkeypatch):
    empty = type("S", (), {"llm_api_key": "", "llm_games_model": ""})()
    monkeypatch.setattr("app.services.vocab.get_settings", lambda: empty)
    phrases = asyncio.run(generate_vocab("A1", "Food"))
    assert phrases == _fallback("A1")
