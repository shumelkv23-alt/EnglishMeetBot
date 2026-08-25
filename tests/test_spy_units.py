# tests/test_spy_units.py
import random

from app.services.games.spy import (
    WORD_BANK,
    assign_roles,
    build_spy_vote_card,
    build_start_vote_card,
    score_spy,
    tally_votes,
)


def test_word_bank_non_empty():
    assert len(WORD_BANK) >= 1
    for topic, words in WORD_BANK.items():
        assert len(words) >= 1


def test_assign_roles_picks_valid_topic_word_and_spy():
    players = ["users/a", "users/b", "users/c"]
    roles = assign_roles(players, rng=random.Random(0))
    assert roles["topic"] in WORD_BANK
    assert roles["word"] in WORD_BANK[roles["topic"]]
    assert roles["spy"] in players


def test_score_spy_caught_gives_civilians_point():
    # шпион "s" набрал 2 голоса, у "x" — 1 → пойман
    votes = {"a": "s", "b": "s", "c": "x"}
    assert score_spy("s", votes, ["a", "b", "c", "s"]) == {"a": 1, "b": 1, "c": 1}


def test_score_spy_not_caught_gives_spy_points():
    votes = {"a": "x", "b": "x", "c": "y"}
    assert score_spy("s", votes, ["a", "b", "c", "s"]) == {"s": 3}


def test_score_spy_tie_not_caught():
    # шпион "s" и "x" делят голоса → ничья, шпион не пойман
    votes = {"a": "s", "b": "x"}
    assert score_spy("s", votes, ["a", "b", "s", "x"]) == {"s": 3}


def test_tally_votes_counts_each_player_with_zeroes():
    votes = {"a": "s", "b": "s", "c": "x"}
    assert tally_votes(votes, ["a", "b", "c", "s", "x"]) == {"a": 0, "b": 0, "c": 0, "s": 2, "x": 1}


def test_build_spy_vote_card_has_button_per_player():
    names = {"users/a": "Alice", "users/b": "Bob"}
    card = build_spy_vote_card(names, ["users/a", "users/b"], "https://x/hook")
    buttons = card["cardsV2"][0]["card"]["sections"][1]["widgets"][0]["buttonList"]["buttons"]
    assert [b["text"] for b in buttons] == ["Alice", "Bob"]
    targets = [b["onClick"]["action"]["parameters"][1]["value"] for b in buttons]
    assert targets == ["users/a", "users/b"]


def test_build_spy_vote_card_shows_live_tally_and_waiting():
    names = {"users/a": "Alice", "users/b": "Bob", "users/c": "Carol"}
    votes = {"users/a": "users/b"}  # Alice проголосовала за Bob
    card = build_spy_vote_card(names, ["users/a", "users/b", "users/c"], "https://x/hook", votes)
    text = card["cardsV2"][0]["card"]["sections"][0]["widgets"][0]["textParagraph"]["text"]
    assert "Bob — 1" in text
    assert "Alice — 0" in text
    assert "Ждут голоса: Bob, Carol" in text


def test_build_start_vote_card_has_topic_and_button():
    card = build_start_vote_card("food", "https://x/hook")
    assert "food" in card["cardsV2"][0]["card"]["header"]["title"]
    button = card["cardsV2"][0]["card"]["sections"][0]["widgets"][0]["buttonList"]["buttons"][0]
    assert button["onClick"]["action"]["parameters"][0]["value"] == "spy_start_vote"
