# scripts/test_click_webhook.py
"""Полный тест клика по кнопке карточки через ASGI: вебхук -> парсинг -> БД.

Проверяет оба реальных формата клика:
  1. Workspace Add-on: chat.buttonClickedPayload + commonEventObject.formInputs
  2. Классический Chat App: type=CARD_CLICKED + action.function=URL + parameters

Запуск (JWT отключён через env):
  $env:SKIP_JWT_VALIDATION="true"; venv/Scripts/python.exe scripts/test_click_webhook.py
"""  # noqa: D205
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.main import app
from app.models import Answer, Profile
from app.services.onboarding_answers import QUESTIONS

FORM_INPUTS = {
    "q1": {"stringInputs": {"value": ["it"]}},
    "q1_other": {"stringInputs": {"value": ["космос"]}},
    "q2": {"stringInputs": {"value": ["chill"]}},
    "q3": {"stringInputs": {"value": ["нейросети"]}},
    "q4": {"stringInputs": {"value": ["mon"]}},
    "q5": {"stringInputs": {"value": ["busy"]}},
    "q6": {"stringInputs": {"value": ["named"]}},
    "q7": {"stringInputs": {"value": ["soft"]}},
}

BUTTON_URL = "https://renewed-ditto-knee.ngrok-free.dev/webhooks/google-chat"


def _build_addon_click() -> tuple[str, dict]:
    """Реальный add-on клик: chat.buttonClickedPayload + commonEventObject."""
    user_id = "users/test_click_addon"
    return user_id, {
        "commonEventObject": {
            "formInputs": FORM_INPUTS,
            "parameters": {"method": "submit_onboarding"},
        },
        "chat": {
            "user": {
                "name": user_id,
                "displayName": "Тест Клик",
                "email": "test-click-addon@example.com",
            },
            "buttonClickedPayload": {
                "space": {"name": "spaces/test_click_addon", "type": "DM"},
            },
        },
    }


def _build_classic_click() -> tuple[str, dict]:
    """Классический CARD_CLICKED с URL-функцией (как в add-on кнопке)."""
    user_id = "users/test_click_classic"
    return user_id, {
        "type": "CARD_CLICKED",
        "user": {
            "name": user_id,
            "displayName": "Тест Клик",
            "email": "test-click-classic@example.com",
        },
        "space": {"name": "spaces/test_click_classic", "type": "DM"},
        "action": {
            "function": BUTTON_URL,
            "parameters": [{"key": "method", "value": "submit_onboarding"}],
        },
        "common": {"formInputs": FORM_INPUTS},
    }


async def _send_click(event: dict) -> tuple[int, dict]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/webhooks/google-chat",
            json=event,
        )
        try:
            body = resp.json()
        except json.JSONDecodeError:
            body = {}
        return resp.status_code, body


async def _check_db(user_id: str, label: str, expected: int = 7, cleanup: bool = True) -> None:
    async with AsyncSessionLocal() as db:
        profile = (
            await db.execute(select(Profile).where(Profile.workspace_user_id == user_id))
        ).scalar_one_or_none()
        assert profile is not None, f"Профиль не создан ({label})"
        answers = (
            await db.execute(select(Answer).where(Answer.profile_id == profile.id))
        ).scalars().all()
        assert len(answers) == expected, f"{label}: ожидалось {expected} ответов, в БД {len(answers)}"
        questions = {a.question_text for a in answers}
        for q in QUESTIONS.values():
            assert q in questions, f"{label}: не найден ответ: {q}"
        print(f"[OK] {label}: профиль {profile.workspace_user_id}, ответов {len(answers)}")

        # Чистим тестовые данные
        if not cleanup:
            return
        for a in answers:
            await db.delete(a)
        await db.delete(profile)
        await db.commit()


async def main() -> None:
    # 1. Add-on клик: профиль оставляем в БД для проверки повтора ниже
    user_id, event = _build_addon_click()
    status, body = await _send_click(event)
    assert status == 200, f"Статус {status} для addon-клика"
    assert "hostAppDataAction" in body, "Нет hostAppDataAction"
    assert "Спасибо, анкета сохранена!" in body["hostAppDataAction"]["chatDataAction"]["createMessageAction"]["message"]["text"]
    print(f"[OK] addon buttonClickedPayload status={status}")
    await _check_db(user_id, "addon buttonClickedPayload", expected=7, cleanup=False)

    # 2. Повторный клик на уже прошедшем онбординг профиле:
    # history должна расти (7 -> 14), а не откатываться незкоммиченной транзакцией
    status, body = await _send_click(event)
    assert status == 200, f"Статус {status} для повторного клика"
    await _check_db(user_id, "repeat addon -> history растёт", expected=14)

    # 3. Классический CARD_CLICKED url+params
    user_id, event = _build_classic_click()
    status, body = await _send_click(event)
    assert status == 200, f"Статус {status} для classic-клика"
    assert body.get("text", "").startswith("Спасибо"), f"Нет текста спасибо: {body!r}"
    print(f"[OK] classic CARD_CLICKED url+params status={status}")
    await _check_db(user_id, "classic CARD_CLICKED url+params", expected=7)

    print("[OK] Тестовые данные удалены")


if __name__ == "__main__":
    asyncio.run(main())
    print("\nВСЁ ОК")