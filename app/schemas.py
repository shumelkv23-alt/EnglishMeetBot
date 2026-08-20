# app/schemas.py
from pydantic import BaseModel
from typing import Optional, Dict, Any, List

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