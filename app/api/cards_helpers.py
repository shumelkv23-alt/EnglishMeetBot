# app/api/cards_helpers.py
"""Низкоуровневые хелперы карточек и webhook-ответов (add-on формат Google Chat).

Общие для диспатча (google_chat.py) и обработчиков игр (games.py): формат
ответа, нормализация параметров клика, определение DM-пространства,
обновление карточки на месте.
"""
from fastapi.responses import JSONResponse


def _normalize_params(raw) -> dict[str, str]:
    """parameters из события в плоский {key: value} (понимает list[{key,value}] и dict)."""
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items() if k and k != "__action_method_name__"}
    if isinstance(raw, list):
        return {str(p.get("key")): str(p.get("value")) for p in raw if isinstance(p, dict) and p.get("key")}
    return {}

def _params_dict(common: dict) -> dict:
    """Параметры клика как dict (список [{key,value}] → {key: value})."""
    params = common.get("parameters") or {}
    if isinstance(params, list):
        return {p.get("key"): p.get("value") for p in params if isinstance(p, dict)}
    return params if isinstance(params, dict) else {}

def _space_is_dm(space: dict) -> bool:
    """True, если пространство — личная переписка (DM) с ботом, а не группа/комната.

    chat_space_id в профиле семантически хранит ТОЛЬКО DM-пространство,
    поэтому имя группы туда писать нельзя (группа хранится в config["space_id"]).
    """
    if not isinstance(space, dict):
        return False
    return space.get("type") == "DM" or space.get("spaceType") in ("DM", "DIRECT_MESSAGE")


def _extract_space_dict(chat_data: dict) -> dict:
    """Пространство события как dict (для _space_is_dm) или {}, если не найдено."""
    for candidate in (
        chat_data.get("space", {}),
        chat_data.get("buttonClickedPayload", {}).get("space", {}),
        chat_data.get("messagePayload", {}).get("space", {}),
    ):
        if isinstance(candidate, dict) and isinstance(candidate.get("name"), str):
            return candidate
    return {}


def _dm_space_name(space: dict) -> str | None:
    """Имя пространства, если это DM; иначе None (группу в chat_space_id не пишем)."""
    if _space_is_dm(space):
        name = space.get("name")
        if isinstance(name, str) and name.startswith("spaces/"):
            return name
    return None

def _prepend_notice_to_card(cards_v2: list[dict], notice: str) -> list[dict]:
    """Вставить короткое подтверждение первой строкой первого textParagraph карточки.

    У Google Chat add-on для `updateMessageAction` нет отдельного toast:
    поле `actionStatus` на верхнем уровне ответа Chat не принимает и валит карточку
    целиком (красная «unable to process»), поэтому «✅ …» / «✨ … bonus word!»
    показываем прямо в теле карточки. При следующем ходе карточка перестраивается
    из состояния, и строка исчезает — как и положено разовому подтверждению.
    """
    notice = (notice or "").strip()
    if not notice:
        return cards_v2
    for card_obj in cards_v2:
        card = card_obj.get("card", {})
        for section in card.get("sections", []):
            for widget in section.get("widgets", []):
                tp = widget.get("textParagraph")
                if isinstance(tp, dict) and tp.get("text") is not None:
                    tp["text"] = f"**{notice}**\n\n" + tp["text"]
                    return cards_v2
    return cards_v2

def _cards_v2_list(cards_v2) -> list[dict]:
    """Нормализовать `cardsV2` до списка карточек.

    `build_*_card` возвращает `{"cardsV2": [...]}`, но часть ходов оборачивает его
    повторно: `{"text": …, "cardsV2": build_card(…)}` → получается вложенный
    `{"cardsV2": {"cardsV2": [...]}}`. Здесь достаём настоящий список; если пришёл
    уже список (start/reveal/millionaire и т.п.) — возвращаем как есть.
    """
    if isinstance(cards_v2, dict) and "cardsV2" in cards_v2:
        return cards_v2["cardsV2"]
    return cards_v2

def _hangman_update(result: dict) -> JSONResponse:
    """Ответ на ход ДМ-игры: карточка (cardsV2) → обновить на месте, иначе текст.

    В `updateMessageAction` шлём ТОЛЬКО `cardsV2` (без `text` и без `actionStatus`):
    add-on не принимает сообщение с одновременно `text`+`cardsV2` и не знает поле
    `actionStatus` — из-за этого карточка не обновлялась по ходу игры. Короткое
    подтверждение результата вшиваем первой строкой в саму карточку.
    """
    if not result:
        return JSONResponse(content={})
    if result.get("cardsV2"):
        cards = _prepend_notice_to_card(
            _cards_v2_list(result["cardsV2"]), result.get("text", "")
        )
        return _addon_update_response(cards)
    return _addon_response({"text": result.get("text", "Done")})

def _action_method(action: dict) -> str:
    """Имя действия из параметров клика (add-on: [{"key": "method", "value": ...}])."""
    for param in action.get("parameters") or []:
        if isinstance(param, dict) and param.get("key") == "method":
            return str(param.get("value", ""))
    return ""

def _reply_text(user_name: str, raw_text: str) -> str:
    """Текст ответа на MESSAGE: приветствие или echo."""
    if any(g in raw_text.lower() for g in ("hi", "hello")):
        return (
            f"Hi {user_name}! 👋\n\n"
            "I'm still learning, but soon we'll start "
            "organizing awesome English meetups!"
        )
    return (
        f'Got it, you wrote: "{raw_text}"\n\n'
        "I don't know what to do with that yet, but I'll learn soon!"
    )

def _addon_response(message: dict) -> JSONResponse:
    """Ответ в формате Google Workspace Add-on (CreateMessageAction).

    Для Chat-приложений, получающих события с обёрткой "chat" (messagePayload и т.п.),
    ответ обязан быть обёрнут в hostAppDataAction.chatDataAction.createMessageAction.
    """
    return JSONResponse(
        content={
            "hostAppDataAction": {
                "chatDataAction": {
                    "createMessageAction": {"message": message}
                }
            }
        }
    )

def _addon_update_message(message_name: str, card: dict) -> JSONResponse:
    """Ответ updateMessageAction: обновить карточку на месте (add-on формат)."""
    return JSONResponse(content={
        "hostAppDataAction": {
            "chatDataAction": {
                "updateMessageAction": {
                    "message": {
                        "name": message_name,
                        "cardsV2": card.get("cardsV2"),
                    }
                }
            }
        }
    })

def _addon_update_response(cards_v2: list[dict] | None = None, text: str = "") -> JSONResponse:
    """Обновить сообщение/карточку, на которой нажали кнопку (updateMessageAction без name).

    Для корректной замены карточки у неё должен быть тот же cardId, что и у
    карточки с нажатой кнопкой (Google сам понимает, какое сообщение обновлять).
    """
    message: dict = {}
    if text:
        message["text"] = text
    if cards_v2:
        message["cardsV2"] = cards_v2
    return JSONResponse(
        content={
            "hostAppDataAction": {
                "chatDataAction": {
                    "updateMessageAction": {"message": message}
                }
            }
        }
    )

