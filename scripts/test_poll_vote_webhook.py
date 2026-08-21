# scripts/test_poll_vote_webhook.py
"""POST CARD_CLICKED submit_poll_vote на локальный вебхук (add-on формат).

Имитирует клик «Забронировать день» по карточке опроса.
Запуск: uvicorn должен быть поднят (SKIP_JWT_VALIDATION=true).
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BASE = "http://localhost:8000/webhooks/google-chat"

USER_ID = sys.argv[1] if len(sys.argv) > 1 else "users/test"
# Дни через запятую или по умолчанию послезавтра и +3 дня
DAYS = (
    [date.today() + timedelta(days=d) for d in (2, 4)]
    if len(sys.argv) < 3
    else [date.fromisoformat(x) for x in sys.argv[2].split(",")]
)

event = {
    "commonEventObject": {
        "userLocale": "ru",
        "timeZone": {"id": "utc"},
        "parameters": {"method": "submit_poll_vote"},
        "formInputs": {
            "days": {
                "": {
                    "stringInputs": {
                        "value": [d.isoformat() for d in DAYS],
                    }
                }
            },
            "q_theme1": {"": {"stringInputs": {"value": ["нейросети и ИИ"]}}},
            "q_theme2": {"": {"stringInputs": {"value": ["сериалы"]}}},
        },
    },
    "chat": {
        "user": {
            "name": USER_ID,
            "displayName": "Test User",
            "email": f"{USER_ID.split('/')[-1]}@test.local",
        },
        "buttonClickedPayload": {
            "space": {"name": "spaces/testSpace", "type": "DM"},
        },
    },
}

resp = requests.post(BASE, json=event, timeout=15)
print("status:", resp.status_code)
print(json.dumps(resp.json(), ensure_ascii=False, indent=2))
