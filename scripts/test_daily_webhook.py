# scripts/test_daily_webhook.py
"""POST клик по новой карточке на локальный вебхук (add-on формат).

Действия (первый аргумент):
  yes         — «Да, приду» (submit_attendance_yes) -> придёт карточка времени
  no          — «Нет, не смогу» (submit_attendance_no)
  time        — «Записаться» (submit_time); слот — второй аргумент,
                например 2026-08-21T1500
  checkin_yes — чек-ин «Да, был(а)»
  checkin_no  — чек-ин «Нет»

Запуск: uvicorn должен быть поднят (SKIP_JWT_VALIDATION=true).
"""
import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BASE = "http://localhost:8000/webhooks/google-chat"

ACTION = sys.argv[1] if len(sys.argv) > 1 else "yes"
USER_ID = sys.argv[2] if len(sys.argv) > 2 else "users/test"
SLOT = sys.argv[3] if len(sys.argv) > 3 else "2026-08-21T1500"

METHODS = {
    "yes": "submit_attendance_yes",
    "no": "submit_attendance_no",
    "time": "submit_time",
    "checkin_yes": "submit_checkin_yes",
    "checkin_no": "submit_checkin_no",
}
method = METHODS.get(ACTION, ACTION)

form_inputs = {}
if ACTION == "time":
    form_inputs = {
        "time": {"": {"stringInputs": {"value": [SLOT]}}},
    }

event = {
    "commonEventObject": {
        "userLocale": "ru",
        "timeZone": {"id": "utc"},
        "parameters": {"method": method},
        "formInputs": form_inputs,
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
