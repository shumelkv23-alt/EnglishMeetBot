# tests/test_google_chat_level.py
from app.api.google_chat import _is_level_command


def test_is_level_command_matches_variants():
    assert _is_level_command("/level")
    assert _is_level_command("!level")
    assert _is_level_command("level")
    assert _is_level_command("lvl")


def test_is_level_command_ignores_other_text():
    assert not _is_level_command("hello")
    assert not _is_level_command("leveling up")
