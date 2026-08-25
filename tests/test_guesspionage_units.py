# tests/test_guesspionage_units.py
from app.services.games.guesspionage import (
    GUESS_QUESTIONS,
    build_guess_card,
    build_higher_lower_card,
    score_round,
)


def test_questions_non_empty_and_valid_percents():
    assert len(GUESS_QUESTIONS) >= 1
    for _, pct in GUESS_QUESTIONS:
        assert 0 <= pct <= 100


def test_score_round_close_guesser_and_higher_win():
    # true=70, guess=60 → |60-70|=10 → 2; higher угадал (60 < 70)
    assert score_round(70, 60, higher={"a"}, lower={"b"}, guesser="g") == {"g": 2, "a": 1}


def test_score_round_very_close_guesser_and_lower_win():
    # true=70, guess=75 → |75-70|=5 → 3; lower угадал (75 > 70)
    assert score_round(70, 75, higher={"a"}, lower={"b"}, guesser="g") == {"g": 3, "b": 1}


def test_score_round_far_guesser():
    # true=70, guess=20 → 1; higher угадал
    assert score_round(70, 20, higher={"a"}, lower={"b"}, guesser="g") == {"g": 1, "a": 1}


def test_score_round_exact_guess_no_direction_points():
    # guess == true → направление не угадывает никто
    assert score_round(70, 70, higher={"a"}, lower={"b"}, guesser="g") == {"g": 3}


def test_build_higher_lower_card_buttons_and_choices():
    card = build_higher_lower_card("Q?", 60, "https://x/hook")
    buttons = card["cardsV2"][0]["card"]["sections"][0]["widgets"][0]["buttonList"]["buttons"]
    assert [b["text"] for b in buttons] == ["Higher ⬆️", "Lower ⬇️"]
    choices = [b["onClick"]["action"]["parameters"][1]["value"] for b in buttons]
    assert choices == ["higher", "lower"]


def test_build_guess_card_has_input_and_space_param():
    card = build_guess_card("Q?", "https://x/hook", "spaces/grp")
    input_widget = card["cardsV2"][0]["card"]["sections"][0]["widgets"][0]
    assert input_widget["textInput"]["name"] == "guess"
    button = card["cardsV2"][0]["card"]["sections"][1]["widgets"][0]["buttonList"]["buttons"][0]
    params = {p["key"]: p["value"] for p in button["onClick"]["action"]["parameters"]}
    assert params["method"] == "submit_guesspionage_guess"
    assert params["space"] == "spaces/grp"
