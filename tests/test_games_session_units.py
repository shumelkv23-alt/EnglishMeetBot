# tests/test_games_session_units.py
import pytest

from app.services.games.session import GameManager, build_join_card


@pytest.fixture(autouse=True)
def _clean_sessions():
    GameManager.reset()
    yield
    GameManager.reset()


def test_start_creates_and_get_returns_session():
    session = GameManager.start("guesspionage", "spaces/1")
    assert session.game == "guesspionage"
    assert GameManager.get("spaces/1") is session


def test_join_adds_player_and_name():
    GameManager.start("spy", "spaces/1")
    session = GameManager.join("spaces/1", "users/a", "Alice")
    assert session is not None
    assert session.players == ["users/a"]
    assert session.names == {"users/a": "Alice"}


def test_join_deduplicates_players():
    GameManager.start("spy", "spaces/1")
    GameManager.join("spaces/1", "users/a")
    GameManager.join("spaces/1", "users/a")
    assert len(GameManager.get("spaces/1").players) == 1


def test_join_returns_none_when_no_session_or_started():
    assert GameManager.join("spaces/1", "users/a") is None
    GameManager.start("spy", "spaces/1")
    GameManager.get("spaces/1").started = True
    assert GameManager.join("spaces/1", "users/a") is None


def test_end_removes_session():
    GameManager.start("spy", "spaces/1")
    GameManager.end("spaces/1")
    assert GameManager.get("spaces/1") is None


def test_build_join_card_has_two_buttons():
    card = build_join_card("https://x/hook", "Шпион")
    buttons = card["cardsV2"][0]["card"]["sections"][1]["widgets"][0]["buttonList"]["buttons"]
    assert [b["text"] for b in buttons] == ["Я в деле", "Начать"]
    methods = [b["onClick"]["action"]["parameters"][0]["value"] for b in buttons]
    assert methods == ["join_game", "start_game"]
