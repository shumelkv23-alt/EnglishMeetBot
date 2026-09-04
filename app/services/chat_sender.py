# app/services/chat_sender.py
"""Проактивная отправка сообщений в Google Chat от имени бота (app-auth, scope chat.bot).

Бот может писать только в пространства, где он участник (включая DM, которые
уже созданы. Для рассылки всем сотрудникам домена нужна установка приложения
на домен — см. Фазу B в PLAN.md).
"""
import logging
import time

import requests
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import service_account

from app.config import get_settings

logger = logging.getLogger(__name__)

CHAT_BOT_SCOPE = "https://www.googleapis.com/auth/chat.bot"
CHAT_API_BASE = "https://chat.googleapis.com/v1"

# Google ограничивает частоту отправки сообщений: при 429/503 не падаем и не теряем
# сообщение, а ждём (Retry-After или экспоненциальная пауза) и повторяем.
RETRYABLE_STATUSES = frozenset({429, 503})
_MAX_RETRIES = 4
_BASE_BACKOFF_SECONDS = 1.0


_CREDENTIALS: service_account.Credentials | None = None


def _bot_credentials() -> service_account.Credentials:
    """Креды сервисного аккаунта с scope chat.bot (app-auth).

    Кэшируются в модуле: чтение ключа с диска и сетевой refresh не должны
    повторяться на каждый вызов (google-auth сам обновляет токен по истечении).
    """
    global _CREDENTIALS
    if _CREDENTIALS is None:
        settings = get_settings()
        creds = service_account.Credentials.from_service_account_file(
            settings.google_sa_key_file, scopes=[CHAT_BOT_SCOPE]
        )
        # Первичный refresh обязателен: без него creds.token == None → 401.
        creds.refresh(GoogleRequest())
        _CREDENTIALS = creds
    return _CREDENTIALS


def _auth_header() -> dict:
    """Заголовок Authorization со свежим токеном (обновляем по истечении часа)."""
    creds = _bot_credentials()
    if creds.expired:
        creds.refresh(GoogleRequest())
    return {"Authorization": f"Bearer {creds.token}"}


def _retry_after_seconds(resp, attempt: int) -> float:
    """Пауза перед повтором: заголовок Retry-After, иначе экспоненциальный backoff."""
    raw = resp.headers.get("Retry-After")
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return _BASE_BACKOFF_SECONDS * (2 ** attempt)


def _request(
    method: str,
    url: str,
    *,
    json: dict | None = None,
    params: dict | None = None,
) -> dict:
    """HTTP-запрос к Chat API с повтором на rate-limit (429) и 503."""
    headers = _auth_header()
    for attempt in range(_MAX_RETRIES):
        resp = requests.request(method, url, headers=headers, json=json, params=params, timeout=15)
        if resp.ok:
            return resp.json()
        if resp.status_code in RETRYABLE_STATUSES and attempt < _MAX_RETRIES - 1:
            delay = _retry_after_seconds(resp, attempt)
            logger.warning(
                "chat_api_throttled method=%s status=%s attempt=%s/%s delay=%.1fs",
                method, resp.status_code, attempt + 1, _MAX_RETRIES, delay,
            )
            time.sleep(delay)
            continue
        logger.error("chat_api_error method=%s status=%s body=%s", method, resp.status_code, resp.text)
        resp.raise_for_status()
    raise RuntimeError(f"chat request failed after {_MAX_RETRIES} attempts: {url}")


def send_text(space_name: str, text: str) -> dict:
    """Отправить текстовое сообщение в пространство от имени бота.

    space_name — например 'spaces/7UqhjKAAAAE' (имя пространства, не id).
    """
    return send_message(space_name, text=text)


def send_message(
    space_name: str,
    text: str = "",
    cards_v2: list[dict] | None = None,
    cards: list[dict] | None = None,
) -> dict:
    """Отправить сообщение (текст и/или Cards V1/V2) в пространство от имени бота."""
    body: dict = {}
    if text:
        body["text"] = text
    if cards_v2:
        body["cardsV2"] = cards_v2
    if cards:
        body["cards"] = cards
    result = _request("POST", f"{CHAT_API_BASE}/{space_name}/messages", json=body)
    logger.info("message_sent space=%s", space_name)
    return result


def patch_message(
    message_name: str,
    text: str | None = None,
    cards_v2: list[dict] | None = None,
) -> dict:
    """Обновить существующее сообщение на месте (messages.patch).

    message_name — имя вида 'spaces/XXX/messages/YYY' (из resp['name'] от send_message).
    updateMask строится по тому, какие поля переданы (text и/или cardsV2).
    """
    update_fields: list[str] = []
    body: dict = {}
    if text is not None:
        body["text"] = text
        update_fields.append("text")
    if cards_v2 is not None:
        body["cardsV2"] = cards_v2
        update_fields.append("cardsV2")
    if not update_fields:
        return {}
    result = _request(
        "PATCH",
        f"{CHAT_API_BASE}/{message_name}",
        json=body,
        params={"updateMask": ",".join(update_fields)},
    )
    logger.info("message_patched name=%s", message_name)
    return result


def list_space_members(space_name: str) -> list[dict]:
    """Список участников пространства (memberships).

    Возвращает массив memberships, где member.name вида 'users/<id>' у человека.
    """
    memberships: list[dict] = []
    page_token: str | None = None
    while True:
        params = {"pageToken": page_token} if page_token else None
        resp = requests.get(
            f"{CHAT_API_BASE}/{space_name}/members",
            headers=_auth_header(),
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        memberships.extend(data.get("memberships", []))
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return memberships


def list_bot_spaces() -> list[dict]:
    """Все пространства, где состоит бот (spaces.list, app-auth)."""
    spaces: list[dict] = []
    page_token: str | None = None
    while True:
        params = {"pageToken": page_token} if page_token else None
        resp = requests.get(
            f"{CHAT_API_BASE}/spaces",
            headers=_auth_header(),
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        spaces.extend(data.get("spaces", []))
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return spaces


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