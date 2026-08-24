# app/api/google_chat.py
import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from google.auth.transport import requests as grequests
from google.oauth2 import id_token

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.services.onboarding import (
    ONBOARDING_QUESTION,
    get_or_create_profile,
    save_answer,
)
from app.services.onboarding_answers import save_onboarding_answers

router = APIRouter(prefix="/webhooks", tags=["Google Chat"])
logger = logging.getLogger(__name__)
settings = get_settings()

_google_request = grequests.Request()


def _verify_chat_jwt(authorization: str) -> None:
    """Проверка JWT из заголовка Authorization (Bearer <jwt>).

    Audience = значение поля "Authentication audience" из Chat App Configuration
    (у нас это URL endpoint'а).
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = authorization[len("Bearer "):]
    id_token.verify_oauth2_token(
        token,
        _google_request,
        audience=settings.chat_app_audience,
    )


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


def _points_word(n: int) -> str:
    """Русская плюрализация: 1 балл, 2 балла, 5 баллов."""
    if n % 100 in (11, 12, 13, 14):
        return "баллов"
    last = n % 10
    if last == 1:
        return "балл"
    if last in (2, 3, 4):
        return "балла"
    return "баллов"


def _is_leaderboard_command(raw_text: str) -> bool:
    """Пользователь просит показать лидерборд."""
    lowered = raw_text.lower().strip(" .!?")
    return any(lowered == t or lowered.startswith(t + " ") for t in (
        "топ", "лидерборд", "рейтинг", "top", "leaderboard",
    ))


def _is_weekly_questions_command(raw_text: str) -> bool:
    """Пользователь просит сгенерировать вопросы недели (для ручного теста)."""
    lowered = raw_text.lower().strip(" .!?")
    return any(lowered == t or lowered.startswith(t + " ") for t in (
        "вопросы", "вопрос", "вопросы недели", "questions",
    ))


def _is_alias_command(raw_text: str) -> bool:
    """Пользователь хочет запустить игру Alias."""
    lowered = raw_text.lower().strip(" .!?")
    return any(lowered == t or lowered.startswith(t + " ") for t in (
        "алиас", "alias", "элиас",
    ))


def _is_snake_command(raw_text: str) -> bool:
    """Пользователь хочет запустить игру Snake Oil / «Змеиное масло»."""
    lowered = raw_text.lower().strip(" .!?")
    return any(lowered == t or lowered.startswith(t + " ") for t in (
        "снейк", "snake", "змейка", "змеиное", "snakeoil",
    ))


def _is_games_command(raw_text: str) -> bool:
    """Пользователь просит меню выбора игры."""
    lowered = raw_text.lower().strip(" .!?")
    return any(lowered == t or lowered.startswith(t + " ") for t in (
        "игры", "играть", "игра", "games", "game",
    ))


def _game_command(raw_text: str) -> str | None:
    """Команда запуска игры из текста сообщения («кто я» / Quiplash)."""
    lowered = raw_text.lower().strip()
    if any(k in lowered for k in ("кто я", "who am i", "угадай кто")):
        return "who_am_i"
    if any(k in lowered for k in ("quiplash", "квиплаш", "квиплэш")):
        return "quiplash"
    return None


def _params_dict(common: dict) -> dict:
    """Параметры клика как dict (список [{key,value}] → {key: value})."""
    params = common.get("parameters") or {}
    if isinstance(params, list):
        return {p.get("key"): p.get("value") for p in params if isinstance(p, dict)}
    return params if isinstance(params, dict) else {}


async def _weekly_questions_response(chat_data: dict) -> JSONResponse:
    """Сгенерировать и вернуть карточку «Вопросы недели» (команда «вопросы»)."""
    from app.services.weekly_questions import build_weekly_questions_card, weekly_questions_for

    user = chat_data.get("user", {})
    workspace_user_id = user.get("name", "")
    if not workspace_user_id:
        return _addon_response({"text": "Не удалось определить тебя 😕"})
    try:
        space = _extract_space_dict(chat_data)
        async with AsyncSessionLocal() as db:
            profile = await get_or_create_profile(
                db, workspace_user_id=workspace_user_id,
                email=user.get("email"), display_name=user.get("displayName"),
                chat_space_id=_dm_space_name(space),
            )
            questions = await weekly_questions_for(db, profile)
        card = build_weekly_questions_card(questions, settings.chat_app_audience)
        return _addon_response({"cardsV2": card["cardsV2"]})
    except Exception:
        logger.exception("weekly_questions_cmd_failed")
        return _addon_response({"text": "Не получилось сгенерировать вопросы 🤒"})


async def _leaderboard_text() -> str:
    """Текст топ-N лидерборда по сумме баллов."""
    from app.services.leaderboard import get_leaderboard

    try:
        async with AsyncSessionLocal() as db:
            rows = await get_leaderboard(db, top_n=10)
    except Exception:
        logger.exception("leaderboard_failed")
        return "Не получилось показать лидерборд 🤒"
    if not rows:
        return "Пока никто не набрал баллы — отметься на встрече, чтобы попасть в топ! 🏆"
    lines = [
        f"{i}. {r['name'] or '—'} — {r['points']} {_points_word(r['points'])}"
        for i, r in enumerate(rows, 1)
    ]
    return "🏆 Лидерборд:\n" + "\n".join(lines)


async def _handle_checkin_present(chat_data: dict, common: dict) -> dict:
    """Кнопка «Я на встрече»: запись self-check-in, если в окне (REQ-9.6)."""
    params = common.get("parameters") or {}
    if isinstance(params, list):
        params = {p.get("key"): p.get("value") for p in params if isinstance(p, dict)}
    instance_id = str(params.get("instance", ""))
    user = chat_data.get("user", {})
    workspace_user_id = user.get("name", "")
    result = {"ok": False, "within": False, "points": 0}
    if workspace_user_id and instance_id.isdigit():
        try:
            from app.services.checkin import submit_checkin

            async with AsyncSessionLocal() as db:
                profile = await get_or_create_profile(db, workspace_user_id=workspace_user_id)
                result = await submit_checkin(db, profile, int(instance_id))
        except Exception:
            logger.exception("checkin_submit_failed")
    points = result.get("points", 0)
    text = (
        f"Ты на встрече! +{points} {_points_word(points)} 🎉"
        if result.get("within") else "Кнопка вне окна встречи — отметка не засчитана ⏳"
    )
    return {"text": text}


def _alias_response(result: dict) -> JSONResponse:
    """Ответ на действие Alias: silent → пусто, cards_v2 → обновить карточку, иначе текст."""
    if result.get("silent"):
        return JSONResponse(content={})
    if result.get("cards_v2"):
        return _addon_update_response(result["cards_v2"], text=result.get("text", ""))
    return _addon_response({"text": result.get("text", "Готово")})


async def _handle_alias_action(chat_data: dict, common: dict, method: str) -> JSONResponse:
    """Обработать клик по кнопке игры Alias (join/start/guess/skip/last/adjust/confirm/finish)."""
    params = _params_dict(common)
    user = chat_data.get("user", {})
    workspace_user_id = user.get("name", "")
    try:
        async with AsyncSessionLocal() as db:
            from app.services import alias_game

            if method == "alias_join":
                if not workspace_user_id:
                    return _addon_response({"text": "Не удалось определить тебя 😕"})
                profile = await get_or_create_profile(db, workspace_user_id=workspace_user_id)
                result = await alias_game.join_team(
                    db, profile,
                    int(params.get("game_id", 0) or 0),
                    int(params.get("team_id", 0) or 0),
                )
                return _alias_response(result)
            if method == "alias_start":
                result = await alias_game.start_game(db, int(params.get("game_id", 0) or 0))
                return _alias_response(result)
            if method == "alias_guess":
                result = await alias_game.guess_word(db, int(params.get("round_id", 0) or 0))
                return _alias_response(result)
            if method == "alias_skip":
                result = await alias_game.skip_word(db, int(params.get("round_id", 0) or 0))
                return _alias_response(result)
            if method == "alias_last":
                result = await alias_game.last_word(
                    db,
                    int(params.get("round_id", 0) or 0),
                    int(params.get("team_id", 0) or 0),
                )
                return _alias_response(result)
            if method == "alias_adjust":
                result = await alias_game.adjust_points(
                    db,
                    int(params.get("round_id", 0) or 0),
                    int(params.get("delta", 0) or 0),
                )
                return _alias_response(result)
            if method == "alias_confirm":
                result = await alias_game.confirm_round(db, int(params.get("round_id", 0) or 0))
                return _alias_response(result)
            if method == "alias_finish":
                result = await alias_game.finish_game(db, int(params.get("game_id", 0) or 0))
                return _alias_response(result)
    except Exception:
        logger.exception("alias_action_failed method=%s", method)
        return _addon_response({"text": "Не получилось выполнить действие 🤒"})
    logger.info("event=BUTTON_CLICKED alias_unknown method=%r", method)
    return JSONResponse(content={})


async def _alias_command_response(chat_data: dict, raw_text: str = "") -> JSONResponse:
    """Команда «алиас»: создать игру и карточку в группе (проактивно)."""
    space = _extract_space_dict(chat_data)
    space_name = space.get("name", "")
    if not space_name or not space_name.startswith("spaces/"):
        return _addon_response({"text": "Не удалось определить пространство 🤷"})
    if _space_is_dm(space):
        return _addon_response({"text": "Alias лучше запускать в группе с командой 🙂"})
    try:
        async with AsyncSessionLocal() as db:
            from app.services import alias_game

            if alias_game.is_test_command(raw_text):
                user = chat_data.get("user", {})
                workspace_user_id = user.get("name", "")
                if not workspace_user_id:
                    return _addon_response({"text": "Не удалось определить тебя 😕"})
                profile = await get_or_create_profile(
                    db, workspace_user_id=workspace_user_id,
                    email=user.get("email"), display_name=user.get("displayName"),
                )
                result = await alias_game.setup_test_game(
                    db, space_name, profile, alias_game.test_target(raw_text),
                )
            else:
                result = await alias_game.game_from_command(db, space_name, raw_text)
    except Exception:
        logger.exception("alias_setup_failed")
        return _addon_response({"text": "Не получилось создать игру 🤒"})
    return _alias_response(result)


def _snake_response(result: dict) -> JSONResponse:
    """Ответ на действие Snake Oil: silent → пусто, cards_v2 → обновить, иначе текст."""
    if result.get("silent"):
        return JSONResponse(content={})
    if result.get("cards_v2"):
        return _addon_update_response(result["cards_v2"], text=result.get("text", ""))
    return _addon_response({"text": result.get("text", "Готово")})


def _game_response(result: dict) -> JSONResponse:
    """Ответ на действие Quiplash: silent → пусто, cards_v2 → обновить карточку, иначе текст."""
    if not result:
        return JSONResponse(content={})
    if result.get("silent"):
        return JSONResponse(content={})
    if result.get("cards_v2"):
        return _addon_update_response(result["cards_v2"], text=result.get("text", ""))
    return _addon_response({"text": result.get("text", "Готово")})


async def _handle_snake_action(chat_data: dict, common: dict, method: str) -> JSONResponse:
    """Обработать клик по кнопке игры Snake Oil (join/start/vote/finish/solo_ready)."""
    params = _params_dict(common)
    user = chat_data.get("user", {})
    workspace_user_id = user.get("name", "")
    try:
        async with AsyncSessionLocal() as db:
            from app.services import snake_oil

            if method == "snake_join":
                if not workspace_user_id:
                    return _addon_response({"text": "Не удалось определить тебя 😕"})
                profile = await get_or_create_profile(db, workspace_user_id=workspace_user_id)
                result = await snake_oil.join_game(db, profile, int(params.get("game_id", 0) or 0))
                return _snake_response(result)
            if method == "snake_start":
                result = await snake_oil.start_game(db, int(params.get("game_id", 0) or 0))
                return _snake_response(result)
            if method == "snake_vote":
                if not workspace_user_id:
                    return _addon_response({"text": "Не удалось определить тебя 😕"})
                profile = await get_or_create_profile(db, workspace_user_id=workspace_user_id)
                result = await snake_oil.vote(
                    db,
                    int(params.get("round_id", 0) or 0),
                    int(params.get("offer_id", 0) or 0),
                    profile,
                )
                return _snake_response(result)
            if method == "snake_solo_ready":
                result = await snake_oil.solo_ready(db, int(params.get("round_id", 0) or 0))
                return _snake_response(result)
            if method == "snake_finish":
                result = await snake_oil.finish_game(db, int(params.get("game_id", 0) or 0))
                return _snake_response(result)
    except Exception:
        logger.exception("snake_action_failed method=%s", method)
        return _addon_response({"text": "Не получилось выполнить действие 🤒"})
    logger.info("event=BUTTON_CLICKED snake_unknown method=%r", method)
    return JSONResponse(content={})


async def _snake_command_response(chat_data: dict, raw_text: str = "") -> JSONResponse:
    """Команда «снейк»: создать игру и карточку в группе (проактивно)."""
    space = _extract_space_dict(chat_data)
    space_name = space.get("name", "")
    if not space_name or not space_name.startswith("spaces/"):
        return _addon_response({"text": "Не удалось определить пространство 🤷"})
    if _space_is_dm(space):
        return _addon_response({"text": "Змеиное масло лучше запускать в группе 🧪"})
    try:
        async with AsyncSessionLocal() as db:
            from app.services import snake_oil

            if snake_oil.is_test_command(raw_text):
                user = chat_data.get("user", {})
                workspace_user_id = user.get("name", "")
                if not workspace_user_id:
                    return _addon_response({"text": "Не удалось определить тебя 😕"})
                profile = await get_or_create_profile(
                    db, workspace_user_id=workspace_user_id,
                    email=user.get("email"), display_name=user.get("displayName"),
                )
                result = await snake_oil.setup_test_game(
                    db, space_name, profile, snake_oil.test_target(raw_text),
                )
            else:
                result = await snake_oil.game_from_command(db, space_name, raw_text)
    except Exception:
        logger.exception("snake_setup_failed")
        return _addon_response({"text": "Не получилось создать игру 🤒"})
    return _snake_response(result)


async def _space_human_members(space_name: str) -> list[str]:
    """Human-участники space (user_id вида 'users/...'). Пусто при ошибке."""
    if not space_name:
        return []
    try:
        from app.services.chat_sender import list_space_members

        memberships = await asyncio.to_thread(list_space_members, space_name)
    except Exception:
        logger.exception("list_space_members_failed space=%s", space_name)
        return []
    return [
        m["member"]["name"]
        for m in memberships
        if m.get("member", {}).get("type") == "HUMAN"
        and "users/" in m["member"].get("name", "")
    ]


async def _start_game_from_command(
    space_name: str, user: dict, raw_text: str
) -> dict | None:
    """Запустить игру по команде. None — это не команда игры."""
    cmd = _game_command(raw_text)
    if cmd is None:
        return None
    try:
        async with AsyncSessionLocal() as db:
            from app.services import games

            workspace_user_id = user.get("name", "")

            if cmd == "quiplash":
                if games.is_test_command(raw_text):
                    if not workspace_user_id:
                        return {"text": "Не удалось определить тебя 😕"}
                    profile = await get_or_create_profile(
                        db, workspace_user_id=workspace_user_id,
                        email=user.get("email"), display_name=user.get("displayName"),
                    )
                    return await games.setup_quiplash_test(db, space_name, profile)
                return await games.setup_quiplash(db, space_name)

            # «кто я»
            if games.is_test_command(raw_text):
                if not workspace_user_id:
                    return {"text": "Не удалось определить тебя 😕"}
                profile = await get_or_create_profile(
                    db, workspace_user_id=workspace_user_id,
                    email=user.get("email"), display_name=user.get("displayName"),
                )
                return await games.setup_who_am_i_test(db, space_name, profile)
            player_ids = await _space_human_members(space_name) or [workspace_user_id]
            return await games.start_who_am_i(db, space_name, player_ids)
    except Exception:
        logger.exception("game_start_failed")
        return {"text": "Не удалось запустить игру 🤕"}


async def _handle_game_message(
    space_name: str, user: dict, raw_text: str
) -> dict | None:
    """Обработать сообщение как ход игры. None — активной игры нет."""
    user_id = user.get("name", "")
    if not user_id:
        return None
    try:
        async with AsyncSessionLocal() as db:
            from app.services import games

            return await games.handle_message(db, space_name, user_id, raw_text)
    except Exception:
        logger.exception("game_message_failed")
        return {"text": "Ошибка при обработке хода игры 🤕"}


async def _handle_game_dm_message(user: dict, raw_text: str) -> dict | None:
    """Сообщение в личку во время игры (ответ Quiplash / «мой секрет»). None — нет игры."""
    user_id = user.get("name", "")
    if not user_id:
        return None
    try:
        async with AsyncSessionLocal() as db:
            from app.services import games

            return await games.handle_dm_message(db, user_id, raw_text)
    except Exception:
        logger.exception("game_dm_message_failed")
        return {"text": "Ошибка при обработке ответа 🤕"}


async def _handle_game_action(chat_data: dict, common: dict, method: str) -> JSONResponse:
    """Обработать клик по карточке Quiplash (join/start/answer/vote/finish)."""
    params = _params_dict(common)
    user = chat_data.get("user", {})
    workspace_user_id = user.get("name", "")
    form_inputs = common.get("formInputs", {}) or {}
    game_id = int(params.get("game_id", 0) or 0)
    if not game_id:
        return _game_response({"text": "Игра не найдена 🤷"})
    try:
        async with AsyncSessionLocal() as db:
            from app.services import games

            if method == "game_join":
                if not workspace_user_id:
                    return _game_response({"text": "Не удалось определить тебя 😕"})
                profile = await get_or_create_profile(
                    db, workspace_user_id=workspace_user_id,
                    email=user.get("email"), display_name=user.get("displayName"),
                )
                result = await games.join_quiplash(db, profile, game_id)
            else:
                result = await games.handle_card_action(
                    db, game_id, workspace_user_id, method, form_inputs, params,
                )
            return _game_response(result)
    except Exception:
        logger.exception("game_action_failed method=%s", method)
        return _game_response({"text": "Ошибка при обработке действия 🤕"})


def _games_menu_card(action_url: str) -> dict:
    """Карточка-меню выбора игры: по кнопке на игру (командный и соло-режим)."""

    def _btn(text: str, method: str) -> dict:
        return {
            "text": text,
            "onClick": {"action": {
                "function": action_url,
                "parameters": [{"key": "method", "value": method}],
            }},
        }

    return {"cardsV2": [{
        "cardId": "gamesMenu",
        "card": {
            "header": {"title": "Выбери игру 🎮", "subtitle": "Нажми кнопку — игра начнётся в группе"},
            "sections": [{"widgets": [{"buttonList": {"buttons": [
                _btn("🎲 Alias — команды", "menu_alias"),
                _btn("🎲 Alias — соло (против бота)", "menu_alias_test"),
                _btn("🧪 Змеиное масло — команды", "menu_snake"),
                _btn("🧪 Змеиное масло — соло (против бота)", "menu_snake_test"),
                _btn("🎮 Quiplash", "menu_quiplash"),
                _btn("🎮 Quiplash — соло (против бота)", "menu_quiplash_test"),
                _btn("🎭 Кто я?", "menu_who_am_i"),
                _btn("🎭 Кто я? — соло (против бота)", "menu_who_am_i_test"),
            ]}}]}],
        },
    }]}


def _alias_setup_card(action_url: str) -> dict:
    """Второй шаг меню: настройка Alias (цель + названия команд)."""

    def _btn(text: str, method: str) -> dict:
        return {
            "text": text,
            "onClick": {"action": {
                "function": action_url,
                "parameters": [{"key": "method", "value": method}],
            }},
        }

    return {"cardsV2": [{
        "cardId": "aliasSetup",
        "card": {
            "header": {"title": "Настройка Alias 🎲", "subtitle": "Пустое поле = значение по умолчанию"},
            "sections": [{"widgets": [
                {"textInput": {"name": "alias_target", "label": "Цель очков (по умолч. 15)"}},
                {"textInput": {
                    "name": "alias_teams",
                    "label": "Названия команд через пробел (по умолч. «Команда 1» «Команда 2»)",
                }},
                {"buttonList": {"buttons": [_btn("▶️ Создать игру", "menu_alias_create")]}},
            ]}],
        },
    }]}


def _alias_test_setup_card(action_url: str) -> dict:
    """Второй шаг меню: настройка соло-Alias (цель против бота)."""
    return {"cardsV2": [{
        "cardId": "aliasTestSetup",
        "card": {
            "header": {"title": "Alias — соло 🤖", "subtitle": "Ты против бота"},
            "sections": [{"widgets": [
                {"textInput": {"name": "alias_test_target", "label": "Цель очков (по умолч. 5)"}},
                {"buttonList": {"buttons": [{
                    "text": "▶️ Начать",
                    "onClick": {"action": {
                        "function": action_url,
                        "parameters": [{"key": "method", "value": "menu_alias_test_create"}],
                    }},
                }]}},
            ]}],
        },
    }]}


async def _games_command_response(chat_data: dict) -> JSONResponse:
    """Команда «игры»: показать меню выбора игры."""
    space = _extract_space_dict(chat_data)
    space_name = space.get("name", "")
    if not space_name or not space_name.startswith("spaces/"):
        return _addon_response({"text": "Не удалось определить пространство 🤷"})
    if _space_is_dm(space):
        return _addon_response({"text": "Игры лучше запускать в группе 🙂"})
    return _addon_response(_games_menu_card(settings.chat_app_audience))


async def _handle_games_menu_action(chat_data: dict, common: dict, method: str) -> JSONResponse:
    """Клик по кнопке меню игр: показать настройку или создать и запустить игру."""
    space = _extract_space_dict(chat_data)
    space_name = space.get("name", "")
    if not space_name or not space_name.startswith("spaces/"):
        return _addon_response({"text": "Не удалось определить пространство 🤷"})
    user = chat_data.get("user", {})
    workspace_user_id = user.get("name", "")
    action_url = settings.chat_app_audience

    # Второй шаг для Alias: вместо меню показываем форму настройки.
    if method == "menu_alias":
        return _addon_update_response(_alias_setup_card(action_url)["cardsV2"])
    if method == "menu_alias_test":
        return _addon_update_response(_alias_test_setup_card(action_url)["cardsV2"])

    try:
        async with AsyncSessionLocal() as db:
            from app.services import alias_game, snake_oil
            from app.services.form_parsing import parse_form_inputs

            # Snake Oil — запускается сразу (настроек нет).
            if method == "menu_snake":
                result = await snake_oil.game_from_command(db, space_name, "снейк")
                return _snake_response(result)
            if method == "menu_snake_test":
                if not workspace_user_id:
                    return _addon_response({"text": "Не удалось определить тебя 😕"})
                profile = await get_or_create_profile(
                    db, workspace_user_id=workspace_user_id,
                    email=user.get("email"), display_name=user.get("displayName"),
                )
                result = await snake_oil.setup_test_game(
                    db, space_name, profile, snake_oil.test_target("снейк тест"),
                )
                return _snake_response(result)

            # Quiplash создаётся в setup-режиме (игроки присоединяются кнопкой);
            # «Кто я?» — запускается сразу (участники = human-члены space).
            if method in ("menu_quiplash", "menu_quiplash_test", "menu_who_am_i", "menu_who_am_i_test"):
                from app.services import games

                if method == "menu_quiplash":
                    return _game_response(await games.setup_quiplash(db, space_name))
                if method == "menu_quiplash_test":
                    if not workspace_user_id:
                        return _addon_response({"text": "Не удалось определить тебя 😕"})
                    profile = await get_or_create_profile(
                        db, workspace_user_id=workspace_user_id,
                        email=user.get("email"), display_name=user.get("displayName"),
                    )
                    return _game_response(await games.setup_quiplash_test(db, space_name, profile))
                if method == "menu_who_am_i_test":
                    if not workspace_user_id:
                        return _addon_response({"text": "Не удалось определить тебя 😕"})
                    profile = await get_or_create_profile(
                        db, workspace_user_id=workspace_user_id,
                        email=user.get("email"), display_name=user.get("displayName"),
                    )
                    return _game_response(await games.setup_who_am_i_test(db, space_name, profile))

                player_ids = await _space_human_members(space_name)
                if not player_ids:
                    player_ids = [workspace_user_id] if workspace_user_id else []
                result = await games.start_who_am_i(db, space_name, player_ids)
                return _game_response(result)

            # Создание Alias по значениям из формы.
            if method in ("menu_alias_create", "menu_alias_test_create"):
                values = parse_form_inputs(common.get("formInputs", {}) or {})
                if method == "menu_alias_create":
                    target = (values.get("alias_target") or [""])[0].strip()
                    teams = (values.get("alias_teams") or [""])[0].strip()
                    parts = ["алиас"]
                    if target.isdigit():
                        parts.append(target)
                    if teams:
                        parts.extend(teams.split())
                    result = await alias_game.game_from_command(db, space_name, " ".join(parts))
                    if result.get("ok"):
                        return _addon_update_response(text="✅ Игра создана, смотри ниже 👇")
                    return _alias_response(result)

                # menu_alias_test_create
                if not workspace_user_id:
                    return _addon_response({"text": "Не удалось определить тебя 😕"})
                target = (values.get("alias_test_target") or [""])[0].strip()
                raw = "алиас тест" + (f" {target}" if target.isdigit() else "")
                profile = await get_or_create_profile(
                    db, workspace_user_id=workspace_user_id,
                    email=user.get("email"), display_name=user.get("displayName"),
                )
                result = await alias_game.setup_test_game(
                    db, space_name, profile, alias_game.test_target(raw),
                )
                if result.get("ok"):
                    return _addon_update_response(text="✅ Игра создана, смотри ниже 👇")
                return _alias_response(result)
    except Exception:
        logger.exception("games_menu_action_failed method=%s", method)
        return _addon_response({"text": "Не получилось запустить игру 🤒"})
    logger.info("event=BUTTON_CLICKED games_menu_unknown method=%r", method)
    return JSONResponse(content={})


async def _submit_weekly_poll(chat_data: dict, common: dict) -> dict:
    """Обработать сабмит карточки еженедельного опроса (add-on формат)."""
    form_inputs = common.get("formInputs", {}) or {}
    user = chat_data.get("user", {})
    workspace_user_id = user.get("name", "")
    result = {"ok": False, "reason": "no_user"}
    if workspace_user_id:
        try:
            space = _extract_space_dict(chat_data)
            async with AsyncSessionLocal() as db:
                profile = await get_or_create_profile(
                    db, workspace_user_id=workspace_user_id,
                    email=user.get("email"), display_name=user.get("displayName"),
                    chat_space_id=_dm_space_name(space),
                )
                from app.services.weekly_poll import submit_poll
                result = await submit_poll(db, profile, form_inputs)
        except Exception:
            logger.exception("weekly_poll_submit_failed")
            result = {"ok": False, "reason": "db_error"}
    if result.get("ok"):
        return {"text": "Спасибо! Ответы и голоса сохранены. 🤝"}
    if result.get("reason") == "closed":
        return {"text": "Опрос на эту неделю уже закрыт — встретимся на следующей! ⏳"}
    return {"text": "Не получилось сохранить ответы — заполни хотя бы что-нибудь и нажми «Отправить»."}


async def _updated_poll_card_response() -> JSONResponse:
    """Обновлённая карточка опроса с актуальными счётчиками голосов.

    Если активный опрос не найден (крайний случай) — тихий пустой ответ,
    чтобы не плодить сообщения.
    """
    from app.services.weekly_poll import (
        active_daily_poll,
        build_daily_poll_card_with_counts,
        today,
    )

    try:
        async with AsyncSessionLocal() as db:
            poll = await active_daily_poll(db, today())
            if poll is not None:
                card = await build_daily_poll_card_with_counts(db, poll, settings.chat_app_audience)
                return _addon_update_response(card.get("cardsV2"), text="Кто сегодня и во сколько? 🗓️")
    except Exception:
        logger.exception("poll_card_update_failed")
    return JSONResponse(content={})


async def _submit_daily_poll(chat_data: dict, common: dict) -> JSONResponse:
    """Обработать клик по кнопке ежедневного опроса (add-on и classic формат).

    Кнопки карточки шлют время в action.parameters, а не в formInputs —
    перекладываем его в formInputs, чтобы submit_poll нашёл слот по ключу "time".
    Успешный голос обновляет карточку на месте (счётчик), без «Спасибо, учёл!».
    """
    form_inputs = common.get("formInputs", {}) or {}
    params = common.get("parameters") or {}
    if isinstance(params, list):
        params = {p.get("key"): p.get("value") for p in params if isinstance(p, dict)}
    if not form_inputs and isinstance(params, dict) and params.get("time"):
        form_inputs = {"time": {"stringInputs": {"value": [str(params["time"])]}}}
    user = chat_data.get("user", {})
    workspace_user_id = user.get("name", "")
    result = {"ok": False, "reason": "no_user"}
    if workspace_user_id:
        try:
            space = _extract_space_dict(chat_data)
            async with AsyncSessionLocal() as db:
                profile = await get_or_create_profile(
                    db, workspace_user_id=workspace_user_id,
                    email=user.get("email"), display_name=user.get("displayName"),
                    chat_space_id=_dm_space_name(space),
                )
                from app.services.weekly_poll import submit_poll
                result = await submit_poll(db, profile, form_inputs)
        except Exception:
            logger.exception("daily_poll_submit_failed")
            result = {"ok": False, "reason": "db_error"}
    if result.get("ok"):
        return await _updated_poll_card_response()
    if result.get("reason") == "closed":
        return _addon_response({"text": "Голосование уже закрыто — итог объявлен."})
    return _addon_response({"text": "Не получилось сохранить — попробуй ещё раз."})


async def _submit_weekly_questions(chat_data: dict, common: dict) -> JSONResponse:
    """Обработать сабмит карточки «Вопросы недели»: сохранить ответы один раз.

    Считывает textInput-поля answer1/answer2 из formInputs, связывает их с
    последними заданными вопросами и сохраняет в answers. Повторный сабмит
    блокируется: карточка заменяется на «Ответ отправлен» (кнопки больше нет).
    """
    from app.services.form_parsing import parse_form_inputs
    from app.services.weekly_questions import (
        build_weekly_questions_card,
        has_answered_questions,
        latest_questions_for,
    )

    values = parse_form_inputs(common.get("formInputs", {}) or {})
    user = chat_data.get("user", {})
    workspace_user_id = user.get("name", "")
    if not workspace_user_id:
        return _addon_response({"text": "Не удалось определить тебя 😕"})

    try:
        space = _extract_space_dict(chat_data)
        async with AsyncSessionLocal() as db:
            profile = await get_or_create_profile(
                db, workspace_user_id=workspace_user_id,
                email=user.get("email"), display_name=user.get("displayName"),
                chat_space_id=_dm_space_name(space),
            )
            questions = await latest_questions_for(db, profile.id)
            if not questions:
                return _addon_response({"text": "Сейчас нет активных вопросов недели 😕"})

            if await has_answered_questions(db, profile.id, questions):
                card = build_weekly_questions_card(
                    questions, settings.chat_app_audience, answered=True
                )
                return _addon_update_response(
                    card["cardsV2"], text="Ты уже отвечал на этой неделе 🙌"
                )

            # answer1 → первый вопрос, answer2 → второй (по порядку в `questions`)
            answers: list[tuple[str, str]] = []
            for i, q in enumerate(questions, 1):
                vals = values.get(f"answer{i}", [])
                if vals:
                    answers.append((q, vals[0]))
            if not answers:
                return _addon_response(
                    {"text": "Заполни хотя бы один ответ, прежде чем нажать «Отправить» 🤔"}
                )

            for q, answer_text in answers:
                await save_answer(db, profile, q, answer_text)

            card = build_weekly_questions_card(
                questions, settings.chat_app_audience, answered=True
            )
            return _addon_update_response(
                card["cardsV2"], text="Спасибо за ответы! 🙌 Записал."
            )
    except Exception:
        logger.exception("weekly_questions_submit_failed")
        return _addon_response({"text": "Не получилось сохранить ответы 🤒"})


async def _submit_onboarding(user: dict, space: dict, form_inputs: dict) -> dict:
    """Сохранить анкету онбординга и вернуть текстовое сообщение для пользователя."""
    workspace_user_id = user.get("name", "")
    if not workspace_user_id or not form_inputs:
        return {
            "text": "Чтобы сохранить анкету, заполни хотя бы несколько полей и нажми «Отправить анкету»."
        }
    try:
        async with AsyncSessionLocal() as db:
            profile = await get_or_create_profile(
                db,
                workspace_user_id=workspace_user_id,
                email=user.get("email"),
                display_name=user.get("displayName"),
                chat_space_id=_dm_space_name(space),
            )
            answers = await save_onboarding_answers(db, profile, form_inputs)
            if not answers:
                return {"text": "Анкета пустая — заполни хотя бы один вопрос 🤔"}
    except Exception:
        logger.exception("onboarding_save_failed")
        return {"text": "Не удалось сохранить анкету. Попробуй ещё раз 🤞"}
    return {
        "text": "Спасибо, анкета сохранена! На основе ответов подберём темы и пару для следующей встречи 🔥"
    }


def _is_onboarding_command(raw_text: str) -> bool:
    """Пользователь явно просит показать анкету онбординга."""
    lowered = raw_text.lower().strip()
    return any(trigger in lowered for trigger in ("анкета", "start", "онбординг", "опрос", "anketa"))


def _onboarding_response_payload(user_name: str, space: dict) -> dict:
    """Карточка анкеты — только в личку; в группу — текст-подсказка без карточки.

    Явный запрос анкеты («анкета»/«start»/«опрос»…) в группе не должен уводить
    карточку в общий чат: в DM показываем саму анкету, иначе — просим написать
    боту в личку.
    """
    if _space_is_dm(space):
        return _onboarding_card(user_name)
    return {"text": "Напиши мне в личку, чтобы пройти анкету 🙌"}


def _action_method(action: dict) -> str:
    """Имя действия из параметров клика (add-on: [{"key": "method", "value": ...}])."""
    for param in action.get("parameters") or []:
        if isinstance(param, dict) and param.get("key") == "method":
            return str(param.get("value", ""))
    return ""


def _onboarding_action_method(common: dict) -> str:
    """Имя действия из commonEventObject.parameters (add-on клик по карточке).

    Наш метод приходит под ключом "method"; карточки ДО конверсии в add-on
    Google шлёт под служебным ключом "__action_method_name__".
    """
    params = common.get("parameters") or {}
    if isinstance(params, dict):
        method = params.get("method") or params.get("__action_method_name__") or ""
        return str(method).strip()
    return ""


def _onboarding_card(user_name: str) -> dict:
    """Интерактивная карточка онбординга: 7 вопросов + кнопка Отправить."""
    return {
        "cardsV2": [
            {
                "cardId": "onboardingForm",
                "card": {
                    "header": {
                        "title": f"Привет, {user_name}! Я EnglishMeetBot 🎉",
                        "subtitle": "Помогаю организовывать встречи по английскому",
                        "imageUrl": "https://fonts.gstatic.com/s/i/googlematerialicons/spark/v1/24px.svg",
                        "imageType": "CIRCLE",
                    },
                    "sections": [
                        {
                            "widgets": [
                                {
                                    "textParagraph": {
                                        "text": (
                                            "Чтобы встречи были интересными именно тебе, "
                                            "заполни небольшую анкету. Где есть варианты — "
                                            "можно выбрать из списка, написать свой вариант "
                                            "или и то, и другое."
                                        )
                                    }
                                }
                            ]
                        },
                        {
                            "header": "1. О чём ты можешь говорить часами без остановки?",
                            "widgets": [
                                {
                                    "selectionInput": {
                                        "name": "q1",
                                        "label": "Выбери 1–2",
                                        "type": "CHECK_BOX",
                                        "items": [
                                            {"text": "💻 IT, технологии и будущее", "value": "it", "selected": False},
                                            {"text": "🌍 Путешествия, страны и культурный шок", "value": "travel", "selected": False},
                                            {"text": "🎬 Кино, сериалы, книги и поп-культура", "value": "movies", "selected": False},
                                            {"text": "🎮 Видеоигры и виртуальные миры", "value": "games", "selected": False},
                                            {"text": "🧠 Психология, саморазвитие и лайфхаки", "value": "psychology", "selected": False},
                                            {"text": "💼 Работа, стартапы и карьерные треш-истории", "value": "work", "selected": False},
                                            {"text": "🎨 Искусство, музыка или творчество", "value": "art", "selected": False},
                                        ],
                                    }
                                },
                                {
                                    "textInput": {
                                        "name": "q1_other",
                                        "label": "Свой вариант",
                                    }
                                },
                            ],
                        },
                        {
                            "header": "2. Какой вайб встреч тебе ближе?",
                            "widgets": [
                                {
                                    "selectionInput": {
                                        "name": "q2",
                                        "label": "Выбери один",
                                        "type": "RADIO_BUTTON",
                                        "items": [
                                            {"text": "🧘‍♂️ Chill & Chat", "value": "chill", "selected": False},
                                            {"text": "🎭 Roleplay", "value": "roleplay", "selected": False},
                                            {"text": "🎲 Games & Quizzes", "value": "games", "selected": False},
                                            {"text": "⚡ Debate", "value": "debate", "selected": False},
                                        ],
                                    }
                                },
                                {
                                    "textInput": {
                                        "name": "q2_other",
                                        "label": "Свой вариант",
                                    }
                                },
                            ],
                        },
                        {
                            "header": "3. Назови ОДНУ тему, которую готов обсуждать прямо сейчас",
                            "widgets": [
                                {
                                    "textInput": {
                                        "name": "q3",
                                        "label": "Например: нейросети, путешествия в Японию, сериал «Дом Дракона»",
                                    }
                                }
                            ],
                        },
                        {
                            "header": "4. В какие дни тебе удобно выделить 30–40 минут?",
                            "widgets": [
                                {
                                    "selectionInput": {
                                        "name": "q4",
                                        "label": "Выбери удобные дни",
                                        "type": "CHECK_BOX",
                                        "items": [
                                            {"text": "Пн", "value": "mon", "selected": False},
                                            {"text": "Вт", "value": "tue", "selected": False},
                                            {"text": "Ср", "value": "wed", "selected": False},
                                            {"text": "Чт", "value": "thu", "selected": False},
                                            {"text": "Пт", "value": "fri", "selected": False},
                                            {"text": "Сб", "value": "sat", "selected": False},
                                            {"text": "Вс", "value": "sun", "selected": False},
                                        ],
                                    }
                                },
                                {
                                    "textInput": {
                                        "name": "q4_other",
                                        "label": "Уточнение (например, только вечером)",
                                    }
                                },
                            ],
                        },
                        {
                            "header": "5. Из-за чего ты обычно теряешь интерес или пропускаешь активности?",
                            "widgets": [
                                {
                                    "selectionInput": {
                                        "name": "q5",
                                        "label": "Выбери ближайшее",
                                        "type": "RADIO_BUTTON",
                                        "items": [
                                            {"text": "😴 Нет сил / усталость", "value": "tired", "selected": False},
                                            {"text": "🌪️ Закрутился в делах и забыл", "value": "busy", "selected": False},
                                            {"text": "🥱 Стало скучно / темы не зашли", "value": "boring", "selected": False},
                                            {"text": "🫥 Неловко или некомфортно", "value": "awkward", "selected": False},
                                        ],
                                    }
                                },
                                {
                                    "textInput": {
                                        "name": "q5_other",
                                        "label": "Свой вариант",
                                    }
                                },
                            ],
                        },
                        {
                            "header": "6. Разрешаешь ли использовать твои ответы?",
                            "widgets": [
                                {
                                    "selectionInput": {
                                        "name": "q6",
                                        "label": "Выбери один",
                                        "type": "RADIO_BUTTON",
                                        "items": [
                                            {"text": "✅ Да, конечно!", "value": "yes", "selected": False},
                                            {"text": "🔒 Только обезличенные данные", "value": "anonymous", "selected": False},
                                            {"text": "❌ Нет, пусть остаётся между нами", "value": "no", "selected": False},
                                        ],
                                    }
                                }
                            ],
                        },
                        {
                            "header": "7. В каком стиле тебе комфортнее общаться?",
                            "widgets": [
                                {
                                    "selectionInput": {
                                        "name": "q7",
                                        "label": "Выбери один",
                                        "type": "RADIO_BUTTON",
                                        "items": [
                                            {"text": "Строгий: исправляют ошибки, дают задания", "value": "strict", "selected": False},
                                            {"text": "Мягкий: болтаем свободно, без давления", "value": "soft", "selected": False},
                                        ],
                                    }
                                }
                            ],
                        },
                        {
                            "widgets": [
                                {
                                    "buttonList": {
                                        "buttons": [
                                            {
                                                "text": "Отправить анкету",
                                                "onClick": {
                                                    "action": {
                                                        "function": settings.chat_app_audience or "submit_onboarding",
                                                        "parameters": [
                                                            {"key": "method", "value": "submit_onboarding"}
                                                        ],
                                                    }
                                                },
                                            }
                                        ]
                                    }
                                }
                            ]
                        },
                    ],
                },
            }
        ]
    }


async def _register_contact(chat_data: dict, space_name: str) -> None:
    """Зарегистрировать профиль пользователя события (момент первого контакта).

    chat_space_id фиксирует ТОЛЬКО DM-пространство пользователя и нужен для
    проактивных DM-рассылок. При добавлении бота в группу имя группы в DM-поле
    не пишем — группа сохраняется отдельно в config["space_id"], а пользователь
    без лички уходит в план @упоминаний, а не в DM.
    """
    user = chat_data.get("user", {})
    workspace_user_id = user.get("name", "")
    if workspace_user_id:
        # Пространство события: в add-on формате лежит в addedToSpacePayload,
        # в классическом — на верхнем уровне (event["space"]).
        payload = chat_data.get("addedToSpacePayload")
        space = payload.get("space") if isinstance(payload, dict) else chat_data.get("space")
        dm_space = space_name if _space_is_dm(space) else None
        try:
            async with AsyncSessionLocal() as db:
                await get_or_create_profile(
                    db,
                    workspace_user_id=workspace_user_id,
                    email=user.get("email"),
                    display_name=user.get("displayName"),
                    chat_space_id=dm_space,
                )
        except Exception:
            logger.exception("db_write_failed")
    else:
        logger.warning("added_to_space_without_user_name, db write skipped")


async def _run_onboarding(space_name: str, space: dict) -> dict:
    """Онбординг при добавлении в пространство: анкета в личку, @упоминание в группу.

    space_id в config пишем ТОЛЬКО для группы/комнаты (не DM): джобы ежедневного
    опроса и итогов должны слать в группу, а не в личку. В DM space_id не трогаем.
    Через onboard_space_members планируем каналы:
      - plan["dm"] — уже есть DM с ботом и онбординг не пройден → анкета в личку;
      - plan["mention"] — нет DM → @упоминание в группу с просьбой написать боту.
    Возвращает план: {'dm': [...], 'mention': [...]}.
    """
    from app.messaging import send_message
    from app.schemas import MessagePayload
    from app.services.chat_sender import send_text
    from app.services.space_onboarding import onboard_space_members
    from app.services.weekly_poll import get_or_create_config

    plan: dict = {"dm": [], "mention": []}
    if not space_name:
        return plan
    try:
        async with AsyncSessionLocal() as db:
            # config["space_id"] — id ГРУППЫ для джоб; DM-пространство не фиксируем
            if not _space_is_dm(space):
                await get_or_create_config(db, "space_id", space_name)
            plan = await onboard_space_members(db, space_name)
    except Exception:
        # Сбой планирования не должен ронять обработку события
        logger.exception("onboarding_plan_failed space=%s", space_name)
        return plan

    # Анкета в личку тем, у кого уже есть DM с ботом
    for ws in plan["dm"]:
        try:
            send_message(
                ws,
                MessagePayload(
                    text="Привет! Заполни короткую анкету 🙌",
                    card=_onboarding_card("друг"),
                ),
            )
        except Exception:
            logger.exception("onboarding_dm_failed user=%s", ws)

    # Остальным — одно сообщение в группу с @упоминаниями
    if plan["mention"]:
        mentions = " ".join(f"<{m}>" for m in plan["mention"])
        try:
            send_text(
                space_name,
                f"{mentions} — напишите мне в личку, чтобы пройти анкету 👋",
            )
        except Exception:
            logger.exception("onboarding_mention_failed space=%s", space_name)

    logger.info(
        "onboarding_run space=%s dm=%d mention=%d",
        space_name, len(plan["dm"]), len(plan["mention"]),
    )
    return plan


def _reply_text(user_name: str, raw_text: str) -> str:
    """Текст ответа на MESSAGE: приветствие или echo."""
    if "привет" in raw_text.lower():
        return (
            f"Привет, {user_name}! 👋\n\n"
            "Я пока учусь, но скоро мы начнём "
            "организовывать крутые встречи по английскому!"
        )
    return (
        f'Я понял, ты написал: "{raw_text}"\n\n'
        "Пока я не знаю, что с этим делать, но скоро научусь!"
    )


async def _handle_free_text(user: dict, space: dict, raw_text: str, user_name: str) -> str:
    """Сохранить свободное сообщение и вернуть текст ответа бота.

    Если у пользователя есть недавние вопросы недели — считаем сообщение ответом
    на них и благодарим (вопрос связывается с этими вопросами); иначе — обычный echo.
    """
    from app.services.weekly_questions import latest_questions_for

    reply = _reply_text(user_name, raw_text)
    workspace_user_id = user.get("name", "")
    if not workspace_user_id:
        logger.warning("message_without_user_name, db write skipped")
        return reply
    try:
        async with AsyncSessionLocal() as db:
            profile = await get_or_create_profile(
                db,
                workspace_user_id=workspace_user_id,
                email=user.get("email"),
                display_name=user.get("displayName"),
                chat_space_id=_dm_space_name(space),
            )
            weekly_qs = await latest_questions_for(db, profile.id)
            if weekly_qs:
                await save_answer(db, profile, " | ".join(weekly_qs), raw_text)
                reply = "Спасибо за ответ! 🙌 Записал — обсудим на ближайшей встрече."
            else:
                await save_answer(db, profile, ONBOARDING_QUESTION, raw_text)
    except Exception:
        # Сбой БД не должен ломать ответ бота
        logger.exception("db_write_failed")
    return reply


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


def _addon_update_response(cards_v2: list[dict] | None = None, text: str = "") -> JSONResponse:
    """Обновить сообщение/карточку на месте (updateMessageAction) вместо нового сообщения.

    Для корректной замены карточки в сообщении у неё должен быть тот же cardId,
    что и у карточки с нажатой кнопкой (у опроса — "dailyPoll").
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


@router.post("/google-chat")
async def handle_google_chat_webhook(request: Request) -> JSONResponse:
    # 1. Аутентификация: Google подписывает каждый запрос JWT в заголовке Authorization
    if not settings.skip_jwt_validation:
        try:
            _verify_chat_jwt(request.headers.get("Authorization", ""))
        except HTTPException:
            raise
        except Exception as e:
            logger.warning("interaction_jwt_invalid error=%s", e)
            raise HTTPException(status_code=401, detail="Invalid JWT")

    # 2. Разбор события
    try:
        event = await request.json()
    except Exception:
        return JSONResponse(content={})

    # 3a. Формат Google Workspace Add-on: событие внутри ключа "chat"
    chat_data = event.get("chat")
    if isinstance(chat_data, dict):
        user_name = chat_data.get("user", {}).get("displayName", "друг")

        # Нажали кнопку на карточке (add-on формат: buttonClickedPayload)
        if "buttonClickedPayload" in chat_data:
            common = event.get("commonEventObject", {}) or {}
            method = _onboarding_action_method(common)
            if method == "submit_onboarding":
                form_inputs = common.get("formInputs", {}) or {}
                space = _extract_space_dict(chat_data)
                user = chat_data.get("user", {})
                response_msg = await _submit_onboarding(user, space, form_inputs)
                return _addon_response(response_msg)
            if method == "submit_weekly_poll":
                return _addon_response(await _submit_weekly_poll(chat_data, common))
            if method == "submit_weekly_questions":
                return await _submit_weekly_questions(chat_data, common)
            if method == "submit_daily_poll":
                return await _submit_daily_poll(chat_data, common)
            if method == "checkin_present":
                return _addon_response(await _handle_checkin_present(chat_data, common))
            if method in (
                "alias_join", "alias_start", "alias_guess", "alias_skip",
                "alias_last", "alias_adjust", "alias_confirm", "alias_finish",
            ):
                return await _handle_alias_action(chat_data, common, method)
            if method in (
                "snake_join", "snake_start", "snake_vote", "snake_finish", "snake_solo_ready",
            ):
                return await _handle_snake_action(chat_data, common, method)
            if method in (
                "menu_alias", "menu_alias_test", "menu_alias_create", "menu_alias_test_create",
                "menu_snake", "menu_snake_test", "menu_quiplash", "menu_quiplash_test",
                "menu_who_am_i", "menu_who_am_i_test",
            ):
                return await _handle_games_menu_action(chat_data, common, method)
            if method.startswith("game_") or method == "who_finish":
                return await _handle_game_action(chat_data, common, method)
            logger.info("event=BUTTON_CLICKED format=addon method=%r", method)
            return JSONResponse(content={})

        # Пользователь написал сообщение
        if "messagePayload" in chat_data:
            message = chat_data["messagePayload"].get("message", {})
            raw_text = (message.get("argumentText") or message.get("text") or "").strip()
            logger.info("event=MESSAGE format=addon user=%r text=%r", user_name, raw_text)
            if not raw_text:
                return JSONResponse(content={})

            # Команда «вопросы» — генерация вопросов недели (проверяем ДО онбординга:
            # «вопросы» содержит подстроку «опрос»)
            if _is_weekly_questions_command(raw_text):
                return await _weekly_questions_response(chat_data)

            # Явный запрос анкеты — карточка только в личку, в группу не шлём
            if _is_onboarding_command(raw_text):
                space = _extract_space_dict(chat_data)
                return _addon_response(_onboarding_response_payload(user_name, space))

            # Команда лидерборда
            if _is_leaderboard_command(raw_text):
                return _addon_response({"text": await _leaderboard_text()})

            # Меню выбора игры (одна команда вместо запоминания всех)
            if _is_games_command(raw_text):
                return await _games_command_response(chat_data)

            # Команда запуска игры Alias
            if _is_alias_command(raw_text):
                return await _alias_command_response(chat_data, raw_text)

            # Команда запуска игры Snake Oil / «Змеиное масло»
            if _is_snake_command(raw_text):
                return await _snake_command_response(chat_data, raw_text)

            # Запуск игры по команде («квиплаш», «кто я») и ход в активной игре
            space = _extract_space_dict(chat_data)
            space_name = space.get("name", "")
            user = chat_data.get("user", {})
            is_dm = _space_is_dm(space)

            if is_dm:
                # В личке игры не запускаем; обрабатываем ответ Quiplash / «мой секрет»
                dm_reply = await _handle_game_dm_message(user, raw_text)
                if dm_reply is not None:
                    return _addon_response(dm_reply) if dm_reply else JSONResponse(content={})
            else:
                game_start = await _start_game_from_command(space_name, user, raw_text)
                if game_start is not None:
                    return _game_response(game_start)

                game_reply = await _handle_game_message(space_name, user, raw_text)
                if game_reply is not None:
                    return _addon_response(game_reply) if game_reply else JSONResponse(content={})

            # Сохраняем профиль и ответ в БД (ответ на вопросы недели или echo)
            user = chat_data.get("user", {})
            space = _extract_space_dict(chat_data)
            reply_text = await _handle_free_text(user, space, raw_text, user_name)
            return _addon_response({"text": reply_text})

        # Бота добавили в пространство / открыли DM
        if "addedToSpacePayload" in chat_data:
            space = chat_data["addedToSpacePayload"].get("space", {})
            space_name = space.get("name", "")
            logger.info("event=ADDED_TO_SPACE format=addon user=%r space=%s", user_name, space_name)
            await _register_contact(chat_data, space_name)
            # Онбординг: анкета в личку / @упоминание в группу
            await _run_onboarding(space_name, space)
            return JSONResponse(content={})

        # Нажали кнопку на карточке (submit анкеты онбординга)
        action = chat_data.get("action", {})
        function_name = action.get("function") or action.get("functionName") or action.get("actionMethodName")
        if function_name == "submit_onboarding":
            form_inputs = chat_data.get("common", {}).get("formInputs", {})
            space = _extract_space_dict(chat_data)
            user = chat_data.get("user", {})
            response_msg = await _submit_onboarding(user, space, form_inputs)
            return _addon_response(response_msg)

        # Прочие события аддон-формата
        logger.info("event=unhandled format=addon chat_keys=%s", sorted(chat_data.keys()))
        return JSONResponse(content={})

    # 3b. Классический формат Chat App (interaction events): type/user/message/space наверху
    event_type = event.get("type")

    if event_type == "ADDED_TO_SPACE":
        user_name = event.get("user", {}).get("displayName", "")
        logger.info("event=ADDED_TO_SPACE format=classic user=%s", user_name)
        space = event.get("space", {})
        space_name = space.get("name", "")
        await _register_contact(event, space_name)
        # Онбординг: анкета в личку / @упоминание в группу
        await _run_onboarding(space_name, space)
        return JSONResponse(content={})

    if event_type == "MESSAGE":
        user_name = event.get("user", {}).get("displayName", "друг")
        message = event.get("message", {})
        raw_text = (message.get("text") or message.get("argumentText") or "").strip()
        logger.info("event=MESSAGE format=classic user=%s text=%r", user_name, raw_text)
        if not raw_text:
            return JSONResponse(content={})
        if _is_weekly_questions_command(raw_text):
            return await _weekly_questions_response(event)
        if _is_onboarding_command(raw_text):
            space = event.get("space", {})
            return JSONResponse(content=_onboarding_response_payload(user_name, space))
        if _is_leaderboard_command(raw_text):
            return JSONResponse(content={"text": await _leaderboard_text()})
        if _is_games_command(raw_text):
            return await _games_command_response(event)
        if _is_alias_command(raw_text):
            return await _alias_command_response(event, raw_text)
        if _is_snake_command(raw_text):
            return await _snake_command_response(event, raw_text)
        # Запуск игры по команде («квиплаш», «кто я») и ход в активной игре
        space = event.get("space", {})
        space_name = space.get("name", "")
        user = event.get("user", {})
        is_dm = _space_is_dm(space)

        if is_dm:
            dm_reply = await _handle_game_dm_message(user, raw_text)
            if dm_reply is not None:
                return JSONResponse(content=dm_reply) if dm_reply else JSONResponse(content={})
        else:
            game_start = await _start_game_from_command(space_name, user, raw_text)
            if game_start is not None:
                if game_start.get("silent"):
                    return JSONResponse(content={})
                return JSONResponse(content=game_start)
            game_reply = await _handle_game_message(space_name, user, raw_text)
            if game_reply is not None:
                return JSONResponse(content=game_reply) if game_reply else JSONResponse(content={})
        user = event.get("user", {})
        space = event.get("space", {})
        reply_text = await _handle_free_text(user, space, raw_text, user_name)
        return JSONResponse(content={"text": reply_text})

    if event_type == "CARD_CLICKED":
        action = event.get("action", {})
        function_name = (
            action.get("function")
            or action.get("functionName")
            or action.get("actionMethodName")
            or ""
        )
        method = _action_method(action)
        if function_name == "submit_onboarding" or method == "submit_onboarding":
            user = event.get("user", {})
            space = event.get("space", {})
            form_inputs = event.get("common", {}).get("formInputs", {})
            response_msg = await _submit_onboarding(user, space, form_inputs)
            return _addon_response(response_msg)
        if function_name == "weekly_poll_submit" or method == "submit_weekly_poll":
            user = event.get("user", {})
            space = event.get("space", {})
            form_inputs = event.get("common", {}).get("formInputs", {})
            response_msg = await _submit_weekly_poll(
                {"user": user, "space": space},
                {"formInputs": form_inputs},
            )
            return _addon_response(response_msg)
        if function_name == "submit_daily_poll" or method == "submit_daily_poll":
            user = event.get("user", {})
            space = event.get("space", {})
            params = {}
            for p in action.get("parameters") or []:
                if isinstance(p, dict) and p.get("key"):
                    params[p.get("key")] = p.get("value")
            form_inputs = event.get("common", {}).get("formInputs", {})
            return await _submit_daily_poll(
                {"user": user, "space": space},
                {"formInputs": form_inputs, "parameters": params},
            )
        if function_name == "submit_weekly_questions" or method == "submit_weekly_questions":
            user = event.get("user", {})
            space = event.get("space", {})
            form_inputs = event.get("common", {}).get("formInputs", {})
            return await _submit_weekly_questions(
                {"user": user, "space": space},
                {"formInputs": form_inputs},
            )
        if function_name == "checkin_submit" or method == "checkin_present":
            user = event.get("user", {})
            space_name = event.get("space", {}).get("name", "")
            params = action.get("parameters") or {}
            instance_id = ""
            for p in params:
                if isinstance(p, dict) and p.get("key") == "instance":
                    instance_id = p.get("value", "")
            response_msg = await _handle_checkin_present(
                {"user": user, "space": {"name": space_name}},
                {"parameters": {"instance": instance_id}},
            )
            return _addon_response(response_msg)
        if method.startswith("game_") or method == "who_finish":
            common = {
                "parameters": action.get("parameters") or [],
                "formInputs": event.get("common", {}).get("formInputs", {}),
            }
            return await _handle_game_action(event, common, method)
        logger.info("event=CARD_CLICKED format=classic function=%s method=%s", function_name, method)
        return JSONResponse(content={})

    # REMOVED_FROM_SPACE и неизвестные типы — тихо отвечаем пустым JSON
    logger.info("event=unhandled type=%r keys=%s", event_type, sorted(event.keys()))
    return JSONResponse(content={})
