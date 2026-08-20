# app/services/chat_sender.py
"""Проактивная отправка сообщений в Google Chat от имени бота (app-auth, scope chat.bot).

Бот может писать только в пространства, где он участник (включая DM, которые
уже созданы. Для рассылки всем сотрудникам домена нужна установка приложения
на домен — см. Фазу B в PLAN.md).
"""
import logging

import requests
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import service_account

from app.config import get_settings

logger = logging.getLogger(__name__)

CHAT_BOT_SCOPE = "https://www.googleapis.com/auth/chat.bot"
CHAT_API_BASE = "https://chat.googleapis.com/v1"


def _bot_credentials() -> service_account.Credentials:
    """Креды сервисного аккаунта с scope chat.bot (app-auth)."""
    settings = get_settings()
    creds = service_account.Credentials.from_service_account_file(
        settings.google_sa_key_file, scopes=[CHAT_BOT_SCOPE]
    )
    creds.refresh(GoogleRequest())
    return creds


def send_text(space_name: str, text: str) -> dict:
    """Отправить текстовое сообщение в пространство от имени бота.

    space_name — например 'spaces/7UqhjKAAAAE' (имя пространства, не id).
    """
    return send_message(space_name, text=text)


def send_message(space_name: str, text: str = "", cards_v2: list[dict] | None = None) -> dict:
    """Отправить сообщение (текст и/или Cards V2) в пространство от имени бота."""
    creds = _bot_credentials()
    body: dict = {}
    if text:
        body["text"] = text
    if cards_v2:
        body["cardsV2"] = cards_v2
    resp = requests.post(
        f"{CHAT_API_BASE}/{space_name}/messages",
        headers={"Authorization": f"Bearer {creds.token}"},
        json=body,
        timeout=15,
    )
    resp.raise_for_status()
    logger.info("message_sent space=%s status=%s", space_name, resp.status_code)
    return resp.json()


def list_space_members(space_name: str) -> list[dict]:
    """Список участников пространства (memberships).

    Возвращает массив memberships, где member.name вида 'users/<id>' у человека.
    """
    creds = _bot_credentials()
    resp = requests.get(
        f"{CHAT_API_BASE}/{space_name}/members",
        headers={"Authorization": f"Bearer {creds.token}"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("memberships", [])


def list_bot_spaces() -> list[dict]:
    """Все пространства, где состоит бот (spaces.list, app-auth)."""
    creds = _bot_credentials()
    resp = requests.get(
        f"{CHAT_API_BASE}/spaces",
        headers={"Authorization": f"Bearer {creds.token}"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("spaces", [])


def find_user_dm_space(user_id: str) -> str:
    """Найти DM-пространство пользователя с ботом по spaces.list + members.

    Возвращает имя space (например 'spaces/XXX') или ''.
    user_id — вида 'users/<id>'.
    """
    if not user_id or not user_id.startswith("users/"):
        return ""
    for space in list_bot_spaces():
        if space.get("spaceType") != "DIRECT_MESSAGE":
            continue
        memberships = list_space_members(space["name"])
        member_names = {
            m.get("member", {}).get("name", "")
            for m in memberships
            if m.get("member", {}).get("type") == "HUMAN"
        }
        if user_id in member_names:
            logger.info("user_dm_space_found user=%s space=%s", user_id, space["name"])
            return space["name"]
    logger.warning("user_dm_space_not_found user=%s", user_id)
    return ""