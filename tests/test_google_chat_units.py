# tests/test_google_chat_units.py
from app.api.google_chat import _addon_update_message


def test_addon_update_message_structure():
    card = {"cardsV2": [{"cardId": "dailyPoll", "card": {}}]}
    resp = _addon_update_message("spaces/A/messages/B", card)
    body = resp.body  # JSONResponse.body — bytes
    import json
    data = json.loads(body)
    assert data == {
        "hostAppDataAction": {
            "chatDataAction": {
                "updateMessageAction": {
                    "message": {
                        "name": "spaces/A/messages/B",
                        "cardsV2": [{"cardId": "dailyPoll", "card": {}}],
                    }
                }
            }
        }
    }
