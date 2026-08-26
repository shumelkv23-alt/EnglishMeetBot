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


def _is_weekly_questions_command(raw_text: str) -> bool:
    """Пользователь просит сгенерировать вопросы недели (для ручного теста)."""
    lowered = raw_text.lower().strip(" .!?")
    return any(lowered == t or lowered.startswith(t + " ") for t in (
        "вопросы", "вопрос", "вопросы недели", "questions",
    ))


def _is_weekly_table_command(raw_text: str) -> bool:
    """Пользователь просит постить/обновить недельную таблицу дней × времён."""
    lowered = raw_text.lower().strip(" .!?")
    return any(lowered == t or lowered.startswith(t + " ") for t in (
        "таблица", "расписание", "schedule", "weekly",
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
    """Пользователь просит меню выбора игры (оба языка — для группы)."""
    lowered = raw_text.lower().strip(" .!?")
    return any(lowered == t or lowered.startswith(t + " ") for t in (
        "игры", "играть", "игра", "games", "game",
    ))


def _is_games_test_command(raw_text: str) -> bool:
    """Пользователь просит меню соло-игр (vs bot) — команда «games test»/«игры тест». """
    lowered = raw_text.lower().strip(" .!?")
    return any(lowered == t or lowered.startswith(t + " ") for t in (
        "games test", "game test", "test games", "test game",
        "игры тест", "игра тест", "тест игры", "тест игра",
    ))


def _is_english_games_command(raw_text: str) -> bool:
    """Английское «games» — в личке открывает меню ДМ-игр."""
    lowered = raw_text.lower().strip(" .!?")
    return any(lowered == t or lowered.startswith(t + " ") for t in ("games", "game"))


def _is_russian_games_command(raw_text: str) -> bool:
    """Русское «игры»/«играть» — в личке даёт подколку «напиши games»."""
    lowered = raw_text.lower().strip(" .!?")
    return any(lowered == t or lowered.startswith(t + " ") for t in ("игры", "играть", "игра"))


def _game_command(raw_text: str) -> str | None:
    """Команда запуска игры из текста сообщения («кто я» / Quiplash)."""
    lowered = raw_text.lower().strip()
    if any(k in lowered for k in ("кто я", "who am i", "угадай кто")):
        return "who_am_i"
    if any(k in lowered for k in ("quiplash", "квиплаш", "квиплэш")):
        return "quiplash"
    return None


# Игры Spy / Guesspionage (DB-сессии через app/services/spy_game и guesspionage_game)
GAME_COMMANDS = ("guesspionage", "spy")


def _is_slash_command(raw_text: str) -> str | None:
    """Извлечь имя игры из текста вида '/spy' или '!spy' — 'guesspionage'/'spy'/None.

    Google Chat перехватывает '/...' как нативную слэш-команду и не доставляет её как
    MESSAGE, поэтому реальный триггер в чате — '!' (слэш — для прямых тестовых запросов).
    """
    text = raw_text.strip().lower()
    for prefix in ("/", "!"):
        if text.startswith(prefix):
            name = text[1:].split()[0] if text[1:].strip() else ""
            if name in GAME_COMMANDS:
                return name
    return None


async def _spy_guesspionage_setup(game: str, space_name: str) -> dict:
    """Создать партию Spy/Guesspionage (DB-сессия) и вернуть результат для вебхука."""
    try:
        async with AsyncSessionLocal() as db:
            if game == "spy":
                from app.services import spy_game
                return await spy_game.setup_spy(db, space_name)
            from app.services import guesspionage_game
            return await guesspionage_game.setup_guesspionage(db, space_name)
    except Exception:
        logger.exception("spy_guesspionage_setup_failed game=%s", game)
        return {"text": "Couldn't start the game 🤒"}


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
        return _addon_response({"text": "Couldn't identify you 😕"})
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
        return _addon_response({"text": "Couldn't generate questions 🤒"})


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
                if result.get("ok") and result.get("within"):
                    await _send_weekly_followup(db, profile, int(instance_id))
        except Exception:
            logger.exception("checkin_submit_failed")
    points = result.get("points", 0)
    text = (
        f"You're at the meeting! +{points} {_points_word(points)} 🎉"
        if result.get("within") else "This button is outside the meeting window — check-in not counted ⏳"
    )
    return {"text": text}


def _followup_card(day: str, time: str, poll_id: int) -> dict:
    """Карточка «придёшь завтра? да/нет» для личного уведомления после чек-ина."""
    from app.services.weekly_availability import DAY_FULL

    url = settings.chat_app_audience or "weekly_followup"

    def _btn(method: str, label: str) -> dict:
        return {
            "text": label,
            "onClick": {"action": {
                "function": url,
                "parameters": [
                    {"key": "method", "value": method},
                    {"key": "day", "value": day},
                    {"key": "time", "value": time},
                    {"key": "poll_id", "value": str(poll_id)},
                ],
            }},
        }

    return {
        "cardsV2": [{
            "cardId": "weeklyFollowup",
            "card": {
                "header": {
                    "title": f"{DAY_FULL[day]} at {time}",
                    "subtitle": "Are you still coming?",
                },
                "sections": [{"widgets": [{"buttonList": {"buttons": [
                    _btn("followup_yes", "Yes ✅"),
                    _btn("followup_no", "No ❌"),
                ]}}]}],
            },
        }]
    }


async def _send_weekly_followup(db, profile, instance_id: int) -> None:
    """После чек-ина: спросить про следующий отмеченный день (да/нет)."""
    from sqlalchemy import select

    from app.config import APP_TZ
    from app.messaging import send_message as dm_send
    from app.models import MeetingInstance as MeetingORM
    from app.schemas import MessagePayload
    from app.services.weekly_availability import DAY_FULL, next_vote_after

    meeting = (
        await db.execute(select(MeetingORM).where(MeetingORM.id == int(instance_id)))
    ).scalar_one_or_none()
    if meeting is None or meeting.scheduled_start is None:
        return
    meeting_date = meeting.scheduled_start.astimezone(APP_TZ).date()
    nxt = await next_vote_after(db, profile.id, meeting_date)
    if nxt is None:
        return
    day, time, poll_id = nxt
    dm_send(
        profile.workspace_user_id,
        MessagePayload(
            text=f"Nice! Quick question: are you coming on {DAY_FULL[day]} at {time}? 😊",
            card=_followup_card(day, time, poll_id),
        ),
    )


async def _handle_checkin_absent(chat_data: dict, common: dict) -> dict:
    """Кнопка «Couldn't make it» — запись отсутствия (без баллов) + фоллоу-ап."""
    params = common.get("parameters") or {}
    if isinstance(params, list):
        params = {p.get("key"): p.get("value") for p in params if isinstance(p, dict)}
    instance_id = str(params.get("instance", ""))
    user = chat_data.get("user", {})
    workspace_user_id = user.get("name", "")
    result = {"ok": False}
    if workspace_user_id and instance_id.isdigit():
        try:
            from app.services.checkin import submit_absent_checkin

            async with AsyncSessionLocal() as db:
                profile = await get_or_create_profile(db, workspace_user_id=workspace_user_id)
                result = await submit_absent_checkin(db, profile, int(instance_id))
                if result.get("ok"):
                    await _send_weekly_followup(db, profile, int(instance_id))
        except Exception:
            logger.exception("absent_checkin_failed")
    return {"text": "Got it — thanks for letting me know. Hope to see you next time! 👋"}


async def _handle_weekly_toggle(chat_data: dict, common: dict) -> JSONResponse:
    """Клик по ячейке таблицы: toggle голоса + обновить карточку на месте."""
    params = common.get("parameters") or {}
    if isinstance(params, list):
        params = {p.get("key"): p.get("value") for p in params if isinstance(p, dict)}
    day = str(params.get("day", ""))
    time = str(params.get("time", ""))
    user = chat_data.get("user", {})
    workspace_user_id = user.get("name", "")
    if not workspace_user_id or not day or not time:
        return JSONResponse(content={})

    result = {"ok": False}
    status_text = ""
    try:
        from app.services.weekly_availability import (
            DAY_FULL,
            build_card_for_poll,
            ensure_weekly_poll,
            toggle_weekly_vote,
        )

        async with AsyncSessionLocal() as db:
            profile = await get_or_create_profile(db, workspace_user_id=workspace_user_id)
            result = await toggle_weekly_vote(db, profile, day, time)
            if result.get("ok"):
                poll = await ensure_weekly_poll(db)
                card = await build_card_for_poll(db, poll, settings.chat_app_audience)
                status_text = (
                    f"✅ {DAY_FULL[day]} {time} — added"
                    if result.get("action") == "added"
                    else f"🗑️ {DAY_FULL[day]} {time} — removed"
                )
    except Exception:
        logger.exception("weekly_toggle_failed")
        return JSONResponse(content={})

    if not result.get("ok"):
        reason = result.get("reason", "")
        if reason == "past":
            return _addon_response({"text": "This day has already passed — can't change it ⏳"})
        if reason == "closed":
            return _addon_response({"text": "This week's schedule is already closed ⏳"})
        return _addon_response({"text": "Couldn't save — try again."})
    return _addon_update_response(card.get("cardsV2"), status_text=status_text)


async def _handle_followup(chat_data: dict, common: dict, method: str) -> JSONResponse:
    """Да/нет на «придёшь завтра?»: да — ждём, нет — убираем голос и правим таблицу."""
    params = common.get("parameters") or {}
    if isinstance(params, list):
        params = {p.get("key"): p.get("value") for p in params if isinstance(p, dict)}
    day = str(params.get("day", ""))
    time = str(params.get("time", ""))
    poll_id = str(params.get("poll_id", ""))
    user = chat_data.get("user", {})
    workspace_user_id = user.get("name", "")
    if not workspace_user_id or not day:
        return JSONResponse(content={})

    try:
        from app.services.weekly_availability import (
            DAY_FULL,
            ensure_weekly_poll,
            post_or_refresh_weekly_table,
            remove_weekly_vote,
        )

        async with AsyncSessionLocal() as db:
            profile = await get_or_create_profile(db, workspace_user_id=workspace_user_id)
            if method == "followup_no":
                pid = int(poll_id) if poll_id.isdigit() else (await ensure_weekly_poll(db)).id
                await remove_weekly_vote(db, profile.id, pid, day)
                poll = await ensure_weekly_poll(db)
                await post_or_refresh_weekly_table(db, poll)
                return _addon_response({
                    "text": f"Got it — I removed {DAY_FULL[day]}. "
                            f"Feel free to update the schedule in the group ✏️"
                })
            return _addon_response({"text": f"Perfect! See you on {DAY_FULL[day]} at {time} 👌"})
    except Exception:
        logger.exception("followup_failed method=%s", method)
        return JSONResponse(content={})


async def _weekly_table_response(chat_data: dict) -> JSONResponse:
    """Постить/обновить недельную таблицу в группу (команда «таблица»)."""
    from app.services.weekly_availability import ensure_weekly_poll, post_or_refresh_weekly_table

    try:
        async with AsyncSessionLocal() as db:
            poll = await ensure_weekly_poll(db)
            await post_or_refresh_weekly_table(db, poll, text="Кто в какие дни на этой неделе? 🗓️")
    except Exception:
        logger.exception("weekly_table_cmd_failed")
        return _addon_response({"text": "Couldn't post the schedule 🤒"})
    return JSONResponse(content={})


def _alias_response(result: dict) -> JSONResponse:
    """Ответ на действие Alias: silent → пусто, cards_v2 → обновить карточку, иначе текст."""
    if result.get("silent"):
        return JSONResponse(content={})
    if result.get("cards_v2"):
        return _addon_update_response(result["cards_v2"], text=result.get("text", ""))
    return _addon_response({"text": result.get("text", "Done")})


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
        return _addon_response({"text": "Couldn't perform that action 🤒"})
    logger.info("event=BUTTON_CLICKED alias_unknown method=%r", method)
    return JSONResponse(content={})


async def _alias_command_response(chat_data: dict, raw_text: str = "") -> JSONResponse:
    """Команда «алиас»: создать игру и карточку в группе (проактивно)."""
    space = _extract_space_dict(chat_data)
    space_name = space.get("name", "")
    if not space_name or not space_name.startswith("spaces/"):
        return _addon_response({"text": "Couldn't determine the space 🤷"})
    if _space_is_dm(space):
        return _addon_response({"text": "Alias is best launched in a group with a team 🙂"})
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


def _snake_response(result: dict) -> JSONResponse:
    """Ответ на действие Snake Oil: silent → пусто, cards_v2 → обновить, иначе текст."""
    if result.get("silent"):
        return JSONResponse(content={})
    if result.get("cards_v2"):
        return _addon_update_response(result["cards_v2"], text=result.get("text", ""))
    return _addon_response({"text": result.get("text", "Done")})


def _game_response(result: dict) -> JSONResponse:
    """Ответ на действие Quiplash: silent → пусто, cards_v2 → обновить карточку, иначе текст."""
    if not result:
        return JSONResponse(content={})
    if result.get("silent"):
        return JSONResponse(content={})
    if result.get("cards_v2"):
        return _addon_update_response(result["cards_v2"], text=result.get("text", ""))
    return _addon_response({"text": result.get("text", "Done")})


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
        return _addon_response({"text": "Couldn't perform that action 🤒"})
    logger.info("event=BUTTON_CLICKED snake_unknown method=%r", method)
    return JSONResponse(content={})


async def _snake_command_response(chat_data: dict, raw_text: str = "") -> JSONResponse:
    """Команда «снейк»: создать игру и карточку в группе (проактивно)."""
    space = _extract_space_dict(chat_data)
    space_name = space.get("name", "")
    if not space_name or not space_name.startswith("spaces/"):
        return _addon_response({"text": "Couldn't determine the space 🤷"})
    if _space_is_dm(space):
        return _addon_response({"text": "Snake Oil is best launched in a group 🧪"})
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
                        return {"text": "Couldn't identify you 😕"}
                    profile = await get_or_create_profile(
                        db, workspace_user_id=workspace_user_id,
                        email=user.get("email"), display_name=user.get("displayName"),
                    )
                    return await games.setup_quiplash_test(db, space_name, profile)
                return await games.setup_quiplash(db, space_name)

            # «кто я»
            if games.is_test_command(raw_text):
                if not workspace_user_id:
                    return {"text": "Couldn't identify you 😕"}
                profile = await get_or_create_profile(
                    db, workspace_user_id=workspace_user_id,
                    email=user.get("email"), display_name=user.get("displayName"),
                )
                return await games.setup_who_am_i_test(db, space_name, profile)
            player_ids = await _space_human_members(space_name) or [workspace_user_id]
            return await games.start_who_am_i(db, space_name, player_ids)
    except Exception:
        logger.exception("game_start_failed")
        return {"text": "Couldn't start the game 🤕"}


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
        return {"text": "Error processing the game move 🤕"}


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
        return {"text": "Error processing your answer 🤕"}


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


async def _handle_game_action(chat_data: dict, common: dict, method: str) -> JSONResponse:
    """Обработать клик по карточке Quiplash (join/start/answer/vote/finish)."""
    params = _params_dict(common)
    user = chat_data.get("user", {})
    workspace_user_id = user.get("name", "")
    form_inputs = common.get("formInputs", {}) or {}
    game_id = int(params.get("game_id", 0) or 0)
    if not game_id:
        return _game_response({"text": "Game not found 🤷"})
    try:
        async with AsyncSessionLocal() as db:
            from app.services import games

            if method == "game_join":
                if not workspace_user_id:
                    return _game_response({"text": "Couldn't identify you 😕"})
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
        return _game_response({"text": "Error processing that action 🤕"})


def _games_menu_card(action_url: str) -> dict:
    """Карточка-меню выбора командной игры (соло-режимы — в «games test»)."""

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
            "header": {"title": "Pick a game 🎮", "subtitle": "Press a button — the game starts in the group"},
            "sections": [{"widgets": [{"buttonList": {"buttons": [
                _btn("🎲 Alias — teams", "menu_alias"),
                _btn("🧪 Snake Oil — teams", "menu_snake"),
                _btn("🎮 Quiplash", "menu_quiplash"),
                _btn("🎭 Who am I?", "menu_who_am_i"),
                _btn("🕵️ Spy", "menu_spy"),
                _btn("📊 Guesspionage", "menu_guesspionage"),
            ]}}]}],
        },
    }]}


def _games_test_menu_card(action_url: str) -> dict:
    """Карточка-меню соло-игр (vs bot) — команда «games test». """

    def _btn(text: str, method: str) -> dict:
        return {
            "text": text,
            "onClick": {"action": {
                "function": action_url,
                "parameters": [{"key": "method", "value": method}],
            }},
        }

    return {"cardsV2": [{
        "cardId": "gamesTestMenu",
        "card": {
            "header": {"title": "Solo games vs bot 🤖", "subtitle": "Press a button — you vs the bot"},
            "sections": [{"widgets": [{"buttonList": {"buttons": [
                _btn("🎲 Alias — solo (vs bot)", "menu_alias_test"),
                _btn("🧪 Snake Oil — solo (vs bot)", "menu_snake_test"),
                _btn("🎮 Quiplash — solo (vs bot)", "menu_quiplash_test"),
                _btn("🎭 Who am I? — solo (vs bot)", "menu_who_am_i_test"),
            ]}}]}],
        },
    }]}


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


def _tease_text(user_name: str) -> str:
    """Подколка: на русское «игры» просим английское слово."""
    name = user_name or "friend"
    return f"{name}, we're learning English here! 😏\nWrite `games` — and let's play."


async def _dm_games_command_response(chat_data: dict) -> JSONResponse:
    """Команда «games» в личке: показать меню ДМ-игр."""
    space = _extract_space_dict(chat_data)
    space_name = space.get("name", "")
    if not space_name or not space_name.startswith("spaces/"):
        return _addon_response({"text": "Couldn't determine the space 🤷"})
    return _addon_response(_dm_games_menu_card(settings.chat_app_audience))


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
                {"textInput": {"name": "alias_target", "label": "Target score (default 15)"}},
                {"textInput": {
                    "name": "alias_teams",
                    "label": "Team names separated by spaces (default: Team 1 Team 2)",
                }},
                {"buttonList": {"buttons": [_btn("▶️ Create game", "menu_alias_create")]}},
            ]}],
        },
    }]}


def _alias_test_setup_card(action_url: str) -> dict:
    """Второй шаг меню: настройка соло-Alias (цель против бота)."""
    return {"cardsV2": [{
        "cardId": "aliasTestSetup",
        "card": {
            "header": {"title": "Alias — solo 🤖", "subtitle": "You vs the bot"},
            "sections": [{"widgets": [
                {"textInput": {"name": "alias_test_target", "label": "Target score (default 5)"}},
                {"buttonList": {"buttons": [{
                    "text": "▶️ Start",
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
        return _addon_response({"text": "Couldn't determine the space 🤷"})
    if _space_is_dm(space):
        return _addon_response({"text": "Games are best launched in a group 🙂"})
    return _addon_response(_games_menu_card(settings.chat_app_audience))


async def _games_test_command_response(chat_data: dict) -> JSONResponse:
    """Команда «games test»: показать меню соло-игр (vs bot)."""
    space = _extract_space_dict(chat_data)
    space_name = space.get("name", "")
    if not space_name or not space_name.startswith("spaces/"):
        return _addon_response({"text": "Couldn't determine the space 🤷"})
    if _space_is_dm(space):
        return _addon_response({"text": "Solo games are best launched in a group 🙂"})
    return _addon_response(_games_test_menu_card(settings.chat_app_audience))


async def _handle_spy_action(chat_data: dict, common: dict, method: str) -> JSONResponse:
    """Обработать клик по карточке Spy (join/start/start_vote/vote/finish)."""
    params = _params_dict(common)
    user = chat_data.get("user", {})
    workspace_user_id = user.get("name", "")
    game_id = int(params.get("game_id", 0) or 0)
    if not game_id:
        return _game_response({"text": "Game not found 🤷"})
    try:
        async with AsyncSessionLocal() as db:
            from app.services import spy_game

            if method == "spy_join":
                if not workspace_user_id:
                    return _game_response({"text": "Couldn't identify you 😕"})
                profile = await get_or_create_profile(
                    db, workspace_user_id=workspace_user_id,
                    email=user.get("email"), display_name=user.get("displayName"),
                )
                result = await spy_game.join_spy(db, profile, game_id)
            elif method == "spy_start":
                result = await spy_game.start_spy_game(db, game_id)
            elif method == "spy_start_vote":
                result = await spy_game.spy_start_vote(db, game_id)
            elif method == "spy_vote":
                result = await spy_game.submit_spy_vote(
                    db, game_id, workspace_user_id, params.get("target", ""),
                )
            elif method == "spy_finish":
                result = await spy_game.finish_spy(db, game_id)
            else:
                return JSONResponse(content={})
            return _game_response(result)
    except Exception:
        logger.exception("spy_action_failed method=%s", method)
        return _game_response({"text": "Error processing that action 🤕"})


async def _handle_guesspionage_action(chat_data: dict, common: dict, method: str) -> JSONResponse:
    """Обработать клик по карточке Guesspionage (join/start/submit/vote/finish)."""
    params = _params_dict(common)
    user = chat_data.get("user", {})
    workspace_user_id = user.get("name", "")
    form_inputs = common.get("formInputs", {}) or {}
    game_id = int(params.get("game_id", 0) or 0)
    if not game_id:
        return _game_response({"text": "Game not found 🤷"})
    try:
        async with AsyncSessionLocal() as db:
            from app.services import guesspionage_game

            if method == "guesspionage_join":
                if not workspace_user_id:
                    return _game_response({"text": "Couldn't identify you 😕"})
                profile = await get_or_create_profile(
                    db, workspace_user_id=workspace_user_id,
                    email=user.get("email"), display_name=user.get("displayName"),
                )
                result = await guesspionage_game.join_guesspionage(db, profile, game_id)
            elif method == "guesspionage_start":
                result = await guesspionage_game.start_guesspionage_game(db, game_id)
            elif method == "guesspionage_submit":
                result = await guesspionage_game.submit_guess(
                    db, game_id, workspace_user_id, form_inputs,
                )
            elif method == "guesspionage_vote":
                result = await guesspionage_game.vote_guesspionage(
                    db, game_id, workspace_user_id, params.get("choice", "higher"),
                )
            elif method == "guesspionage_finish":
                result = await guesspionage_game.finish_guesspionage(db, game_id)
            else:
                return JSONResponse(content={})
            return _game_response(result)
    except Exception:
        logger.exception("guesspionage_action_failed method=%s", method)
        return _game_response({"text": "Error processing that action 🤕"})


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
    if method == "menu_alias_test":
        return _addon_update_response(_alias_test_setup_card(action_url)["cardsV2"])

    # Шпион / Guesspionage — DB-сессия, карточка-лобби постится проактивно.
    if method in ("menu_spy", "menu_guesspionage"):
        game = "spy" if method == "menu_spy" else "guesspionage"
        return _game_response(await _spy_guesspionage_setup(game, space_name))

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
                    return _addon_response({"text": "Couldn't identify you 😕"})
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
                        return _addon_response({"text": "Couldn't identify you 😕"})
                    profile = await get_or_create_profile(
                        db, workspace_user_id=workspace_user_id,
                        email=user.get("email"), display_name=user.get("displayName"),
                    )
                    return _game_response(await games.setup_quiplash_test(db, space_name, profile))
                if method == "menu_who_am_i_test":
                    if not workspace_user_id:
                        return _addon_response({"text": "Couldn't identify you 😕"})
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
                        return _addon_update_response(text="✅ Game created, see below 👇")
                    return _alias_response(result)

                # menu_alias_test_create
                if not workspace_user_id:
                    return _addon_response({"text": "Couldn't identify you 😕"})
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
                    return _addon_update_response(text="✅ Game created, see below 👇")
                return _alias_response(result)
    except Exception:
        logger.exception("games_menu_action_failed method=%s", method)
        return _addon_response({"text": "Couldn't start the game 🤒"})
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
        return {"text": "Thanks! Answers and votes saved. 🤝"}
    if result.get("reason") == "closed":
        return {"text": "This week's poll is already closed — see you next week! ⏳"}
    return {"text": "Couldn't save your answers — fill in at least something and press Submit."}


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
                return _addon_update_response(card.get("cardsV2"), text="Who's meeting today and when? 🗓️")
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
        return _addon_response({"text": "Voting is already closed — the result is in."})
    return _addon_response({"text": "Couldn't save — try again."})


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
        return _addon_response({"text": "Couldn't identify you 😕"})

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
                return _addon_response({"text": "There are no active weekly questions right now 😕"})

            if await has_answered_questions(db, profile.id, questions):
                card = build_weekly_questions_card(
                    questions, settings.chat_app_audience, answered=True
                )
                return _addon_update_response(
                    card["cardsV2"], text="You already answered this week 🙌"
                )

            # answer1 → первый вопрос, answer2 → второй (по порядку в `questions`)
            answers: list[tuple[str, str]] = []
            for i, q in enumerate(questions, 1):
                vals = values.get(f"answer{i}", [])
                if vals:
                    answers.append((q, vals[0]))
            if not answers:
                return _addon_response(
                    {"text": "Fill in at least one answer before pressing Submit 🤔"}
                )

            for q, answer_text in answers:
                await save_answer(db, profile, q, answer_text)

            card = build_weekly_questions_card(
                questions, settings.chat_app_audience, answered=True
            )
            return _addon_update_response(
                card["cardsV2"], text="Thanks for your answers! 🙌 Saved."
            )
    except Exception:
        logger.exception("weekly_questions_submit_failed")
        return _addon_response({"text": "Couldn't save your answers 🤒"})


async def _submit_onboarding(user: dict, space: dict, form_inputs: dict) -> dict:
    """Сохранить анкету онбординга и вернуть текстовое сообщение для пользователя."""
    workspace_user_id = user.get("name", "")
    if not workspace_user_id or not form_inputs:
        return {
            "text": "To save the form, fill in at least a few fields and press Submit form."
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
        "text": "Thanks, the form is saved! Based on your answers we'll pick topics and a partner for the next meeting 🔥"
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
    return {"text": "DM me to fill out the form 🙌"}


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
                        "title": f"Hi, {user_name}! I'm EnglishMeetBot 🎉",
                        "subtitle": "Helping organize English meetups",
                        "imageUrl": "https://fonts.gstatic.com/s/i/googlematerialicons/spark/v1/24px.svg",
                        "imageType": "CIRCLE",
                    },
                    "sections": [
                        {
                            "widgets": [
                                {
                                    "textParagraph": {
                                        "text": (
                                            "So our meetups are interesting for you, "
                                            "fill in this short form. Where there are options, "
                                            "pick from the list, write your own, "
                                            "or both."
                                        )
                                    }
                                }
                            ]
                        },
                        {
                            "header": "1. What can you talk about for hours without stopping?",
                            "widgets": [
                                {
                                    "selectionInput": {
                                        "name": "q1",
                                        "label": "Pick 1–2",
                                        "type": "CHECK_BOX",
                                        "items": [
                                            {"text": "💻 IT, tech & the future", "value": "it", "selected": False},
                                            {"text": "🌍 Travel, countries & culture shock", "value": "travel", "selected": False},
                                            {"text": "🎬 Movies, series, books & pop culture", "value": "movies", "selected": False},
                                            {"text": "🎮 Video games & virtual worlds", "value": "games", "selected": False},
                                            {"text": "🧠 Psychology, self-growth & life hacks", "value": "psychology", "selected": False},
                                            {"text": "💼 Work, startups & career mishaps", "value": "work", "selected": False},
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
                            "header": "2. What kind of meetup vibe is closest to you?",
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
                                        "label": "For example: neural networks, a trip to Japan, the House of the Dragon series",
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
                                        "label": "Pick the days that work",
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
                                        "label": "Details (e.g., evenings only)",
                                    }
                                },
                            ],
                        },
                        {
                            "header": "5. What usually makes you lose interest or skip activities?",
                            "widgets": [
                                {
                                    "selectionInput": {
                                        "name": "q5",
                                        "label": "Pick the closest one",
                                        "type": "RADIO_BUTTON",
                                        "items": [
                                            {"text": "😴 No energy / tired", "value": "tired", "selected": False},
                                            {"text": "🌪️ Got busy and forgot", "value": "busy", "selected": False},
                                            {"text": "🥱 It got boring / topics didn't land", "value": "boring", "selected": False},
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
                                            {"text": "✅ Yes, of course!", "value": "yes", "selected": False},
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
                                            {"text": "Strict: errors corrected, homework given", "value": "strict", "selected": False},
                                            {"text": "Relaxed: free chat, no pressure", "value": "soft", "selected": False},
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
                                                "text": "Submit form",
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
    from app.services.space_onboarding import mention_new_members, onboard_space_members
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
                    text="Hi! Fill in a short form 🙌",
                    card=_onboarding_card("friend"),
                ),
            )
        except Exception:
            logger.exception("onboarding_dm_failed user=%s", ws)

    # Остальным — одно сообщение в группу с @упоминаниями (только тем, кого ещё не звали)
    if plan["mention"]:
        try:
            async with AsyncSessionLocal() as db:
                await mention_new_members(db, space_name, plan["mention"])
        except Exception:
            logger.exception("onboarding_mention_failed space=%s", space_name)

    # Голосовалка недели (таблица дней × времён) — только в группу, не в ЛС
    if not _space_is_dm(space):
        try:
            from app.services.weekly_availability import (
                ensure_weekly_poll,
                post_or_refresh_weekly_table,
            )

            async with AsyncSessionLocal() as db:
                poll = await ensure_weekly_poll(db)
                await post_or_refresh_weekly_table(
                    db, poll, text="Кто в какие дни на этой неделе? 🗓️",
                )
        except Exception:
            logger.exception("onboarding_weekly_table_failed space=%s", space_name)

    logger.info(
        "onboarding_run space=%s dm=%d mention=%d",
        space_name, len(plan["dm"]), len(plan["mention"]),
    )
    return plan


_GREETINGS = (
    "привет", "здравствуйте", "здравствуй", "добрый день", "добрый вечер",
    "доброе утро", "hi", "hello", "hey",
)


def _is_greeting(raw_text: str) -> bool:
    """Простое приветствие — не считаем его ответом на вопросы недели."""
    lowered = (raw_text or "").lower().strip(" .!?")
    return any(
        lowered == g or lowered.startswith(g + " ") or lowered.startswith(g + ",")
        for g in _GREETINGS
    )


def _reply_text(user_name: str, raw_text: str) -> str:
    """Текст ответа на MESSAGE: приветствие или echo."""
    if _is_greeting(raw_text):
        return (
            f"Hi, {user_name}! 👋\n\n"
            "I'm still learning, but soon we'll start "
            "organizing awesome English meetups!"
        )
    return (
        f'I see, you wrote: "{raw_text}"\n\n'
        "I don't know what to do with that yet, but I'll learn soon!"
    )


_ACKNOWLEDGMENTS = (
    "окей", "ок", "хорошо", "понял", "понятно", "ясно", "ага", "угу", "ладно",
    "да", "нет", "спасибо", "спс", "благодарю", "пока", "до встречи",
    "ok", "okay", "okey", "yes", "no", "thanks", "thank you", "thx",
    "got it", "cool", "nice", "bye", "goodbye",
)


def _is_acknowledgment(raw_text: str) -> bool:
    """Короткое подтверждение («окей», «спасибо») — не вопрос и не ответ на вопрос."""
    lowered = (raw_text or "").lower().strip(" .!?,。")
    return lowered in _ACKNOWLEDGMENTS


def _ack_reply(raw_text: str) -> str:
    """Короткий вежливый ответ на подтверждение."""
    lowered = (raw_text or "").lower().strip(" .!?,。")
    if lowered in ("спасибо", "спс", "благодарю", "thanks", "thank you", "thx"):
        return "You're welcome! 😊"
    if lowered in ("пока", "до встречи", "bye", "goodbye"):
        return "See you! 👋"
    return "🙂"


async def _ai_chat_reply(raw_text: str) -> str:
    """Ответ LLM на незнакомое сообщение; заглушка, если LLM недоступен."""
    from app.services.chat_ai import chat_reply

    try:
        text = await chat_reply(raw_text)
    except Exception:
        logger.exception("chat_ai_unexpected_failed")
        text = None
    if text:
        return text
    return (
        "I don't quite understand what you mean yet 😅\n"
        "I can do: `games` — games, `questions` — weekly questions. "
        "Or rephrase and I'll answer!"
    )


async def _handle_free_text(user: dict, space: dict, raw_text: str, user_name: str) -> str:
    """Ответ на свободное сообщение в личке.

    Приоритет: приветствие → подтверждение («окей/спасибо») → LLM-ответ.
    Ответы на вопросы недели принимаются ТОЛЬКО через карточку
    (submit_weekly_questions), поэтому свободный текст никуда не записывается.
    """
    if _is_greeting(raw_text):
        return _reply_text(user_name, raw_text)
    if _is_acknowledgment(raw_text):
        return _ack_reply(raw_text)
    return await _ai_chat_reply(raw_text)


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


def _addon_update_response(
    cards_v2: list[dict] | None = None,
    text: str = "",
    status_text: str = "",
) -> JSONResponse:
    """Обновить сообщение/карточку на месте (updateMessageAction) вместо нового сообщения.

    Для корректной замены карточки в сообщении у неё должен быть тот же cardId,
    что и у карточки с нажатой кнопкой (у опроса — "dailyPoll").

    status_text — короткое персональное подтверждение (toast) тому, кто нажал
    кнопку; видно только этому пользователю (actionStatus.userFacingMessage).
    """
    message: dict = {}
    if text:
        message["text"] = text
    if cards_v2:
        message["cardsV2"] = cards_v2
    payload: dict = {
        "hostAppDataAction": {
            "chatDataAction": {
                "updateMessageAction": {"message": message}
            }
        }
    }
    if status_text:
        payload["actionStatus"] = {"statusCode": "OK", "userFacingMessage": status_text}
    return JSONResponse(content=payload)


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
            if method == "submit_weekly_poll":
                return _addon_response(await _submit_weekly_poll(chat_data, common))
            if method == "submit_weekly_questions":
                return await _submit_weekly_questions(chat_data, common)
            if method == "submit_daily_poll":
                return await _submit_daily_poll(chat_data, common)
            if method == "checkin_present":
                return _addon_response(await _handle_checkin_present(chat_data, common))
            if method == "checkin_absent":
                return _addon_response(await _handle_checkin_absent(chat_data, common))
            if method == "weekly_toggle":
                return await _handle_weekly_toggle(chat_data, common)
            if method in ("followup_yes", "followup_no"):
                return await _handle_followup(chat_data, common, method)
            if method in (
                "alias_join", "alias_start", "alias_guess", "alias_skip",
                "alias_last", "alias_adjust", "alias_confirm", "alias_finish",
            ):
                return await _handle_alias_action(chat_data, common, method)
            if method in (
                "snake_join", "snake_start", "snake_vote", "snake_finish", "snake_solo_ready",
            ):
                return await _handle_snake_action(chat_data, common, method)
            if method in ("spy_join", "spy_start", "spy_start_vote", "spy_vote", "spy_finish"):
                return await _handle_spy_action(chat_data, common, method)
            if method in (
                "guesspionage_join", "guesspionage_start", "guesspionage_submit",
                "guesspionage_vote", "guesspionage_finish",
            ):
                return await _handle_guesspionage_action(chat_data, common, method)
            if method in (
                "menu_alias", "menu_alias_test", "menu_alias_create", "menu_alias_test_create",
                "menu_snake", "menu_snake_test", "menu_quiplash", "menu_quiplash_test",
                "menu_who_am_i", "menu_who_am_i_test", "menu_spy", "menu_guesspionage",
            ):
                return await _handle_games_menu_action(chat_data, common, method)
            if method in (
                "menu_hangman",
                "hangman_guess", "hangman_word_guess", "hangman_new",
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

            # Команда «вопросы» — генерация вопросов недели (проверяем ДО онбординга:
            # «вопросы» содержит подстроку «опрос»)
            if _is_weekly_questions_command(raw_text):
                return await _weekly_questions_response(chat_data)

            # Недельная таблица дней × времён (постится в группу)
            if _is_weekly_table_command(raw_text):
                return await _weekly_table_response(chat_data)

            # Явный запрос анкеты — карточка только в личку, в группу не шлём
            if _is_onboarding_command(raw_text):
                space = _extract_space_dict(chat_data)
                return _addon_response(_onboarding_response_payload(user_name, space))

            # Команда лидерборда: меню рейтингов по играм.
            if _is_leaderboard_command(raw_text):
                return _addon_response(_ratings_menu_card(settings.chat_app_audience))

            # Общий лидерборд баллов — отдельной командой (не «top»).
            if _is_points_command(raw_text):
                return _addon_response({"text": await _leaderboard_text()})

            # Пространство и тип (ДМ/группа) — нужно для маршрутизации игр ниже
            space = _extract_space_dict(chat_data)
            space_name = space.get("name", "")
            user = chat_data.get("user", {})
            is_dm = _space_is_dm(space)

            # Меню игр: в личке — ДМ-игры, в группе — групповые (как раньше).
            # Русское «игры»/«играть» в личке — подколка «напиши games».
            if is_dm and _is_english_games_command(raw_text):
                return await _dm_games_command_response(chat_data)
            if is_dm and _is_russian_games_command(raw_text):
                return _addon_response({"text": _tease_text(user_name)})
            if not is_dm and _is_games_test_command(raw_text):
                return await _games_test_command_response(chat_data)
            if not is_dm and _is_games_command(raw_text):
                return await _games_command_response(chat_data)

            # Команда запуска игры Alias
            if _is_alias_command(raw_text):
                return await _alias_command_response(chat_data, raw_text)

            # Команда запуска игры Snake Oil / «Змеиное масло»
            if _is_snake_command(raw_text):
                return await _snake_command_response(chat_data, raw_text)

            # Запуск игры по команде («квиплаш», «кто я») и ход в активной игре
            if is_dm:
                # Ответ Quiplash / «мой секрет»
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

            # Игры Spy / Guesspionage по команде «!spy» / «!guesspionage»
            game = _is_slash_command(raw_text)
            if game:
                return _game_response(await _spy_guesspionage_setup(game, space_name))

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
        user_name = event.get("user", {}).get("displayName", "friend")
        message = event.get("message", {})
        raw_text = (message.get("text") or message.get("argumentText") or "").strip()
        logger.info("event=MESSAGE format=classic user=%s text=%r", user_name, raw_text)
        if not raw_text:
            return JSONResponse(content={})
        if _is_weekly_questions_command(raw_text):
            return await _weekly_questions_response(event)
        if _is_weekly_table_command(raw_text):
            return await _weekly_table_response(event)
        if _is_onboarding_command(raw_text):
            space = event.get("space", {})
            return JSONResponse(content=_onboarding_response_payload(user_name, space))
        if _is_leaderboard_command(raw_text):
            return JSONResponse(content=_ratings_menu_card(settings.chat_app_audience))
        if _is_points_command(raw_text):
            return JSONResponse(content={"text": await _leaderboard_text()})
        if _is_games_test_command(raw_text):
            return await _games_test_command_response(event)
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
        # Игры Spy / Guesspionage по команде «!spy» / «!guesspionage»
        game = _is_slash_command(raw_text)
        if game:
            result = await _spy_guesspionage_setup(game, space_name)
            if result.get("silent"):
                return JSONResponse(content={})
            return JSONResponse(content=result)
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
        if method == "checkin_absent":
            user = event.get("user", {})
            instance_id = ""
            for p in action.get("parameters") or []:
                if isinstance(p, dict) and p.get("key") == "instance":
                    instance_id = p.get("value", "")
            response_msg = await _handle_checkin_absent(
                {"user": user, "space": event.get("space", {})},
                {"parameters": {"instance": instance_id}},
            )
            return _addon_response(response_msg)
        if method == "weekly_toggle":
            return await _handle_weekly_toggle(event, {"parameters": action.get("parameters") or []})
        if method in ("followup_yes", "followup_no"):
            return await _handle_followup(event, {"parameters": action.get("parameters") or []}, method)
        if method.startswith("game_") or method == "who_finish":
            common = {
                "parameters": action.get("parameters") or [],
                "formInputs": event.get("common", {}).get("formInputs", {}),
            }
            return await _handle_game_action(event, common, method)
        if method.startswith("spy_"):
            common = {
                "parameters": action.get("parameters") or [],
                "formInputs": event.get("common", {}).get("formInputs", {}),
            }
            return await _handle_spy_action(event, common, method)
        if method.startswith("guesspionage_"):
            common = {
                "parameters": action.get("parameters") or [],
                "formInputs": event.get("common", {}).get("formInputs", {}),
            }
            return await _handle_guesspionage_action(event, common, method)
        logger.info("event=CARD_CLICKED format=classic function=%s method=%s", function_name, method)
        return JSONResponse(content={})

    # REMOVED_FROM_SPACE и неизвестные типы — тихо отвечаем пустым JSON
    logger.info("event=unhandled type=%r keys=%s", event_type, sorted(event.keys()))
    return JSONResponse(content={})
