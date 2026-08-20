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


def send_message(user_id: str, payload: MessagePayload) -> None:
    """
    STUB. Пока не подключён реальный Chat API — просто логирует вызов.

    При подключении реальной отправки тело заменяется на вызов
    app/services/chat_sender.py (service account), сигнатура остаётся той же.
    Функция синхронная: реальный транспорт (requests) тоже синхронный.
    """
    logger.info("[STUB SEND] to=%s text=%r card=%s", user_id, payload.text, payload.card)