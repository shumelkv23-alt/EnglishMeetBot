# app/api/google_chat.py
import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from google.auth.transport import requests as grequests
from google.oauth2 import id_token

from app.config import get_settings
from app.services.games.session import GameManager, build_join_card
from app.database import AsyncSessionLocal
from app.services.onboarding import (
    ONBOARDING_QUESTION,
    get_or_create_profile,
    save_answer,
)
from app.services.onboarding_answers import save_onboarding_answers
from app.services.levels import build_level_card, level_choice_items, levels_description, normalize_level

router = APIRouter(prefix="/webhooks", tags=["Google Chat"])
logger = logging.getLogger(__name__)
settings = get_settings()

GAME_COMMANDS = ("guesspionage", "spy")
GAME_TITLES = {"guesspionage": "Guesspionage English", "spy": "Spy"}
MIN_PLAYERS = {"guesspionage": 2, "spy": 3}


def _is_slash_command(raw_text: str) -> str | None:
    """Извлечь имя игры из текста вида '/spy' или '!spy'. Возвращает 'guesspionage'/'spy'/None.

    Google Chat перехватывает '/...' как нативную слэш-команду и не доставляет её как
    MESSAGE, поэтому реальный триггер в чате — '!' (слэш остаётся для тестов, которые
    шлют запросы напрямую в обход Google).
    """
    text = raw_text.strip().lower()
    for prefix in ("/", "!"):
        if text.startswith(prefix):
            name = text[1:].split()[0] if text[1:].strip() else ""
            if name in GAME_COMMANDS:
                return name
    return None


def _game_command_response(game: str, space_name: str) -> dict:
    """Создать сессию (если ещё нет) и вернуть карточку «Кто играет?»."""
    if GameManager.get(space_name) is not None:
        return {"text": "A game is already running in this chat — wait for the round to end."}
    GameManager.start(game, space_name)
    return build_join_card(settings.chat_app_audience, GAME_TITLES[game])


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


def _handle_join_game(user: dict, space: dict, message_name: str | None = None) -> JSONResponse:
    """Кнопка «Я в деле»: добавить игрока и обновить карточку счётчиком (без уведомления)."""
    space_name = space.get("name", "")
    user_id = user.get("name", "")
    session = GameManager.join(space_name, user_id, user.get("displayName", ""))
    if session is None:
        return JSONResponse(content={})
    card = build_join_card(settings.chat_app_audience, GAME_TITLES[session.game], session.players, session.names)
    if message_name:
        return _addon_update_message(message_name, card)
    return JSONResponse(content={})


def _start_session_game(session, space_name: str, action_url: str) -> dict:
    if session.game == "guesspionage":
        from app.services.games.guesspionage import start_guesspionage

        return start_guesspionage(session, space_name, action_url)
    if session.game == "spy":
        from app.services.games.spy import start_spy

        return start_spy(session, action_url)
    return {"text": "Game mechanics not wired up yet."}


def _handle_start_game(space: dict) -> JSONResponse:
    """Кнопка «Начать»: валидация по числу игроков и запуск."""
    space_name = space.get("name", "")
    session = GameManager.get(space_name)
    if session is None or session.started:
        return JSONResponse(content={})
    min_players = MIN_PLAYERS.get(session.game, 2)
    if len(session.players) < min_players:
        return _addon_response({"text": f"Need at least {min_players} players to start."})
    session.started = True
    return _addon_response(_start_session_game(session, space_name, settings.chat_app_audience))


def _handle_guesspionage_submit_guess(user: dict, form_inputs: dict, params: dict) -> JSONResponse:
    """Называющий прислал число (из лички): принять и огласить группе."""
    from app.services.games.guesspionage import submit_guess

    space_name = params.get("space", "")
    session = GameManager.get(space_name)
    if session is None:
        return JSONResponse(content={})
    result = submit_guess(session, user.get("name", ""), form_inputs, space_name, settings.chat_app_audience)
    return _addon_response(result)


async def _handle_guesspionage_vote(user: dict, space: dict, params: dict) -> JSONResponse:
    """Голос «выше/ниже» из группы."""
    from app.services.games.guesspionage import vote as guesspionage_vote

    space_name = space.get("name", "")
    session = GameManager.get(space_name)
    if session is None:
        return JSONResponse(content={})
    choice = params.get("choice", "higher")
    async with AsyncSessionLocal() as db:
        result = await guesspionage_vote(db, session, user.get("name", ""), choice, space_name)
    if result is None:
        return JSONResponse(content={})
    return _addon_response(result)


def _handle_spy_start_vote(space: dict) -> JSONResponse:
    """Кнопка «Начать голосование»: показать карточку «Кто шпион?»."""
    from app.services.games.spy import build_spy_vote_card

    session = GameManager.get(space.get("name", ""))
    if session is None:
        return JSONResponse(content={})
    return _addon_response(build_spy_vote_card(session.names, session.players, settings.chat_app_audience))


async def _handle_spy_vote(user: dict, space: dict, params: dict, message_name: str | None = None) -> JSONResponse:
    """Голос «кто шпион»: живое обновление карточки, в конце — итог."""
    from app.services.games.spy import vote as spy_vote

    space_name = space.get("name", "")
    session = GameManager.get(space_name)
    if session is None:
        return JSONResponse(content={})
    target = params.get("target", "")
    async with AsyncSessionLocal() as db:
        result = await spy_vote(db, session, user.get("name", ""), target, space_name, settings.chat_app_audience)
    if result is None:
        return JSONResponse(content={})
    if "cardsV2" in result and message_name:
        return _addon_update_message(message_name, result)
    return _addon_response(result)


# ---------------------------------------------------------------------------
# Игры из tree-проекта: Alias, Snake Oil, «Кто я?»/Quiplash + меню «games»
# ---------------------------------------------------------------------------

def _points_word(n: int) -> str:
    """English pluralization: 1 point, N points."""
    return "point" if n == 1 else "points"


def _is_leaderboard_command(raw_text: str) -> bool:
    """Пользователь просит показать рейтинги по играм (команда «top»)."""
    lowered = raw_text.lower().strip(" .!?")
    return any(lowered == t or lowered.startswith(t + " ") for t in (
        "топ", "лидерборд", "рейтинг", "top", "leaderboard",
    ))


def _is_points_command(raw_text: str) -> bool:
    """Пользователь просит показать общий лидерборд баллов (не по играм)."""
    lowered = raw_text.lower().strip(" .!?")
    return any(lowered == t or lowered.startswith(t + " ") for t in (
        "баллы", "очки", "балы", "points",
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


def _is_level_command(raw_text: str) -> bool:
    """Пользователь просит показать/поменять свой уровень (команда /level).

    Google Chat перехватывает '/...' как нативную слэш-команду, поэтому в живой
    переписке реальный триггер — '!level'; '/level' остаётся для тестов.
    """
    text = raw_text.lower().strip()
    for prefix in ("/", "!"):
        if text.startswith(prefix):
            text = text[1:].strip()
            break
    return any(text == t or text.startswith(t + " ") for t in ("level", "уровень", "lvl"))


def _game_command(raw_text: str) -> str | None:
    """Команда запуска игры из текста сообщения («кто я» / Quiplash)."""
    lowered = raw_text.lower().strip()
    if any(k in lowered for k in ("кто я", "who am i", "угадай кто")):
        return "who_am_i"
    if any(k in lowered for k in ("quiplash", "квиплаш", "квиплэш")):
        return "quiplash"
    return None


def _alias_response(result: dict) -> JSONResponse:
    """Ответ на действие Alias: silent → пусто, cards_v2 → обновить карточку, иначе текст."""
    if result.get("silent"):
        return JSONResponse(content={})
    if result.get("cards_v2"):
        return _addon_update_response(result["cards_v2"], text=result.get("text", ""))
    return _addon_response({"text": result.get("text", "Done")})


def _snake_response(result: dict) -> JSONResponse:
    """Ответ на действие Snake Oil: silent → пусто, cards_v2 → обновить, иначе текст."""
    if result.get("silent"):
        return JSONResponse(content={})
    if result.get("cards_v2"):
        return _addon_update_response(result["cards_v2"], text=result.get("text", ""))
    return _addon_response({"text": result.get("text", "Done")})


def _game_response(result: dict) -> JSONResponse:
    """Ответ на действие Quiplash/«Кто я?»: silent → пусто, cards_v2 → обновить, иначе текст."""
    if not result:
        return JSONResponse(content={})
    if result.get("silent"):
        return JSONResponse(content={})
    if result.get("cards_v2"):
        return _addon_update_response(result["cards_v2"], text=result.get("text", ""))
    return _addon_response({"text": result.get("text", "Done")})


async def _handle_alias_action(chat_data: dict, common: dict, method: str) -> JSONResponse:
    """Обработать клик по кнопке игры Alias (join/start/guess/skip/last/adjust/confirm/finish)."""
    params = _normalize_params(common.get("parameters"))
    user = chat_data.get("user", {})
    workspace_user_id = user.get("name", "")
    try:
        async with AsyncSessionLocal() as db:
            from app.services import alias_game

            if method == "alias_join":
                if not workspace_user_id:
                    return _addon_response({"text": "Couldn't identify you 😕"})
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
        return _addon_response({"text": "Couldn't perform the action 🤒"})
    logger.info("event=BUTTON_CLICKED alias_unknown method=%r", method)
    return JSONResponse(content={})


async def _alias_command_response(chat_data: dict, raw_text: str = "") -> JSONResponse:
    """Команда «алиас»: создать игру и карточку в группе (проактивно)."""
    space = _extract_space_dict(chat_data)
    space_name = space.get("name", "")
    if not space_name or not space_name.startswith("spaces/"):
        return _addon_response({"text": "Couldn't determine the space 🤷"})
    if _space_is_dm(space):
        return _addon_response({"text": "Alias is better launched in a group 🙂"})
    try:
        async with AsyncSessionLocal() as db:
            from app.services import alias_game

            if alias_game.is_test_command(raw_text):
                user = chat_data.get("user", {})
                workspace_user_id = user.get("name", "")
                if not workspace_user_id:
                    return _addon_response({"text": "Couldn't identify you 😕"})
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
        return _addon_response({"text": "Couldn't create the game 🤒"})
    return _alias_response(result)


async def _handle_snake_action(chat_data: dict, common: dict, method: str) -> JSONResponse:
    """Обработать клик по кнопке игры Snake Oil (join/start/vote/finish/solo_ready)."""
    params = _normalize_params(common.get("parameters"))
    user = chat_data.get("user", {})
    workspace_user_id = user.get("name", "")
    try:
        async with AsyncSessionLocal() as db:
            from app.services import snake_oil

            if method == "snake_join":
                if not workspace_user_id:
                    return _addon_response({"text": "Couldn't identify you 😕"})
                profile = await get_or_create_profile(db, workspace_user_id=workspace_user_id)
                result = await snake_oil.join_game(db, profile, int(params.get("game_id", 0) or 0))
                return _snake_response(result)
            if method == "snake_start":
                result = await snake_oil.start_game(db, int(params.get("game_id", 0) or 0))
                return _snake_response(result)
            if method == "snake_vote":
                if not workspace_user_id:
                    return _addon_response({"text": "Couldn't identify you 😕"})
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
        return _addon_response({"text": "Couldn't perform the action 🤒"})
    logger.info("event=BUTTON_CLICKED snake_unknown method=%r", method)
    return JSONResponse(content={})


async def _snake_command_response(chat_data: dict, raw_text: str = "") -> JSONResponse:
    """Команда «снейк»: создать игру и карточку в группе (проактивно)."""
    space = _extract_space_dict(chat_data)
    space_name = space.get("name", "")
    if not space_name or not space_name.startswith("spaces/"):
        return _addon_response({"text": "Couldn't determine the space 🤷"})
    if _space_is_dm(space):
        return _addon_response({"text": "Snake Oil is better launched in a group 🧪"})
    try:
        async with AsyncSessionLocal() as db:
            from app.services import snake_oil

            if snake_oil.is_test_command(raw_text):
                user = chat_data.get("user", {})
                workspace_user_id = user.get("name", "")
                if not workspace_user_id:
                    return _addon_response({"text": "Couldn't identify you 😕"})
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
        return _addon_response({"text": "Couldn't create the game 🤒"})
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


async def _start_game_from_command(space_name: str, user: dict, raw_text: str) -> dict | None:
    """Запустить игру по команде. None — это не команда игры."""
    cmd = _game_command(raw_text)
    if cmd is None:
        return None
    try:
        async with AsyncSessionLocal() as db:
            from app.services import party_games

            workspace_user_id = user.get("name", "")

            if cmd == "quiplash":
                if party_games.is_test_command(raw_text):
                    if not workspace_user_id:
                        return {"text": "Couldn't identify you 😕"}
                    profile = await get_or_create_profile(
                        db, workspace_user_id=workspace_user_id,
                        email=user.get("email"), display_name=user.get("displayName"),
                    )
                    return await party_games.setup_quiplash_test(db, space_name, profile)
                return await party_games.setup_quiplash(db, space_name)

            # «кто я»
            if party_games.is_test_command(raw_text):
                if not workspace_user_id:
                    return {"text": "Couldn't identify you 😕"}
                profile = await get_or_create_profile(
                    db, workspace_user_id=workspace_user_id,
                    email=user.get("email"), display_name=user.get("displayName"),
                )
                return await party_games.setup_who_am_i_test(db, space_name, profile)
            player_ids = await _space_human_members(space_name) or [workspace_user_id]
            return await party_games.start_who_am_i(db, space_name, player_ids)
    except Exception:
        logger.exception("game_start_failed")
        return {"text": "Couldn't start the game 🤕"}


async def _handle_game_message(space_name: str, user: dict, raw_text: str) -> dict | None:
    """Обработать сообщение как ход игры. None — активной игры нет."""
    user_id = user.get("name", "")
    if not user_id:
        return None
    try:
        async with AsyncSessionLocal() as db:
            from app.services import party_games

            return await party_games.handle_message(db, space_name, user_id, raw_text)
    except Exception:
        logger.exception("game_message_failed")
        return {"text": "Error processing the game move 🤕"}


async def _handle_game_dm_message(user: dict, raw_text: str) -> dict | None:
    """Сообщение в личку во время игры (ответ Quiplash / «мой секрет»). None — нет игры."""
    user_id = user.get("name", "")
    if not user_id:
        return None
    try:
        async with AsyncSessionLocal() as db:
            from app.services import party_games

            return await party_games.handle_dm_message(db, user_id, raw_text)
    except Exception:
        logger.exception("game_dm_message_failed")
        return {"text": "Error processing the answer 🤕"}


async def _handle_game_action(chat_data: dict, common: dict, method: str) -> JSONResponse:
    """Обработать клик по карточке Quiplash (join/start/answer/vote/finish)."""
    params = _normalize_params(common.get("parameters"))
    user = chat_data.get("user", {})
    workspace_user_id = user.get("name", "")
    form_inputs = common.get("formInputs", {}) or {}
    game_id = int(params.get("game_id", 0) or 0)
    if not game_id:
        return _game_response({"text": "Game not found 🤷"})
    try:
        async with AsyncSessionLocal() as db:
            from app.services import party_games

            if method == "game_join":
                if not workspace_user_id:
                    return _game_response({"text": "Couldn't identify you 😕"})
                profile = await get_or_create_profile(
                    db, workspace_user_id=workspace_user_id,
                    email=user.get("email"), display_name=user.get("displayName"),
                )
                result = await party_games.join_quiplash(db, profile, game_id)
            else:
                result = await party_games.handle_card_action(
                    db, game_id, workspace_user_id, method, form_inputs, params,
                )
            return _game_response(result)
    except Exception:
        logger.exception("game_action_failed method=%s", method)
        return _game_response({"text": "Error processing the action 🤕"})


def _games_menu_card(action_url: str) -> dict:
    """Карточка-меню выбора игры: только мультиплеер (все 6 игр)."""

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
            "header": {"title": "Choose a game 🎮", "subtitle": "Press a button — the game starts in the group"},
            "sections": [{"widgets": [{"buttonList": {"buttons": [
                _btn("🎲 Alias", "menu_alias"),
                _btn("🧪 Snake Oil", "menu_snake"),
                _btn("🎮 Quiplash", "menu_quiplash"),
                _btn("🎭 Who am I?", "menu_who_am_i"),
                _btn("🕵️ Spy", "menu_spy"),
                _btn("📊 Guesspionage", "menu_guesspionage"),
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
            "header": {"title": "Alias setup 🎲", "subtitle": "Empty field = default value"},
            "sections": [{"widgets": [
                {"textInput": {"name": "alias_target", "label": "Target points (default 15)"}},
                {"textInput": {
                    "name": "alias_teams",
                    "label": "Team names separated by spaces (default 'Team 1' 'Team 2')",
                }},
                {"buttonList": {"buttons": [_btn("▶️ Create game", "menu_alias_create")]}},
            ]}],
        },
    }]}


async def _games_command_response(chat_data: dict) -> JSONResponse:
    """Команда «игры»: показать меню выбора игры."""
    space = _extract_space_dict(chat_data)
    space_name = space.get("name", "")
    if not space_name or not space_name.startswith("spaces/"):
        return _addon_response({"text": "Couldn't determine the space 🤷"})
    if _space_is_dm(space):
        return _addon_response({"text": "Games are better launched in a group 🙂"})
    return _addon_response(_games_menu_card(settings.chat_app_audience))


async def _handle_games_menu_action(chat_data: dict, common: dict, method: str) -> JSONResponse:
    """Клик по кнопке меню игр: показать настройку или создать и запустить игру."""
    space = _extract_space_dict(chat_data)
    space_name = space.get("name", "")
    if not space_name or not space_name.startswith("spaces/"):
        return _addon_response({"text": "Couldn't determine the space 🤷"})
    user = chat_data.get("user", {})
    workspace_user_id = user.get("name", "")
    action_url = settings.chat_app_audience

    # Второй шаг для Alias: вместо меню показываем форму настройки.
    if method == "menu_alias":
        return _addon_update_response(_alias_setup_card(action_url)["cardsV2"])

    # Существующие in-memory игры (Шпион / Guesspionage) — карточка «Кто играет?».
    if method in ("menu_spy", "menu_guesspionage"):
        game = "spy" if method == "menu_spy" else "guesspionage"
        return _addon_response(_game_command_response(game, space_name))

    try:
        async with AsyncSessionLocal() as db:
            from app.services import alias_game, snake_oil
            from app.services.form_parsing import parse_form_inputs

            # Snake Oil — запускается сразу (настроек нет).
            if method == "menu_snake":
                result = await snake_oil.game_from_command(db, space_name, "снейк")
                return _snake_response(result)

            # Quiplash создаётся в setup-режиме (игроки присоединяются кнопкой);
            # «Кто я?» — запускается сразу (участники = human-члены space).
            if method == "menu_quiplash":
                from app.services import party_games
                return _game_response(await party_games.setup_quiplash(db, space_name))
            if method == "menu_who_am_i":
                from app.services import party_games
                player_ids = await _space_human_members(space_name)
                if not player_ids:
                    player_ids = [workspace_user_id] if workspace_user_id else []
                result = await party_games.start_who_am_i(db, space_name, player_ids)
                return _game_response(result)

            # Создание Alias по значениям из формы.
            if method == "menu_alias_create":
                values = parse_form_inputs(common.get("formInputs", {}) or {})
                target = (values.get("alias_target") or [""])[0].strip()
                teams = (values.get("alias_teams") or [""])[0].strip()
                parts = ["алиас"]
                if target.isdigit():
                    parts.append(target)
                if teams:
                    parts.extend(teams.split())
                result = await alias_game.game_from_command(db, space_name, " ".join(parts))
                if result.get("ok"):
                    return _addon_update_response(text="✅ Game created, see below 👇")
                return _alias_response(result)
    except Exception:
        logger.exception("games_menu_action_failed method=%s", method)
        return _addon_response({"text": "Couldn't start the game 🤒"})
    logger.info("event=BUTTON_CLICKED games_menu_unknown method=%r", method)
    return JSONResponse(content={})


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


async def _handle_checkin_present(chat_data: dict, common: dict) -> JSONResponse:
    """Кнопка «Я на встрече»: self-check-in в окне → обновить карточку счётчиком."""
    params = common.get("parameters") or {}
    instance_id = str(params.get("instance", ""))
    user = chat_data.get("user", {})
    workspace_user_id = user.get("name", "")
    message_name = (chat_data.get("buttonClickedPayload", {}).get("message") or {}).get("name")
    result = {"ok": False, "within": False, "count": 0}
    if workspace_user_id and instance_id.isdigit():
        try:
            from app.services.checkin import build_checkin_card, submit_checkin

            async with AsyncSessionLocal() as db:
                profile = await get_or_create_profile(db, workspace_user_id=workspace_user_id)
                result = await submit_checkin(db, profile, int(instance_id))
        except Exception:
            logger.exception("checkin_submit_failed")
    if result.get("within") and message_name:
        card = build_checkin_card(instance_id, settings.chat_app_audience, result.get("count", 0))
        return _addon_update_message(message_name, card)
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
        return {"text": "Thanks! Answers and votes saved. 🤝"}
    if result.get("reason") == "closed":
        return {"text": "This week's poll is closed — see you next week! ⏳"}
    return {"text": "Couldn't save answers — fill in at least something and press 'Submit'."}


async def _submit_daily_poll(chat_data: dict, common: dict, message_name: str | None = None) -> JSONResponse:
    """Обработать клик по кнопке недельного опроса (день+время).

    При успехе и наличии message_name — обновляет карточку счётчиками
    (updateMessageAction), иначе/при закрытии — текст (createMessageAction).
    """
    form_inputs = common.get("formInputs", {}) or {}
    params = common.get("parameters") or {}
    if isinstance(params, list):
        params = {p.get("key"): p.get("value") for p in params if isinstance(p, dict)}
    if not form_inputs and isinstance(params, dict) and params.get("time"):
        form_inputs = {
            "day": {"stringInputs": {"value": [str(params.get("day", ""))]}},
            "time": {"stringInputs": {"value": [str(params["time"])]}},
        }
    user = chat_data.get("user", {})
    workspace_user_id = user.get("name", "")
    result = {"ok": False, "reason": "no_user"}
    updated_card = None
    if workspace_user_id:
        try:
            space = _extract_space_dict(chat_data)
            async with AsyncSessionLocal() as db:
                profile = await get_or_create_profile(
                    db, workspace_user_id=workspace_user_id,
                    email=user.get("email"), display_name=user.get("displayName"),
                    chat_space_id=_dm_space_name(space),
                )
                from app.services.weekly_poll import (
                    active_weekly_poll, build_weekly_poll_card, poll_counts, submit_poll,
                )
                result = await submit_poll(db, profile, form_inputs)
                if result.get("ok") and message_name:
                    try:
                        poll = await active_weekly_poll(db)
                        if poll is not None:
                            days, times, counts = await poll_counts(db, poll.id)
                            updated_card = build_weekly_poll_card(
                                days, times, settings.chat_app_audience, counts,
                            )
                    except Exception:
                        # голос уже записан — карточку просто не обновим
                        logger.exception("weekly_poll_card_build_failed")
        except Exception:
            logger.exception("weekly_poll_submit_failed")
            result = {"ok": False, "reason": "db_error"}
    if result.get("ok"):
        if updated_card is not None and message_name:
            return _addon_update_message(message_name, updated_card)
        return _addon_response({"text": "Thanks, noted! 🙌"})
    if result.get("reason") == "closed":
        return _addon_response({"text": "Voting is closed — results announced."})
    return _addon_response({"text": "Couldn't save — try again."})


async def _handle_confirm_attendance(user: dict, params: dict) -> JSONResponse:
    """Подтверждение явки из лички (тоггл): No — снять голос, Yes — вернуть/оставить."""
    workspace_user_id = user.get("name", "")
    try:
        day = int(params.get("day", ""))
    except (TypeError, ValueError):
        day = -1
    answer = params.get("answer", "")
    if not workspace_user_id or day < 0 or answer not in ("yes", "no"):
        return _addon_response({"text": "Couldn't process that 🤷"})
    try:
        async with AsyncSessionLocal() as db:
            profile = await get_or_create_profile(db, workspace_user_id=workspace_user_id)
            from app.services.weekly_poll import DAY_FULL, decline_day, restore_day

            if answer == "no":
                removed = await decline_day(db, profile, day)
                if removed:
                    return _addon_response({"text": f"Got it — you're out for {DAY_FULL[day]} ❌"})
                return _addon_response({"text": "You didn't have a vote for that day."})
            restored = await restore_day(db, profile, day)
            if restored:
                return _addon_response({"text": f"Welcome back — you're in for {DAY_FULL[day]} ✅"})
            return _addon_response({"text": "See you there! ✅"})
    except Exception:
        logger.exception("confirm_attendance_failed")
        return _addon_response({"text": "Couldn't process that 🤒"})


async def _submit_onboarding(user: dict, space: dict, form_inputs: dict) -> dict:
    """Сохранить анкету онбординга и вернуть текстовое сообщение для пользователя."""
    workspace_user_id = user.get("name", "")
    if not workspace_user_id or not form_inputs:
        return {
            "text": "To save the form, fill in at least a few fields and press 'Submit'."
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
                return {"text": "The form is empty — fill in at least one question 🤔"}
    except Exception:
        logger.exception("onboarding_save_failed")
        return {"text": "Couldn't save the form. Try again 🤞"}
    return {
        "text": "Thanks, your form is saved! We'll use your answers to pick topics and a partner for the next meetup 🔥"
    }


async def _level_payload(chat_data: dict) -> dict:
    """Payload для /level: карточка выбора уровня в личке (с текущим уровнем), текст в группе."""
    space = _extract_space_dict(chat_data)
    if not _space_is_dm(space):
        return {"text": "DM me to change your English level 🙌"}
    user = chat_data.get("user", {})
    workspace_user_id = user.get("name", "")
    current = None
    if workspace_user_id:
        try:
            async with AsyncSessionLocal() as db:
                profile = await get_or_create_profile(
                    db, workspace_user_id=workspace_user_id,
                    email=user.get("email"), display_name=user.get("displayName"),
                    chat_space_id=_dm_space_name(space),
                )
                current = profile.english_level
        except Exception:
            logger.exception("level_command_profile_failed")
    return build_level_card(current, settings.chat_app_audience)


async def _set_level(chat_data: dict, common: dict) -> JSONResponse:
    """Сохранение выбранного уровня из карточки /level (или backfill)."""
    from app.services.form_parsing import parse_form_inputs

    form_inputs = common.get("formInputs", {}) or {}
    values = parse_form_inputs(form_inputs).get("q_level", [])
    level = normalize_level(values[0]) if values else None
    user = chat_data.get("user", {})
    workspace_user_id = user.get("name", "")
    if workspace_user_id and level:
        try:
            space = _extract_space_dict(chat_data)
            async with AsyncSessionLocal() as db:
                profile = await get_or_create_profile(
                    db, workspace_user_id=workspace_user_id,
                    email=user.get("email"), display_name=user.get("displayName"),
                    chat_space_id=_dm_space_name(space),
                )
                profile.english_level = level
                await db.commit()
        except Exception:
            logger.exception("set_level_failed")
            return _addon_response({"text": "Couldn't save your level. Try again 🤞"})
        return _addon_response(
            {"text": f"Got it — your level is now {level}. Questions and vocabulary will match it 🎯"}
        )
    return _addon_response({"text": "Something went wrong. Try again."})


async def _submit_weekly_question(chat_data: dict, common: dict) -> JSONResponse:
    """Сохранить ответ на еженедельный вопрос."""
    form_inputs = common.get("formInputs", {}) or {}
    params = common.get("parameters") or {}
    if isinstance(params, list):
        params = {p.get("key"): p.get("value") for p in params if isinstance(p, dict)}
    q_llm_text = params.get("q_llm_text", "")
    q_bank_text = params.get("q_bank_text", "")
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
                from app.services.weekly_questions import submit_weekly_question

                result = await submit_weekly_question(db, profile, form_inputs, q_llm_text, q_bank_text)
        except Exception:
            logger.exception("weekly_question_submit_failed")
            result = {"ok": False, "reason": "db_error"}
    if result.get("ok"):
        return _addon_response({"text": "Thanks for your answer! 🎉"})
    return _addon_response({"text": "Write an answer and press 'Submit answer'."})


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


async def _handle_hangman_action(chat_data: dict, common: dict, method: str) -> JSONResponse:
    """Клик по кнопкам ДМ-игр: старт «Виселицы», рейтинг, ход, новая игра."""
    params = _params_dict(common)
    user = chat_data.get("user", {})
    workspace_user_id = user.get("name", "")
    form_inputs = common.get("formInputs", {}) or {}
    space = _extract_space_dict(chat_data)
    space_name = space.get("name", "")

    try:
        async with AsyncSessionLocal() as db:
            from app.services import hangman
            from app.services.form_parsing import parse_form_inputs

            if method == "hangman_leaderboard":
                return _addon_response(await hangman.leaderboard_response(db))

            if not workspace_user_id:
                return _addon_response({"text": "Couldn't identify you 😕"})
            profile = await get_or_create_profile(
                db, workspace_user_id=workspace_user_id,
                email=user.get("email"), display_name=user.get("displayName"),
            )

            if method == "menu_hangman":
                return _addon_response(await hangman.start_hangman(db, space_name, profile))

            game_id = int(params.get("game_id", 0) or 0)
            if not game_id:
                return _addon_response({"text": "Game not found 🤷"})

            if method == "hangman_guess":
                values = parse_form_inputs(form_inputs).get("letter") or [""]
                return _hangman_update(await hangman.guess(db, game_id, profile, values[0]))
            if method == "hangman_word_guess":
                values = parse_form_inputs(form_inputs).get("word") or [""]
                return _hangman_update(await hangman.guess_word(db, game_id, profile, values[0]))
            if method == "hangman_new":
                return _hangman_update(await hangman.new_game(db, game_id, profile))
    except Exception:
        logger.exception("hangman_action_failed method=%s", method)
        return _game_response({"text": "Error processing that action 🤕"})
    logger.info("event=BUTTON_CLICKED hangman_unknown method=%r", method)
    return JSONResponse(content={})


async def _handle_millionaire_action(chat_data: dict, common: dict, method: str) -> JSONResponse:
    """Клик по кнопкам «Миллионера»: старт, ответ, подсказки, новая игра, рейтинг."""
    params = _params_dict(common)
    user = chat_data.get("user", {})
    workspace_user_id = user.get("name", "")
    space = _extract_space_dict(chat_data)
    space_name = space.get("name", "")

    try:
        async with AsyncSessionLocal() as db:
            from app.services import millionaire

            if method == "millionaire_leaderboard":
                return _addon_response(await millionaire.leaderboard_response(db))

            if not workspace_user_id:
                return _addon_response({"text": "Couldn't identify you 😕"})
            profile = await get_or_create_profile(
                db, workspace_user_id=workspace_user_id,
                email=user.get("email"), display_name=user.get("displayName"),
            )

            if method == "menu_millionaire":
                return _addon_response(await millionaire.start_millionaire(db, space_name, profile))

            game_id = int(params.get("game_id", 0) or 0)
            if not game_id:
                return _addon_response({"text": "Game not found 🤷"})

            if method == "millionaire_answer":
                answer_index = int(params.get("answer", -1) or -1)
                if answer_index < 0:
                    return _addon_response({"text": "Pick an answer 🤷"})
                return _hangman_update(await millionaire.answer(db, game_id, profile, answer_index))
            if method == "millionaire_5050":
                return _hangman_update(await millionaire.use_5050(db, game_id, profile))
            if method == "millionaire_hint":
                return _hangman_update(await millionaire.use_hint(db, game_id, profile))
            if method == "millionaire_new":
                return _hangman_update(await millionaire.new_game(db, game_id, profile))
            if method == "millionaire_quit":
                return _hangman_update(await millionaire.quit_game(db, game_id, profile))
    except Exception:
        logger.exception("millionaire_action_failed method=%s", method)
        return _game_response({"text": "Error processing that action 🤕"})
    logger.info("event=BUTTON_CLICKED millionaire_unknown method=%r", method)
    return JSONResponse(content={})


async def _handle_wordle_action(chat_data: dict, common: dict, method: str) -> JSONResponse:
    """Клик по кнопкам Wordle: старт, попытка угадать слово, новая игра, рейтинг."""
    params = _params_dict(common)
    user = chat_data.get("user", {})
    workspace_user_id = user.get("name", "")
    form_inputs = common.get("formInputs", {}) or {}
    space = _extract_space_dict(chat_data)
    space_name = space.get("name", "")

    try:
        async with AsyncSessionLocal() as db:
            from app.services import wordle
            from app.services.form_parsing import parse_form_inputs

            if method == "wordle_leaderboard":
                return _addon_response(await wordle.leaderboard_response(db))

            if not workspace_user_id:
                return _addon_response({"text": "Couldn't identify you 😕"})
            profile = await get_or_create_profile(
                db, workspace_user_id=workspace_user_id,
                email=user.get("email"), display_name=user.get("displayName"),
            )

            if method == "menu_wordle":
                return _addon_response(await wordle.start_wordle(db, space_name, profile))

            game_id = int(params.get("game_id", 0) or 0)
            if not game_id:
                return _addon_response({"text": "Game not found 🤷"})

            if method == "wordle_guess":
                values = parse_form_inputs(form_inputs).get("word") or [""]
                return _hangman_update(await wordle.guess(db, game_id, profile, values[0]))
            if method == "wordle_new":
                return _hangman_update(await wordle.new_game(db, game_id, profile))
            if method == "wordle_quit":
                return _hangman_update(await wordle.quit_game(db, game_id, profile))
    except Exception:
        logger.exception("wordle_action_failed method=%s", method)
        return _game_response({"text": "Error processing that action 🤕"})
    logger.info("event=BUTTON_CLICKED wordle_unknown method=%r", method)
    return JSONResponse(content={})


async def _handle_two_truths_action(chat_data: dict, common: dict, method: str) -> JSONResponse:
    """Клик по кнопкам «Две правды, одна ложь»: старт, выбор, новый набор."""
    params = _params_dict(common)
    user = chat_data.get("user", {})
    workspace_user_id = user.get("name", "")
    space = _extract_space_dict(chat_data)
    space_name = space.get("name", "")

    try:
        async with AsyncSessionLocal() as db:
            from app.services import two_truths

            if not workspace_user_id:
                return _addon_response({"text": "Couldn't identify you 😕"})
            profile = await get_or_create_profile(
                db, workspace_user_id=workspace_user_id,
                email=user.get("email"), display_name=user.get("displayName"),
            )

            if method == "menu_two_truths":
                return _addon_response(await two_truths.start_two_truths(db, space_name, profile))

            game_id = int(params.get("game_id", 0) or 0)
            if not game_id:
                return _addon_response({"text": "Game not found 🤷"})

            if method == "two_truths_pick":
                choice = int(params.get("choice", 0) or 0)
                return _hangman_update(await two_truths.pick(db, game_id, profile, choice))
            if method == "two_truths_new":
                return _hangman_update(await two_truths.new_game(db, game_id, profile))
    except Exception:
        logger.exception("two_truths_action_failed method=%s", method)
        return _game_response({"text": "Error processing that action 🤕"})
    logger.info("event=BUTTON_CLICKED two_truths_unknown method=%r", method)
    return JSONResponse(content={})


async def _handle_word_puzzle_action(chat_data: dict, common: dict, method: str) -> JSONResponse:
    """Клик по кнопкам «Словесного пазла»: старт, проверка порядка, новый пазл."""
    params = _params_dict(common)
    user = chat_data.get("user", {})
    workspace_user_id = user.get("name", "")
    form_inputs = common.get("formInputs", {}) or {}
    space = _extract_space_dict(chat_data)
    space_name = space.get("name", "")

    try:
        async with AsyncSessionLocal() as db:
            from app.services import word_puzzle
            from app.services.form_parsing import parse_form_inputs

            if not workspace_user_id:
                return _addon_response({"text": "Couldn't identify you 😕"})
            profile = await get_or_create_profile(
                db, workspace_user_id=workspace_user_id,
                email=user.get("email"), display_name=user.get("displayName"),
            )

            if method == "menu_word_puzzle":
                return _addon_response(await word_puzzle.start_word_puzzle(db, space_name, profile))

            game_id = int(params.get("game_id", 0) or 0)
            if not game_id:
                return _addon_response({"text": "Game not found 🤷"})

            if method == "word_puzzle_check":
                values = parse_form_inputs(form_inputs).get("order") or [""]
                return _hangman_update(await word_puzzle.check(db, game_id, profile, values[0]))
            if method == "word_puzzle_new":
                return _hangman_update(await word_puzzle.new_game(db, game_id, profile))
    except Exception:
        logger.exception("word_puzzle_action_failed method=%s", method)
        return _game_response({"text": "Error processing that action 🤕"})
    logger.info("event=BUTTON_CLICKED word_puzzle_unknown method=%r", method)
    return JSONResponse(content={})


async def _handle_translation_action(chat_data: dict, common: dict, method: str) -> JSONResponse:
    """Клик по кнопкам «Переведи-ка»: старт, проверка перевода, следующая пара, финиш."""
    params = _params_dict(common)
    user = chat_data.get("user", {})
    workspace_user_id = user.get("name", "")
    form_inputs = common.get("formInputs", {}) or {}
    space = _extract_space_dict(chat_data)
    space_name = space.get("name", "")

    try:
        async with AsyncSessionLocal() as db:
            from app.services import translation
            from app.services.form_parsing import parse_form_inputs

            if not workspace_user_id:
                return _addon_response({"text": "Couldn't identify you 😕"})
            profile = await get_or_create_profile(
                db, workspace_user_id=workspace_user_id,
                email=user.get("email"), display_name=user.get("displayName"),
            )

            if method == "menu_translation":
                return _addon_response(await translation.start_translation(db, space_name, profile))

            game_id = int(params.get("game_id", 0) or 0)
            if not game_id:
                return _addon_response({"text": "Game not found 🤷"})

            if method == "translation_check":
                values = parse_form_inputs(form_inputs).get("answer") or [""]
                return _hangman_update(await translation.check(db, game_id, profile, values[0]))
            if method == "translation_next":
                return _hangman_update(await translation.next_round(db, game_id, profile))
            if method == "translation_finish":
                return _hangman_update(await translation.finish(db, game_id, profile))
    except Exception:
        logger.exception("translation_action_failed method=%s", method)
        return _game_response({"text": "Error processing that action 🤕"})
    logger.info("event=BUTTON_CLICKED translation_unknown method=%r", method)
    return JSONResponse(content={})


async def _handle_words_of_wonders_action(chat_data: dict, common: dict, method: str) -> JSONResponse:
    """Клик по кнопкам «Words of Wonders»: старт, проверка слова, сдача, новый пазл."""
    params = _params_dict(common)
    user = chat_data.get("user", {})
    workspace_user_id = user.get("name", "")
    form_inputs = common.get("formInputs", {}) or {}
    space = _extract_space_dict(chat_data)
    space_name = space.get("name", "")

    try:
        async with AsyncSessionLocal() as db:
            from app.services import words_of_wonders
            from app.services.form_parsing import parse_form_inputs

            if not workspace_user_id:
                return _addon_response({"text": "Couldn't identify you 😕"})
            profile = await get_or_create_profile(
                db, workspace_user_id=workspace_user_id,
                email=user.get("email"), display_name=user.get("displayName"),
            )

            if method == "menu_wow":
                return _addon_response(await words_of_wonders.start(db, space_name, profile))

            game_id = int(params.get("game_id", 0) or 0)
            if not game_id:
                return _addon_response({"text": "Game not found 🤷"})

            if method == "wow_check":
                values = parse_form_inputs(form_inputs).get("answer") or [""]
                return _hangman_update(await words_of_wonders.check(db, game_id, profile, values[0]))
            if method == "wow_reveal":
                return _hangman_update(await words_of_wonders.reveal(db, game_id, profile))
            if method == "wow_new":
                return _hangman_update(await words_of_wonders.new_game(db, game_id, profile))
    except Exception:
        logger.exception("words_of_wonders_action_failed method=%s", method)
        return _game_response({"text": "Error processing that action 🤕"})
    logger.info("event=BUTTON_CLICKED wow_unknown method=%r", method)
    return JSONResponse(content={})


async def _handle_riddles_action(chat_data: dict, common: dict, method: str) -> JSONResponse:
    """Клик по кнопкам «Riddles»: старт, проверка ответа, подсказка, сдача, следующая, финиш."""
    params = _params_dict(common)
    user = chat_data.get("user", {})
    workspace_user_id = user.get("name", "")
    form_inputs = common.get("formInputs", {}) or {}
    space = _extract_space_dict(chat_data)
    space_name = space.get("name", "")

    try:
        async with AsyncSessionLocal() as db:
            from app.services import riddles
            from app.services.form_parsing import parse_form_inputs

            if not workspace_user_id:
                return _addon_response({"text": "Couldn't identify you 😕"})
            profile = await get_or_create_profile(
                db, workspace_user_id=workspace_user_id,
                email=user.get("email"), display_name=user.get("displayName"),
            )

            if method == "menu_riddles":
                return _addon_response(await riddles.start(db, space_name, profile))

            game_id = int(params.get("game_id", 0) or 0)
            if not game_id:
                return _addon_response({"text": "Game not found 🤷"})

            if method == "riddle_check":
                values = parse_form_inputs(form_inputs).get("answer") or [""]
                return _hangman_update(await riddles.check(db, game_id, profile, values[0]))
            if method == "riddle_hint":
                return _hangman_update(await riddles.hint(db, game_id, profile))
            if method == "riddle_reveal":
                return _hangman_update(await riddles.reveal(db, game_id, profile))
            if method == "riddle_next":
                return _hangman_update(await riddles.next_riddle(db, game_id, profile))
            if method == "riddle_finish":
                return _hangman_update(await riddles.finish(db, game_id, profile))
    except Exception:
        logger.exception("riddles_action_failed method=%s", method)
        return _game_response({"text": "Error processing that action 🤕"})
    logger.info("event=BUTTON_CLICKED riddles_unknown method=%r", method)
    return JSONResponse(content={})


def _dm_games_menu_card(action_url: str) -> dict:
    """Карточка-меню ДМ-игр: по кнопке — соло-игра в личке или общее меню рейтингов."""

    def _btn(text: str, method: str) -> dict:
        return {
            "text": text,
            "onClick": {"action": {
                "function": action_url,
                "parameters": [{"key": "method", "value": method}],
            }},
        }

    return {"cardsV2": [{
        "cardId": "dmGamesMenu",
        "card": {
            "header": {"title": "What shall we play in DM? 🎮", "subtitle": "Solo games vs the bot"},
            "sections": [{"widgets": [{"buttonList": {"buttons": [
                _btn("💀 Hangman", "menu_hangman"),
                _btn("💎 Millionaire", "menu_millionaire"),
                _btn("🟩 Wordle", "menu_wordle"),
                _btn("🤥 Two truths & a lie", "menu_two_truths"),
                _btn("🧩 Word puzzle", "menu_word_puzzle"),
                _btn("🔤 Translate it", "menu_translation"),
                _btn("🔠 Words of Wonders", "menu_wow"),
                _btn("🤔 Riddles", "menu_riddles"),
            ]}}]}],
        },
    }]}



async def _dm_games_command_response(chat_data: dict) -> JSONResponse:
    """Команда «games» в личке: показать меню ДМ-игр."""
    space = _extract_space_dict(chat_data)
    space_name = space.get("name", "")
    if not space_name or not space_name.startswith("spaces/"):
        return _addon_response({"text": "Couldn't determine the space 🤷"})
    return _addon_response(_dm_games_menu_card(settings.chat_app_audience))


# Пункты меню рейтингов: (эмодзи, подпись, method). Добавляй новые игры сюда.
_RATINGS_MENU_ITEMS = [
    ("💀", "Hangman", "hangman_leaderboard"),
    ("💎", "Millionaire", "millionaire_leaderboard"),
    ("🟩", "Wordle", "wordle_leaderboard"),
]


def _ratings_menu_card(action_url: str) -> dict:
    """Меню рейтингов по играм — расширяемое: добавляй новые игры в _RATINGS_MENU_ITEMS."""

    def _btn(text: str, method: str) -> dict:
        return {
            "text": text,
            "onClick": {"action": {
                "function": action_url,
                "parameters": [{"key": "method", "value": method}],
            }},
        }

    buttons = [_btn(f"{emoji} {label}", method) for emoji, label, method in _RATINGS_MENU_ITEMS]
    return {"cardsV2": [{
        "cardId": "ratingsMenu",
        "card": {
            "header": {"title": "Game ratings 🏆", "subtitle": "Pick a game"},
            "sections": [{"widgets": [{"buttonList": {"buttons": buttons}}]}],
        },
    }]}


async def _leaderboard_text() -> str:
    """Текст топ-N лидерборда по сумме баллов."""
    from app.services.leaderboard import get_leaderboard

    try:
        async with AsyncSessionLocal() as db:
            rows = await get_leaderboard(db, top_n=10)
    except Exception:
        logger.exception("leaderboard_failed")
        return "Couldn't show the leaderboard 🤒"
    if not rows:
        return "Nobody has points yet — check in at a meeting to get on the board! 🏆"
    lines = [
        f"{i}. {r['name'] or '—'} — {r['points']} {_points_word(r['points'])}"
        for i, r in enumerate(rows, 1)
    ]
    return "🏆 Leaderboard:\n" + "\n".join(lines)


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
    return {"text": "DM me to fill in the form 🙌"}


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
                        "title": f"Hi {user_name}! I'm EnglishMeetBot 🎉",
                        "subtitle": "I help organize English meetups",
                        "imageUrl": "https://fonts.gstatic.com/s/i/googlematerialicons/spark/v1/24px.svg",
                        "imageType": "CIRCLE",
                    },
                    "sections": [
                        {
                            "widgets": [
                                {
                                    "textParagraph": {
                                        "text": (
                                            "To make meetups interesting for you, "
                                            "fill in a short form. Where there are options — "
                                            "you can pick from the list, write your own "
                                            "or do both."
                                        )
                                    }
                                }
                            ]
                        },
                        {
                            "header": "1. What can you talk about for hours nonstop?",
                            "widgets": [
                                {
                                    "selectionInput": {
                                        "name": "q1",
                                        "label": "Pick 1–2",
                                        "type": "CHECK_BOX",
                                        "items": [
                                            {"text": "💻 IT, tech and the future", "value": "it", "selected": False},
                                            {"text": "🌍 Travel, countries and culture shock", "value": "travel", "selected": False},
                                            {"text": "🎬 Movies, series, books and pop culture", "value": "movies", "selected": False},
                                            {"text": "🎮 Video games and virtual worlds", "value": "games", "selected": False},
                                            {"text": "🧠 Psychology, self-improvement and lifehacks", "value": "psychology", "selected": False},
                                            {"text": "💼 Work, startups and career stories", "value": "work", "selected": False},
                                            {"text": "🎨 Art, music or creativity", "value": "art", "selected": False},
                                        ],
                                    }
                                },
                                {
                                    "textInput": {
                                        "name": "q1_other",
                                        "label": "Your own option",
                                    }
                                },
                            ],
                        },
                        {
                            "header": "2. What meetup vibe is closer to you?",
                            "widgets": [
                                {
                                    "selectionInput": {
                                        "name": "q2",
                                        "label": "Pick one",
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
                                        "label": "Your own option",
                                    }
                                },
                            ],
                        },
                        {
                            "header": "3. Name ONE topic you're ready to discuss right now",
                            "widgets": [
                                {
                                    "textInput": {
                                        "name": "q3",
                                        "label": "For example: AI, traveling to Japan, the 'House of the Dragon' series",
                                    }
                                }
                            ],
                        },
                        {
                            "header": "4. On which days can you spare 30–40 minutes?",
                            "widgets": [
                                {
                                    "selectionInput": {
                                        "name": "q4",
                                        "label": "Pick convenient days",
                                        "type": "CHECK_BOX",
                                        "items": [
                                            {"text": "Mon", "value": "mon", "selected": False},
                                            {"text": "Tue", "value": "tue", "selected": False},
                                            {"text": "Wed", "value": "wed", "selected": False},
                                            {"text": "Thu", "value": "thu", "selected": False},
                                            {"text": "Fri", "value": "fri", "selected": False},
                                            {"text": "Sat", "value": "sat", "selected": False},
                                            {"text": "Sun", "value": "sun", "selected": False},
                                        ],
                                    }
                                },
                                {
                                    "textInput": {
                                        "name": "q4_other",
                                        "label": "Clarification (e.g. evenings only)",
                                    }
                                },
                            ],
                        },
                        {
                            "header": "5. Why do you usually lose interest or skip activities?",
                            "widgets": [
                                {
                                    "selectionInput": {
                                        "name": "q5",
                                        "label": "Pick the closest",
                                        "type": "RADIO_BUTTON",
                                        "items": [
                                            {"text": "😴 No energy / tiredness", "value": "tired", "selected": False},
                                            {"text": "🌪️ Got busy and forgot", "value": "busy", "selected": False},
                                            {"text": "🥱 Got bored / topics didn't click", "value": "boring", "selected": False},
                                            {"text": "🫥 Awkward or uncomfortable", "value": "awkward", "selected": False},
                                        ],
                                    }
                                },
                                {
                                    "textInput": {
                                        "name": "q5_other",
                                        "label": "Your own option",
                                    }
                                },
                            ],
                        },
                        {
                            "header": "6. Can we use your answers?",
                            "widgets": [
                                {
                                    "selectionInput": {
                                        "name": "q6",
                                        "label": "Pick one",
                                        "type": "RADIO_BUTTON",
                                        "items": [
                                            {"text": "✅ Yes, sure!", "value": "yes", "selected": False},
                                            {"text": "🔒 Only anonymized data", "value": "anonymous", "selected": False},
                                            {"text": "❌ No, keep it between us", "value": "no", "selected": False},
                                        ],
                                    }
                                }
                            ],
                        },
                        {
                            "header": "7. What communication style is more comfortable for you?",
                            "widgets": [
                                {
                                    "selectionInput": {
                                        "name": "q7",
                                        "label": "Pick one",
                                        "type": "RADIO_BUTTON",
                                        "items": [
                                            {"text": "Strict: correct mistakes, give tasks", "value": "strict", "selected": False},
                                            {"text": "Relaxed: chat freely, no pressure", "value": "soft", "selected": False},
                                        ],
                                    }
                                }
                            ],
                        },
                        {
                            "header": "8. What's your English level?",
                            "widgets": [
                                {
                                    "textParagraph": {
                                        "text": (
                                            "We'll use it to send you questions and vocabulary "
                                            "that fit you.\n" + levels_description()
                                        )
                                    }
                                },
                                {
                                    "selectionInput": {
                                        "name": "q8",
                                        "label": "Pick your level",
                                        "type": "RADIO_BUTTON",
                                        "items": level_choice_items(),
                                    }
                                },
                            ],
                        },
                        {
                            "widgets": [
                                {
                                    "buttonList": {
                                        "buttons": [
                                            {
                                                "text": "Submit the form",
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
        logger.info("register_contact space=%r is_dm=%s", space, _space_is_dm(space))
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
                cfg = await get_or_create_config(db, "space_id", space_name)
                if cfg.value != space_name:
                    cfg.value = space_name
                    await db.commit()
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
                    text="Hi! Fill in a short form 🙌",
                    card=_onboarding_card("friend"),
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
                f"{mentions} — DM me to fill in the form 👋",
            )
        except Exception:
            logger.exception("onboarding_mention_failed space=%s", space_name)

    logger.info(
        "onboarding_run space=%s dm=%d mention=%d",
        space_name, len(plan["dm"]), len(plan["mention"]),
    )
    return plan


async def _handle_member_added(space_name: str, member_name: str) -> None:
    """Новый участник в группе: зарегистрировать и запустить онбординг."""
    if not member_name or not member_name.startswith("users/"):
        return
    from app.messaging import send_message
    from app.schemas import MessagePayload
    from app.services.chat_sender import send_text

    try:
        async with AsyncSessionLocal() as db:
            profile = await get_or_create_profile(db, workspace_user_id=member_name)
            if profile.onboarding_completed:
                return  # уже онборднут — не трогаем
            if profile.chat_space_id:
                send_message(
                    member_name,
                    MessagePayload(text="Hi! Fill in a short form 🙌", card=_onboarding_card("friend")),
                )
            elif space_name:
                send_text(space_name, f"<{member_name}> — DM me to fill in the form 👋")
    except Exception:
        logger.exception("member_added_onboarding_failed member=%s", member_name)


def _reply_text(user_name: str, raw_text: str) -> str:
    """Текст ответа на MESSAGE: приветствие или echo."""
    if any(g in raw_text.lower() for g in ("hi", "hello", "привет")):
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
        user_name = chat_data.get("user", {}).get("displayName", "friend")

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
            if method == "submit_weekly_question":
                return await _submit_weekly_question(chat_data, common)
            if method == "set_level":
                return await _set_level(chat_data, common)
            if method == "submit_weekly_poll":
                return _addon_response(await _submit_weekly_poll(chat_data, common))
            if method == "submit_daily_poll":
                message_name = (chat_data.get("buttonClickedPayload", {}).get("message") or {}).get("name")
                return await _submit_daily_poll(chat_data, common, message_name=message_name)
            if method == "checkin_present":
                return await _handle_checkin_present(chat_data, common)
            if method == "confirm_attendance":
                return await _handle_confirm_attendance(
                    chat_data.get("user", {}),
                    _normalize_params(common.get("parameters")),
                )
            if method == "join_game":
                space = _extract_space_dict(chat_data)
                message_name = (chat_data.get("buttonClickedPayload", {}).get("message") or {}).get("name")
                return _handle_join_game(chat_data.get("user", {}), space, message_name)
            if method == "start_game":
                space = _extract_space_dict(chat_data)
                return _handle_start_game(space)
            if method == "submit_guesspionage_guess":
                return _handle_guesspionage_submit_guess(
                    chat_data.get("user", {}),
                    common.get("formInputs", {}),
                    _normalize_params(common.get("parameters")),
                )
            if method == "guesspionage_higher_lower":
                return await _handle_guesspionage_vote(
                    chat_data.get("user", {}),
                    _extract_space_dict(chat_data),
                    _normalize_params(common.get("parameters")),
                )
            if method == "spy_start_vote":
                return _handle_spy_start_vote(_extract_space_dict(chat_data))
            if method == "spy_vote":
                message_name = (chat_data.get("buttonClickedPayload", {}).get("message") or {}).get("name")
                return await _handle_spy_vote(
                    chat_data.get("user", {}),
                    _extract_space_dict(chat_data),
                    _normalize_params(common.get("parameters")),
                    message_name,
                )
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
                "menu_alias", "menu_alias_create", "menu_snake", "menu_quiplash",
                "menu_who_am_i", "menu_spy", "menu_guesspionage",
            ):
                return await _handle_games_menu_action(chat_data, common, method)
            if method in (
                "menu_hangman", "hangman_guess", "hangman_word_guess", "hangman_new",
                "hangman_leaderboard",
            ):
                return await _handle_hangman_action(chat_data, common, method)
            if method in (
                "menu_millionaire", "millionaire_answer", "millionaire_5050",
                "millionaire_hint", "millionaire_new", "millionaire_quit",
                "millionaire_leaderboard",
            ):
                return await _handle_millionaire_action(chat_data, common, method)
            if method in (
                "menu_wordle", "wordle_guess", "wordle_new", "wordle_quit",
                "wordle_leaderboard",
            ):
                return await _handle_wordle_action(chat_data, common, method)
            if method in (
                "menu_two_truths", "two_truths_pick", "two_truths_new",
            ):
                return await _handle_two_truths_action(chat_data, common, method)
            if method in (
                "menu_word_puzzle", "word_puzzle_check", "word_puzzle_new",
            ):
                return await _handle_word_puzzle_action(chat_data, common, method)
            if method in (
                "menu_translation", "translation_check", "translation_next", "translation_finish",
            ):
                return await _handle_translation_action(chat_data, common, method)
            if method in (
                "menu_wow", "wow_check", "wow_reveal", "wow_new",
            ):
                return await _handle_words_of_wonders_action(chat_data, common, method)
            if method in (
                "menu_riddles", "riddle_check", "riddle_hint", "riddle_reveal",
                "riddle_next", "riddle_finish",
            ):
                return await _handle_riddles_action(chat_data, common, method)
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

            # Явный запрос анкеты — карточка только в личку, в группу не шлём
            if _is_onboarding_command(raw_text):
                space = _extract_space_dict(chat_data)
                return _addon_response(_onboarding_response_payload(user_name, space))

            # Команда лидерборда: меню рейтингов по играм.
            if _is_leaderboard_command(raw_text):
                return _addon_response(_ratings_menu_card(settings.chat_app_audience))

            # Общий лидерборд баллов — отдельной командой.
            if _is_points_command(raw_text):
                return _addon_response({"text": await _leaderboard_text()})

            # Меню выбора игры: в личке — соло-игры, в группе — групповые
            if _is_games_command(raw_text):
                space = _extract_space_dict(chat_data)
                if _space_is_dm(space):
                    return await _dm_games_command_response(chat_data)
                return await _games_command_response(chat_data)

            if _is_level_command(raw_text):
                return _addon_response(await _level_payload(chat_data))

            # Команды запуска игр Alias / Snake Oil
            if _is_alias_command(raw_text):
                return await _alias_command_response(chat_data, raw_text)
            if _is_snake_command(raw_text):
                return await _snake_command_response(chat_data, raw_text)

            # Запуск игры по команде («квиплаш», «кто я») и ход в активной игре
            space = _extract_space_dict(chat_data)
            space_name = space.get("name", "")
            user = chat_data.get("user", {})
            is_dm = _space_is_dm(space)

            if is_dm:
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

            game = _is_slash_command(raw_text)
            if game:
                space = _extract_space_dict(chat_data)
                return _addon_response(_game_command_response(game, space.get("name", "")))

            # Помощник занятия: вопросы про тему/игры
            from app.services.lesson_assistant import handle_lesson_query

            space = _extract_space_dict(chat_data)
            space_name = space.get("name", "")
            async with AsyncSessionLocal() as db:
                assistant_reply = await handle_lesson_query(db, raw_text, space_name)
            if assistant_reply:
                return _addon_response(assistant_reply)

            # Сохраняем профиль и ответ в БД
            user = chat_data.get("user", {})
            workspace_user_id = user.get("name", "")
            if workspace_user_id:
                try:
                    space = _extract_space_dict(chat_data)
                    async with AsyncSessionLocal() as db:
                        profile = await get_or_create_profile(
                            db,
                            workspace_user_id=workspace_user_id,
                            email=user.get("email"),
                            display_name=user.get("displayName"),
                            chat_space_id=_dm_space_name(space),
                        )
                        from datetime import datetime, timezone

                        from app.services.inactivity import touch_activity

                        touch_activity(profile, datetime.now(timezone.utc))
                        await save_answer(db, profile, ONBOARDING_QUESTION, raw_text)
                except Exception:
                    # Сбой БД не должен ломать ответ бота
                    logger.exception("db_write_failed")
            else:
                logger.warning("message_without_user_name, db write skipped")

            return _addon_response({"text": _reply_text(user_name, raw_text)})

        # Бота добавили в пространство / открыли DM
        if "addedToSpacePayload" in chat_data:
            space = chat_data["addedToSpacePayload"].get("space", {})
            space_name = space.get("name", "")
            logger.info("event=ADDED_TO_SPACE format=addon user=%r space=%s", user_name, space_name)
            await _register_contact(chat_data, space_name)
            # Онбординг: анкета в личку / @упоминание в группу
            await _run_onboarding(space_name, space)
            return JSONResponse(content={})

        # Нового участника добавили в существующую группу
        if "membershipAddedPayload" in chat_data:
            payload = chat_data["membershipAddedPayload"]
            space = payload.get("space", {})
            space_name = space.get("name", "")
            membership = payload.get("membership", {})
            member = membership.get("member", {})
            member_name = member.get("name", "")
            logger.info("event=MEMBERSHIP_ADDED format=addon member=%s space=%s", member_name, space_name)
            await _handle_member_added(space_name, member_name)
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

    if event_type == "MEMBERSHIP_ADDED":
        space = event.get("space", {})
        space_name = space.get("name", "")
        membership = event.get("membership", {})
        member = membership.get("member", {})
        member_name = member.get("name", "")
        logger.info("event=MEMBERSHIP_ADDED format=classic member=%s", member_name)
        await _handle_member_added(space_name, member_name)
        return JSONResponse(content={})

    if event_type == "MESSAGE":
        user_name = event.get("user", {}).get("displayName", "friend")
        message = event.get("message", {})
        raw_text = (message.get("text") or message.get("argumentText") or "").strip()
        logger.info("event=MESSAGE format=classic user=%s text=%r", user_name, raw_text)
        if not raw_text:
            return JSONResponse(content={})
        if _is_onboarding_command(raw_text):
            space = event.get("space", {})
            return JSONResponse(content=_onboarding_response_payload(user_name, space))
        if _is_leaderboard_command(raw_text):
            return JSONResponse(content=_ratings_menu_card(settings.chat_app_audience))
        if _is_points_command(raw_text):
            return JSONResponse(content={"text": await _leaderboard_text()})
        if _is_games_command(raw_text):
            space = event.get("space", {})
            if _space_is_dm(space):
                return await _dm_games_command_response(event)
            return await _games_command_response(event)
        if _is_level_command(raw_text):
            return JSONResponse(content=await _level_payload(event))
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
        game = _is_slash_command(raw_text)
        if game:
            space = event.get("space", {})
            return JSONResponse(content=_game_command_response(game, space.get("name", "")))

        # Помощник занятия: вопросы про тему/игры
        from app.services.lesson_assistant import handle_lesson_query

        space = event.get("space", {})
        space_name = space.get("name", "")
        async with AsyncSessionLocal() as db:
            assistant_reply = await handle_lesson_query(db, raw_text, space_name)
        if assistant_reply:
            return JSONResponse(content=assistant_reply)

        user = event.get("user", {})
        workspace_user_id = user.get("name", "")
        if workspace_user_id:
            try:
                from datetime import datetime, timezone

                from app.services.inactivity import touch_activity

                space = event.get("space", {})
                async with AsyncSessionLocal() as db:
                    profile = await get_or_create_profile(
                        db,
                        workspace_user_id=workspace_user_id,
                        email=user.get("email"),
                        display_name=user.get("displayName"),
                        chat_space_id=_dm_space_name(space),
                    )
                    touch_activity(profile, datetime.now(timezone.utc))
                    await db.commit()
            except Exception:
                logger.exception("db_write_failed")
        return JSONResponse(content={"text": _reply_text(user_name, raw_text)})

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
        if function_name == "set_level" or method == "set_level":
            user = event.get("user", {})
            space = event.get("space", {})
            form_inputs = event.get("common", {}).get("formInputs", {})
            return await _set_level({"user": user, "space": space}, {"formInputs": form_inputs})
        if function_name == "submit_daily_poll" or method == "submit_daily_poll":
            user = event.get("user", {})
            space = event.get("space", {})
            params = {}
            for p in action.get("parameters") or []:
                if isinstance(p, dict) and p.get("key"):
                    params[p.get("key")] = p.get("value")
            form_inputs = event.get("common", {}).get("formInputs", {})
            message_name = (event.get("message") or {}).get("name")
            response_msg = await _submit_daily_poll(
                {"user": user, "space": space},
                {"formInputs": form_inputs, "parameters": params},
                message_name=message_name,
            )
            return response_msg
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
            return response_msg
        if method == "confirm_attendance":
            return await _handle_confirm_attendance(
                event.get("user", {}),
                _normalize_params(action.get("parameters")),
            )
        if method == "join_game":
            return _handle_join_game(event.get("user", {}), event.get("space", {}), (event.get("message") or {}).get("name"))
        if method == "start_game":
            return _handle_start_game(event.get("space", {}))
        if method == "submit_guesspionage_guess":
            form_inputs = event.get("common", {}).get("formInputs", {})
            return _handle_guesspionage_submit_guess(
                event.get("user", {}), form_inputs, _normalize_params(action.get("parameters"))
            )
        if method == "guesspionage_higher_lower":
            return await _handle_guesspionage_vote(
                event.get("user", {}), event.get("space", {}), _normalize_params(action.get("parameters"))
            )
        if method == "spy_start_vote":
            return _handle_spy_start_vote(event.get("space", {}))
        if method == "spy_vote":
            return await _handle_spy_vote(
                event.get("user", {}),
                event.get("space", {}),
                _normalize_params(action.get("parameters")),
                (event.get("message") or {}).get("name"),
            )
        if method in (
            "alias_join", "alias_start", "alias_guess", "alias_skip",
            "alias_last", "alias_adjust", "alias_confirm", "alias_finish",
        ):
            return await _handle_alias_action(event, {"parameters": action.get("parameters") or []}, method)
        if method in (
            "snake_join", "snake_start", "snake_vote", "snake_finish", "snake_solo_ready",
        ):
            return await _handle_snake_action(event, {"parameters": action.get("parameters") or []}, method)
        if method in (
            "menu_alias", "menu_alias_create", "menu_snake", "menu_quiplash",
            "menu_who_am_i", "menu_spy", "menu_guesspionage",
        ):
            common = {
                "parameters": action.get("parameters") or [],
                "formInputs": event.get("common", {}).get("formInputs", {}),
            }
            return await _handle_games_menu_action(event, common, method)
        common = {
            "parameters": action.get("parameters") or [],
            "formInputs": event.get("common", {}).get("formInputs", {}),
        }
        if method in (
            "menu_hangman", "hangman_guess", "hangman_word_guess", "hangman_new",
            "hangman_leaderboard",
        ):
            return await _handle_hangman_action(event, common, method)
        if method in (
            "menu_millionaire", "millionaire_answer", "millionaire_5050",
            "millionaire_hint", "millionaire_new", "millionaire_quit",
            "millionaire_leaderboard",
        ):
            return await _handle_millionaire_action(event, common, method)
        if method in (
            "menu_wordle", "wordle_guess", "wordle_new", "wordle_quit",
            "wordle_leaderboard",
        ):
            return await _handle_wordle_action(event, common, method)
        if method in (
            "menu_two_truths", "two_truths_pick", "two_truths_new",
        ):
            return await _handle_two_truths_action(event, common, method)
        if method in (
            "menu_word_puzzle", "word_puzzle_check", "word_puzzle_new",
        ):
            return await _handle_word_puzzle_action(event, common, method)
        if method in (
            "menu_translation", "translation_check", "translation_next", "translation_finish",
        ):
            return await _handle_translation_action(event, common, method)
        if method in (
            "menu_wow", "wow_check", "wow_reveal", "wow_new",
        ):
            return await _handle_words_of_wonders_action(event, common, method)
        if method in (
            "menu_riddles", "riddle_check", "riddle_hint", "riddle_reveal",
            "riddle_next", "riddle_finish",
        ):
            return await _handle_riddles_action(event, common, method)
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
