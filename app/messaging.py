# app/messaging.py
"""Интерфейс отправки сообщений в Google Chat (контракт, см. CONTRACTS.md).

Единственная граница между логикой бота и реальным Chat API.
Все модули вызывают send_message(user_id, payload) и НЕ знают,
что внутри — стаб или настоящий запрос.

Сигнатуру менять нельзя без общего обсуждения: на неё опираются
app/activities.py (Тиммейт A) и app/scheduling.py (Тиммейт B).
"""
import logging

from app.schemas import MessagePayload

logger = logging.getLogger(__name__)

try:
    from app.services.chat_sender import find_user_dm_space, send_message as _chat_send

    _REAL_API = True
except Exception:
    _REAL_API = False


def send_message(user_id: str, payload: MessagePayload) -> None:
    """
    Отправить сообщение пользователю (user_id = workspace_user_id, 'users/...').

    Если реальный Chat API подключён — находит DM-пространство пользователя
    и отправляет туда. Иначе — логирует вызов (стаб).
    """
    if _REAL_API and user_id and user_id.startswith("users/"):
        try:
            space = find_user_dm_space(user_id)
            if space:
                cards_v2 = payload.card.get("cardsV2") if payload.card else None
                _chat_send(space, text=payload.text, cards_v2=cards_v2)
                return
            logger.warning("dm_space_not_found user=%s, fallback to stub", user_id)
        except Exception:
            logger.exception("real_send_failed user=%s", user_id)
    logger.info("[STUB SEND] to=%s text=%r card=%s", user_id, payload.text, payload.card)
