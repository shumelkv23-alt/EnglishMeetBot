# scripts/test_card_via_api.py
"""Отправить интерактивную карточку анкеты через Chat REST API (messages.create).

Если Google отклонит карточку — в ответе будет текст ошибки валидации с деталями.
Запуск: python scripts/test_card_via_api.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import service_account

from app.api.google_chat import _onboarding_card
from app.config import get_settings

settings = get_settings()
creds = service_account.Credentials.from_service_account_file(
    settings.google_sa_key_file, scopes=["https://www.googleapis.com/auth/chat.bot"]
)
creds.refresh(GoogleRequest())

space = settings.chat_test_space
card = _onboarding_card("Тест REST")

resp = requests.post(
    f"https://chat.googleapis.com/v1/{space}/messages",
    headers={"Authorization": f"Bearer {creds.token}"},
    json={
        "text": "Тест карточки анкеты через REST API (см. следующее сообщение):",
        "cardsV2": card["cardsV2"],
    },
    timeout=15,
)
print("STATUS:", resp.status_code)
if 200 <= resp.status_code < 300:
    print("OK, message name:", resp.json().get("name"))
else:
    print("ERROR BODY:")
    print(resp.text)