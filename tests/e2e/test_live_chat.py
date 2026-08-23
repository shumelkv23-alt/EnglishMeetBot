"""Live-тесты: реальное обращение к Google Chat API через сервисный аккаунт.

Запуск: pytest -m live. Требуют CHAT_TEST_SPACE в .env и валидный sa-key.json.
Без них — честно скипаются. БД не нужна.
"""
import os

import pytest

from app.config import get_settings

pytestmark = pytest.mark.live


def _require_google() -> str:
    settings = get_settings()
    space = settings.chat_test_space
    if not space:
        pytest.skip("CHAT_TEST_SPACE не задан в .env")
    if not os.path.exists(settings.google_sa_key_file):
        pytest.skip(f"{settings.google_sa_key_file} не найден")
    return space


def test_send_text_to_test_space():
    from app.services.chat_sender import send_text

    space = _require_google()
    resp = send_text(space, "e2e live ping 🤖")
    # успешная отправка возвращает объект сообщения с полем name
    assert resp.get("name", "").startswith("spaces/")


def test_list_bot_spaces():
    from app.services.chat_sender import list_bot_spaces

    _require_google()
    assert isinstance(list_bot_spaces(), list)


def test_list_space_members():
    from app.services.chat_sender import list_space_members

    space = _require_google()
    assert isinstance(list_space_members(space), list)


def test_find_user_dm_space_rejects_bad_input():
    from app.services.chat_sender import find_user_dm_space

    assert find_user_dm_space("") == ""
    assert find_user_dm_space("spaces/abc") == ""  # не users/... — не ищем
