# app/schemas.py
from pydantic import BaseModel
from typing import Optional, Dict, Any
from enum import Enum
from datetime import datetime

class GoogleChatUser(BaseModel):
    """Пользователь Google Chat"""
    name: Optional[str] = None
    displayName: Optional[str] = None
    email: Optional[str] = None

class GoogleChatMessage(BaseModel):
    """Сообщение от пользователя"""
    name: Optional[str] = None
    argumentText: Optional[str] = None
    text: Optional[str] = None

class GoogleChatWebhookPayload(BaseModel):
    """Основная структура вебхука от Google Chat"""
    type: str  # MESSAGE, ADDED_TO_SPACE, REMOVED_FROM_SPACE
    user: Optional[GoogleChatUser] = None
    message: Optional[GoogleChatMessage] = None
    space: Optional[Dict[str, Any]] = None


# ============================================================
# ДОМЕННЫЕ МОДЕЛИ (контракт командной разработки, см. CONTRACTS.md)
#
# ВАЖНО: user_id везде — это workspace_user_id из Google Chat,
# строка вида "users/123456789" (не email, не int-ид профиля из БД).
# Сюда НЕ добавлять и НЕ менять поля молча — только через общий PR.
# ============================================================


class MeetingStatus(str, Enum):
    VOTING = "voting"
    TIME_FINALIZED = "time_finalized"
    ESCALATED = "escalated"
    SCHEDULED = "scheduled"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class Slot(BaseModel):
    id: str
    day: str          # "Wed", "Fri" — день недели
    time: str          # "19:00" — 24-часовой формат "HH:MM"
    votes: list[str] = []   # user_id тех, кто отметил слот (workspace_user_id)


class MeetingInstance(BaseModel):
    """Экземпляр недельного голосования за время встречи.

    week_start / deadline — всегда timezone-aware (UTC).
    """
    id: str
    week_start: datetime
    status: MeetingStatus
    slots: list[Slot]
    final_slot_id: str | None = None
    deadline: datetime


class WeeklyAnswer(BaseModel):
    """Один ответ участника на еженедельный вопрос."""
    user_id: str
    question_id: str
    answer_text: str
    week_id: str


class Activity(BaseModel):
    """Готовая активность для встречи.

    type:
      - "digest" — мини-дайджест недели, content:
          {"kind": "digest", "title": "...", "items": [{"user": "Имя", "text": "Ответ"}, ...]}
      - "guess_colleague" — угадай коллегу, content:
          {"kind": "guess_colleague", "question": "...", "answer": "...", "author_user_id": "users/..."}
    """
    type: str          # "digest" | "guess_colleague"
    content: dict       # готовый текст/данные для карточки (см. примеры выше)


class MessagePayload(BaseModel):
    """Что уходит в отправку. card — готовый Cards V2-контент."""
    text: str
    card: dict | None = None