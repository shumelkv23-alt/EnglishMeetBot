# app/api/games.py
"""Обработчики игр (button clicks, команды, карточки меню) — выделены из google_chat.py.

Зависит от app.api.cards_helpers (хелперы ответов/карточек) и app.services.games.*.
"""
import asyncio
import logging

from fastapi.responses import JSONResponse

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.services.games.session import GameManager, build_join_card
from app.services.onboarding import get_or_create_profile

from app.api.cards_helpers import (
    _addon_response,
    _addon_update_message,
    _addon_update_response,
    _extract_space_dict,
    _hangman_update,
    _normalize_params,
    _params_dict,
    _space_is_dm,
)

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

def _points_word(n: int) -> str:
    """English pluralization: 1 point, N points."""
    return "point" if n == 1 else "points"


def _is_leaderboard_command(raw_text: str) -> bool:
    """Пользователь просит показать рейтинги по играм (команда «top»)."""
    lowered = raw_text.lower().strip(" .!?")
    return any(lowered == t or lowered.startswith(t + " ") for t in (
        "top", "leaderboard",
    ))


def _is_points_command(raw_text: str) -> bool:
    """Пользователь просит показать общий лидерборд баллов (не по играм)."""
    lowered = raw_text.lower().strip(" .!?")
    return any(lowered == t or lowered.startswith(t + " ") for t in (
        "points",
    ))


def _is_alias_command(raw_text: str) -> bool:
    """Пользователь хочет запустить игру Alias."""
    lowered = raw_text.lower().strip(" .!?")
    return any(lowered == t or lowered.startswith(t + " ") for t in (
        "alias",
    ))


def _is_snake_command(raw_text: str) -> bool:
    """Пользователь хочет запустить игру Snake Oil / «Змеиное масло»."""
    lowered = raw_text.lower().strip(" .!?")
    return any(lowered == t or lowered.startswith(t + " ") for t in (
        "snake", "snakeoil",
    ))


def _is_games_command(raw_text: str) -> bool:
    """Пользователь просит меню выбора игры."""
    lowered = raw_text.lower().strip(" .!?")
    return any(lowered == t or lowered.startswith(t + " ") for t in (
        "games", "game",
    ))

def _game_command(raw_text: str) -> str | None:
    """Команда запуска игры из текста сообщения («кто я» / Quiplash / «Поле чудес»)."""
    lowered = raw_text.lower().strip()
    if "who am i" in lowered:
        return "who_am_i"
    if "quiplash" in lowered:
        return "quiplash"
    if "wheel of fortune" in lowered or "field of miracles" in lowered:
        return "wheel"
    return None

async def _wheel_setup(space_name: str) -> dict:
    """Создать партию «Поле чудес» (DB-сессия) и вернуть результат для вебхука."""
    try:
        async with AsyncSessionLocal() as db:
            from app.services.games import wheel_game

            return await wheel_game.setup_wheel(db, space_name)
    except Exception:
        logger.exception("wheel_setup_failed space=%s", space_name)
        return {"text": "Couldn't start the game 🤒"}

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
            from app.services.games import alias_game

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
            from app.services.games import alias_game

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
            from app.services.games import snake_oil

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
            from app.services.games import snake_oil

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
            from app.services.games import party_games

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
            from app.services.games import party_games

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
            from app.services.games import party_games

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
            from app.services.games import party_games

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
                _btn("🎡 Wheel Game", "menu_wheel"),
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

    # «Поле чудес» — DB-сессия, карточка-лобби постится проактивно.
    if method == "menu_wheel":
        return _game_response(await _wheel_setup(space_name))

    try:
        async with AsyncSessionLocal() as db:
            from app.services.games import alias_game, snake_oil
            from app.services.form_parsing import parse_form_inputs

            # Snake Oil — запускается сразу (настроек нет).
            if method == "menu_snake":
                result = await snake_oil.game_from_command(db, space_name, "снейк")
                return _snake_response(result)

            # Quiplash создаётся в setup-режиме (игроки присоединяются кнопкой);
            # «Кто я?» — запускается сразу (участники = human-члены space).
            if method == "menu_quiplash":
                from app.services.games import party_games
                return _game_response(await party_games.setup_quiplash(db, space_name))
            if method == "menu_who_am_i":
                from app.services.games import party_games
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

            # Обучение «Survival English for Calls» — меню курса в личке (новое сообщение).
            if method == "menu_callready":
                if not workspace_user_id:
                    return _addon_response({"text": "Couldn't identify you 😕"})
                profile = await get_or_create_profile(
                    db, workspace_user_id=workspace_user_id,
                    email=user.get("email"), display_name=user.get("displayName"),
                )
                from app.services import callready
                return _addon_response(await callready.learn_menu(db, profile))

            # «English by level» — меню уровней A/B/C в личке (новое сообщение).
            if method == "menu_leveled":
                if not workspace_user_id:
                    return _addon_response({"text": "Couldn't identify you 😕"})
                profile = await get_or_create_profile(
                    db, workspace_user_id=workspace_user_id,
                    email=user.get("email"), display_name=user.get("displayName"),
                )
                from app.services import leveled
                return _addon_response(await leveled.level_menu(db, profile))
    except Exception:
        logger.exception("games_menu_action_failed method=%s", method)
        return _addon_response({"text": "Couldn't start the game 🤒"})
    logger.info("event=BUTTON_CLICKED games_menu_unknown method=%r", method)
    return JSONResponse(content={})

async def _handle_wheel_action(chat_data: dict, common: dict, method: str) -> JSONResponse:
    """Обработать клик по карточке «Поле чудес» (join/start/spin/guess/finish)."""
    params = _params_dict(common)
    user = chat_data.get("user", {})
    workspace_user_id = user.get("name", "")
    form_inputs = common.get("formInputs", {}) or {}
    game_id = int(params.get("game_id", 0) or 0)
    if not game_id:
        return _game_response({"text": "Game not found 🤷"})
    try:
        async with AsyncSessionLocal() as db:
            from app.services.games import wheel_game

            if method == "wheel_join":
                if not workspace_user_id:
                    return _game_response({"text": "Couldn't identify you 😕"})
                profile = await get_or_create_profile(
                    db, workspace_user_id=workspace_user_id,
                    email=user.get("email"), display_name=user.get("displayName"),
                )
                result = await wheel_game.join_wheel(db, profile, game_id)
            elif method == "wheel_start":
                result = await wheel_game.start_wheel_game(db, game_id)
            elif method == "wheel_spin":
                result = await wheel_game.wheel_spin(db, game_id, workspace_user_id)
            elif method == "wheel_guess":
                result = await wheel_game.wheel_guess(db, game_id, workspace_user_id, form_inputs)
            elif method == "wheel_finish":
                result = await wheel_game.finish_wheel(db, game_id)
            else:
                return JSONResponse(content={})
            return _game_response(result)
    except Exception:
        logger.exception("wheel_action_failed method=%s", method)
        return _game_response({"text": "Error processing that action 🤕"})

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
            from app.services.games import hangman
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
            from app.services.games import millionaire

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
            from app.services.games import wordle
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
            from app.services.games import two_truths

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
            from app.services.games import word_puzzle
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
            from app.services.games import translation
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
            from app.services.games import words_of_wonders
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
            from app.services.games import riddles
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

async def _handle_crossword_action(chat_data: dict, common: dict, method: str) -> JSONResponse:
    """Клик по кнопкам «Crossword»: старт, проверка слова, сдача, новая игра, выход."""
    params = _params_dict(common)
    user = chat_data.get("user", {})
    workspace_user_id = user.get("name", "")
    form_inputs = common.get("formInputs", {}) or {}
    space = _extract_space_dict(chat_data)
    space_name = space.get("name", "")

    try:
        async with AsyncSessionLocal() as db:
            from app.services.games import crossword
            from app.services.form_parsing import parse_form_inputs

            if not workspace_user_id:
                return _addon_response({"text": "Couldn't identify you 😕"})
            profile = await get_or_create_profile(
                db, workspace_user_id=workspace_user_id,
                email=user.get("email"), display_name=user.get("displayName"),
            )

            if method == "menu_crossword":
                return _addon_response(await crossword.start_crossword(db, space_name, profile))

            game_id = int(params.get("game_id", 0) or 0)
            if not game_id:
                return _addon_response({"text": "Game not found 🤷"})

            if method == "crossword_check":
                values = parse_form_inputs(form_inputs).get("answer") or [""]
                return _hangman_update(await crossword.check(db, game_id, profile, values[0]))
            if method == "crossword_reveal":
                return _hangman_update(await crossword.reveal(db, game_id, profile))
            if method == "crossword_new":
                return _hangman_update(await crossword.new_game(db, game_id, profile))
            if method == "crossword_quit":
                return _hangman_update(await crossword.quit_game(db, game_id, profile))
    except Exception:
        logger.exception("crossword_action_failed method=%s", method)
        return _game_response({"text": "Error processing that action 🤕"})
    logger.info("event=BUTTON_CLICKED crossword_unknown method=%r", method)
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
                _btn("✏️ Crossword", "menu_crossword"),
                _btn("🎓 Learn English (calls)", "menu_callready"),
                _btn("🌍 English by level", "menu_leveled"),
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

