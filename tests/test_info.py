"""Тесты команды «info»: карточка возможностей бота (личка vs группа)."""

from app.api.google_chat import _info_card, _is_info_command


def test_is_info_command_matches():
    for t in (
        "info", "инфо", "help", "помощь", "хелп", "возможности",
        "команды", "commands", "что ты умеешь",
    ):
        assert _is_info_command(t), t
    for t in ("games", "level", "learn", "points", "top", "hi", "привет"):
        assert not _is_info_command(t), t


def test_info_card_id_and_sections():
    for card in (_info_card(True), _info_card(False)):
        assert card["cardsV2"][0]["cardId"] == "info"
        sections = card["cardsV2"][0]["card"]["sections"]
        assert len(sections) == 4
        # у каждой секции есть заголовок и ровно один текстовый виджет
        for s in sections:
            assert isinstance(s["header"], str) and s["header"]
            assert len(s["widgets"]) == 1
            assert "textParagraph" in s["widgets"][0]


def _text(card: dict) -> str:
    return " ".join(
        w["textParagraph"]["text"]
        for s in card["cardsV2"][0]["card"]["sections"]
        for w in s["widgets"]
    )


def test_dm_card_lists_dm_features_only():
    text = _text(_info_card(True))
    for key in ("learn", "level", "Hangman", "Wordle", "points", "анкета"):
        assert key in text, key
    # не должно быть групповых игр и расписания
    for key in ("Alias", "Поле чудес", "Guesspionage", "таблица"):
        assert key not in text, key


def test_group_card_lists_group_features_only():
    text = _text(_info_card(False))
    for key in ("таблица", "вопросы", "Alias", "Поле чудес", "points"):
        assert key in text, key
    # не должно быть DM-игр и курсов
    for key in ("Hangman", "Millionaire", "level", "learn"):
        assert key not in text, key


def test_purpose_present_in_both():
    for card in (_info_card(True), _info_card(False)):
        assert "EnglishMeetBot" in _text(card)
