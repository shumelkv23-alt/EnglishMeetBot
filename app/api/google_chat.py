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
from app.services.levels import build_level_card, level_choice_items, levels_description, normalize_level

from app.api.cards_helpers import (
    _action_method,
    _addon_response,
    _addon_update_message,
    _dm_space_name,
    _extract_space_dict,
    _hangman_update,
    _normalize_params,
    _params_dict,
    _reply_text,
    _space_is_dm,
)
from app.api.games import (
    _alias_command_response,
    _dm_games_command_response,
    _game_command_response,
    _game_response,
    _games_command_response,
    _handle_alias_action,
    _handle_crossword_action,
    _handle_game_action,
    _handle_game_dm_message,
    _handle_game_message,
    _handle_games_menu_action,
    _handle_guesspionage_submit_guess,
    _handle_guesspionage_vote,
    _handle_hangman_action,
    _handle_join_game,
    _handle_millionaire_action,
    _handle_riddles_action,
    _handle_snake_action,
    _handle_spy_start_vote,
    _handle_spy_vote,
    _handle_start_game,
    _handle_translation_action,
    _handle_two_truths_action,
    _handle_wheel_action,
    _handle_word_puzzle_action,
    _handle_wordle_action,
    _handle_words_of_wonders_action,
    _is_alias_command,
    _is_games_command,
    _is_leaderboard_command,
    _is_points_command,
    _is_slash_command,
    _is_snake_command,
    _leaderboard_text,
    _ratings_menu_card,
    _snake_command_response,
    _start_game_from_command,
)

router = APIRouter(prefix="/webhooks", tags=["Google Chat"])
logger = logging.getLogger(__name__)
settings = get_settings()











# ---------------------------------------------------------------------------
# Игры из tree-проекта: Alias, Snake Oil, «Кто я?»/Quiplash + меню «games»
# ---------------------------------------------------------------------------



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
    return any(text == t or text.startswith(t + " ") for t in ("level", "lvl"))




def _is_learn_command(raw_text: str) -> bool:
    """Команда «обучение» в личке — курс «Survival English for Calls» (EN + RU)."""
    lowered = raw_text.lower().strip(" .!?")
    return any(lowered == t or lowered.startswith(t + " ") for t in (
        "learn", "course",
    ))


def _is_leveled_command(raw_text: str) -> bool:
    """Команда «levels»/«уровни» в личке — раздел «English by level» (A/B/C).

    «level»/«уровень» (ед.ч.) занято под показ/смену своего уровня — см. _is_level_command.
    """
    lowered = raw_text.lower().strip(" .!?")
    return any(lowered == t or lowered.startswith(t + " ") for t in (
        "levels", "english by level",
    ))


def _is_info_command(raw_text: str) -> bool:
    """Команда «info» — карточка о боте и его возможностях (в личке и в группе)."""
    lowered = raw_text.lower().strip(" .!?")
    return any(lowered == t or lowered.startswith(t + " ") for t in (
        "info", "help", "commands",
    ))


def _is_mode_command(raw_text: str) -> bool:
    """Команда «показать выбор режима» (demo/orig).

    Google шлёт ADDED_TO_SPACE только один раз — при первом добавлении бота в
    пространство. При повторном добавлении (бот уже участник) или после перезапуска
    событие не приходит, и стартовую карточку некому отправить. Поэтому разрешаем
    вызвать её вручную командой «mode» / «demo» / «запуск» и т.п.
    """
    lowered = raw_text.lower().strip(" .!?")
    return any(lowered == t or lowered.startswith(t + " ") for t in (
        "mode", "demo", "setup", "run", "режим", "демо", "запуск",
    ))


def _info_card(is_dm: bool) -> dict:
    """Карточка «info»: назначение бота и его возможности (в личке или в группе)."""
    purpose = (
        "**EnglishMeetBot** — your English conversation club assistant 🤝\n\n"
        "I help bring people together for meetups and run them: manage the schedule, "
        "track attendance, launch games and short English lessons — right in the chat."
    )

    if is_dm:
        sections = [
            {"header": "What I do", "widgets": [{"textParagraph": {"text": purpose}}]},
            {"header": "Learning 📚", "widgets": [{"textParagraph": {"text": (
                "`learn` — the «Survival English for Calls» course: phrases for calls and meetings\n"
                "`levels` — English by level A/B/C: topics, vocabulary, grammar and quizzes"
            )}}]},
            {"header": "Solo games 🎮", "widgets": [{"textParagraph": {"text": (
                "`games` — solo games vs the bot:\n"
                "💀 Hangman · 💎 Millionaire · 🟩 Wordle · 🤥 Two truths & a lie\n"
                "🧩 Word puzzle · 🔤 Translate it · 🔠 Words of Wonders · 🤔 Riddles · ✏️ Crossword"
            )}}]},
            {"header": "Progress & leaderboards 📈", "widgets": [{"textParagraph": {"text": (
                "`points` — your points and the overall leaderboard\n"
                "`top` — per-game leaderboards\n"
                "`form` — fill in your level and interests"
            )}}]},
        ]
        subtitle = "what I can do in a DM"
    else:
        sections = [
            {"header": "What I do", "widgets": [{"textParagraph": {"text": purpose}}]},
            {"header": "Meetups & schedule 📅", "widgets": [{"textParagraph": {"text": (
                "`table` — weekly meetup schedule (days × times)\n"
                "`questions` — questions of the week\n"
                "Before a meetup I send an RSVP poll and reminders."
            )}}]},
            {"header": "Games for lessons 🎲", "widgets": [{"textParagraph": {"text": (
                "`games` — group games:\n"
                "🎲 Alias · 🧪 Snake Oil · 🎮 Quiplash · 🎭 Who am I\n"
                "🕵️ Spy · 📊 Guesspionage · 🎡 Wheel Game\n"
                "`alias` / `snake` — quick start"
            )}}]},
            {"header": "Leaderboards & points 📈", "widgets": [{"textParagraph": {"text": (
                "`points` — overall leaderboard of points\n"
                "`top` — per-game leaderboards\n"
                "`form` — fill in the form (in a DM)"
            )}}]},
        ]
        subtitle = "what I can do in a group"

    return {"cardsV2": [{
        "cardId": "info",
        "card": {
            "header": {"title": "EnglishMeetBot 🤖", "subtitle": subtitle},
            "sections": sections,
        },
    }]}




async def _callready_menu_response(chat_data: dict) -> JSONResponse:
    """Команда «learn»/«обучение» в личке: показать меню курса (новое сообщение)."""
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
            from app.services import callready
            card = await callready.learn_menu(db, profile)
        return _addon_response({"cardsV2": card["cardsV2"]})
    except Exception:
        logger.exception("callready_menu_cmd_failed")
        return _addon_response({"text": "Couldn't open the course 🤒"})


async def _leveled_menu_response(chat_data: dict) -> JSONResponse:
    """Команда «levels»/«уровни» в личке: показать меню уровней (новое сообщение)."""
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
            from app.services import leveled
            card = await leveled.level_menu(db, profile)
        return _addon_response({"cardsV2": card["cardsV2"]})
    except Exception:
        logger.exception("leveled_menu_cmd_failed")
        return _addon_response({"text": "Couldn't open English by level 🤒"})














async def _handle_callready_action(chat_data: dict, common: dict, method: str) -> JSONResponse:
    """Клик по кнопкам курса «Survival English for Calls»: навигация, практика, прогресс.

    Все карточки курса имеют единый cardId «callready», поэтому навигация обновляет
    карточку на месте через _hangman_update.
    """
    params = _params_dict(common)
    user = chat_data.get("user", {})
    workspace_user_id = user.get("name", "")

    def _int(value: str) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return -1

    try:
        async with AsyncSessionLocal() as db:
            from app.services import callready

            if not workspace_user_id:
                return _addon_response({"text": "Couldn't identify you 😕"})
            profile = await get_or_create_profile(
                db, workspace_user_id=workspace_user_id,
                email=user.get("email"), display_name=user.get("displayName"),
            )

            if method == "callready_menu":
                return _hangman_update(await callready.learn_menu(db, profile))
            if method == "callready_continue":
                return _hangman_update(await callready.continue_learning(db, profile))
            if method == "callready_route":
                return _hangman_update(await callready.show_route(db, profile))
            if method == "callready_progress":
                return _hangman_update(await callready.show_progress(db, profile))
            if method == "callready_phrasebook":
                return _hangman_update(await callready.show_phrasebook(db, profile))
            if method == "callready_practice":
                return _hangman_update(await callready.show_practice(db, profile))
            if method == "callready_module":
                return _hangman_update(await callready.show_module(db, profile, params.get("module", "")))
            if method == "callready_next_module":
                return _hangman_update(await callready.next_module(db, profile, params.get("module", "")))
            if method == "callready_prev_module":
                return _hangman_update(await callready.prev_module(db, profile, params.get("module", "")))
            if method == "callready_phrasebook_cat":
                return _hangman_update(await callready.show_phrasebook_cat(db, profile, params.get("cat", "")))
            if method == "callready_practice_topic":
                return _hangman_update(await callready.show_topic(db, profile, _int(params.get("topic", ""))))
            if method == "callready_next_task":
                return _hangman_update(await callready.show_task(
                    db, profile, _int(params.get("topic", "")), _int(params.get("pos", "")),
                ))
            if method == "callready_answer":
                return _hangman_update(await callready.answer(
                    db, profile,
                    _int(params.get("topic", "")),
                    _int(params.get("pos", "")),
                    _int(params.get("answer", "")),
                ))
            if method == "callready_mtest":
                return _hangman_update(await callready.show_mtest(
                    db, profile, params.get("module", ""), _int(params.get("q", "")), _int(params.get("score", "")),
                ))
            if method == "callready_mtest_answer":
                return _hangman_update(await callready.answer_mtest(
                    db, profile, params.get("module", ""),
                    _int(params.get("q", "")), _int(params.get("answer", "")), _int(params.get("score", "")),
                ))
            if method == "callready_btest":
                return _hangman_update(await callready.show_btest(
                    db, profile, params.get("block", ""), _int(params.get("q", "")), _int(params.get("score", "")),
                ))
            if method == "callready_btest_answer":
                return _hangman_update(await callready.answer_btest(
                    db, profile, params.get("block", ""),
                    _int(params.get("q", "")), _int(params.get("answer", "")), _int(params.get("score", "")),
                ))
    except Exception:
        logger.exception("callready_action_failed method=%s", method)
        return _addon_response({"text": "Error processing that action 🤕"})
    logger.info("event=BUTTON_CLICKED callready_unknown method=%r", method)
    return JSONResponse(content={})


async def _handle_leveled_action(chat_data: dict, common: dict, method: str) -> JSONResponse:
    """Клик по кнопкам раздела «English by level»: уровень → тема → тест.

    Все карточки раздела имеют единый cardId «leveled», поэтому навигация обновляет
    карточку на месте через _hangman_update.
    """
    params = _params_dict(common)
    user = chat_data.get("user", {})
    workspace_user_id = user.get("name", "")

    def _int(value: str) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return -1

    try:
        async with AsyncSessionLocal() as db:
            from app.services import leveled

            if not workspace_user_id:
                return _addon_response({"text": "Couldn't identify you 😕"})
            profile = await get_or_create_profile(
                db, workspace_user_id=workspace_user_id,
                email=user.get("email"), display_name=user.get("displayName"),
            )

            if method == "leveled_menu":
                return _hangman_update(await leveled.level_menu(db, profile))
            if method == "leveled_themes":
                return _hangman_update(await leveled.show_themes(db, profile, params.get("level", "")))
            if method == "leveled_theme":
                return _hangman_update(await leveled.show_theme(db, profile, params.get("theme", "")))
            if method == "leveled_progress":
                return _hangman_update(await leveled.show_progress(db, profile))
            if method == "leveled_test":
                return _hangman_update(await leveled.show_test(
                    db, profile, params.get("theme", ""), _int(params.get("q", "")), _int(params.get("score", "")),
                ))
            if method == "leveled_test_answer":
                return _hangman_update(await leveled.answer_test(
                    db, profile, params.get("theme", ""),
                    _int(params.get("q", "")), _int(params.get("answer", "")), _int(params.get("score", "")),
                ))
    except Exception:
        logger.exception("leveled_action_failed method=%s", method)
        return _addon_response({"text": "Error processing that action 🤕"})
    logger.info("event=BUTTON_CLICKED leveled_unknown method=%r", method)
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
                    _fast_cycle_on,
                )
                result = await submit_poll(db, profile, form_inputs)
                if result.get("ok") and message_name:
                    try:
                        poll = await active_weekly_poll(db)
                        if poll is not None:
                            days, times, counts = await poll_counts(db, poll.id)
                            fc = await _fast_cycle_on(db)
                            updated_card = build_weekly_poll_card(
                                days, times, settings.chat_app_audience, counts,
                                show_finish_button=fc, ignore_day_close=fc,
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


async def _handle_finish_voting() -> JSONResponse:
    """Кнопка «Finish voting» (только fast_cycle): ставит флаг, цикл fast_cycle завершает день.

    Саму встречу/рассылки делает run_cycle — иначе задвоим инвайт и напоминания.
    """
    try:
        async with AsyncSessionLocal() as db:
            from app.services.weekly_poll import _fast_cycle_on, get_or_create_config

            if not await _fast_cycle_on(db):
                return _addon_response({"text": "This button is only available in demo mode."})
            cfg = await get_or_create_config(db, "finish_voting_requested", False)
            cfg.value = True
            await db.commit()
    except Exception:
        logger.exception("finish_voting_failed")
        return _addon_response({"text": "Couldn't finish voting — try again."})
    return _addon_response({"text": "Finishing voting — meetup details are on the way! 🗓️"})


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































# Пункты меню рейтингов: (эмодзи, подпись, method). Добавляй новые игры сюда.




def _is_onboarding_command(raw_text: str) -> bool:
    """Пользователь явно просит показать анкету онбординга."""
    lowered = raw_text.lower().strip()
    return any(trigger in lowered for trigger in ("form", "start", "onboarding"))


def _onboarding_response_payload(user_name: str, space: dict) -> dict:
    """Карточка анкеты — только в личку; в группу — текст-подсказка без карточки.

    Явный запрос анкеты («анкета»/«start»/«опрос»…) в группе не должен уводить
    карточку в общий чат: в DM показываем саму анкету, иначе — просим написать
    боту в личку.
    """
    if _space_is_dm(space):
        return _onboarding_card(user_name)
    return {"text": "DM me to fill in the form 🙌"}




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


def build_mode_choice_card(action_url: str) -> dict:
    """Карточка «Choose mode»: demo (быстрый цикл) или orig (обычный режим)."""
    return {
        "cardsV2": [
            {
                "cardId": "modeChoice",
                "card": {
                    "header": {
                        "title": "Choose how to run",
                        "subtitle": "Pick a mode to start EnglishMeetBot",
                    },
                    "sections": [
                        {
                            "widgets": [
                                {
                                    "buttonList": {
                                        "buttons": [
                                            {
                                                "text": "🚀 Demo (fast cycle)",
                                                "onClick": {
                                                    "action": {
                                                        "function": action_url or "choose_mode",
                                                        "parameters": [
                                                            {"key": "method", "value": "choose_mode"},
                                                            {"key": "mode", "value": "demo"},
                                                        ],
                                                    }
                                                },
                                            },
                                            {
                                                "text": "📅 Original (weekly)",
                                                "onClick": {
                                                    "action": {
                                                        "function": action_url or "choose_mode",
                                                        "parameters": [
                                                            {"key": "method", "value": "choose_mode"},
                                                            {"key": "mode", "value": "orig"},
                                                        ],
                                                    }
                                                },
                                            },
                                        ]
                                    }
                                }
                            ]
                        }
                    ],
                },
            }
        ]
    }


async def _handle_choose_mode(chat_data: dict, common: dict) -> JSONResponse:
    """Кнопка выбора режима: demo → быстрый цикл, orig → обычный режим."""
    params = _normalize_params(common.get("parameters"))
    mode = params.get("mode", "")
    space = _extract_space_dict(chat_data)
    space_name = space.get("name", "")

    if mode == "demo":
        try:
            async with AsyncSessionLocal() as db:
                from app.services.mode_control import enable_demo_mode

                await enable_demo_mode(db, space_id=space_name)
            # Онбординг сразу: @упоминание всех в группу + анкета в личку тем, у кого есть DM.
            if space_name:
                await _run_onboarding(space_name, space, force=True)
            from app.scheduler import schedule_fast_cycle, scheduler

            if scheduler is not None:
                from app.services.weekly_poll import get_or_create_config

                async with AsyncSessionLocal() as db:
                    step = int((await get_or_create_config(db, "fast_cycle_seconds", 60)).value or 60)
                schedule_fast_cycle(step)
        except Exception:
            logger.exception("choose_mode_demo_failed")
            return _addon_response({"text": "Couldn't start demo mode."})
        return JSONResponse(content={})

    if mode == "orig":
        try:
            async with AsyncSessionLocal() as db:
                from app.services.mode_control import enable_normal_mode

                await enable_normal_mode(db)
            if space_name:
                await _run_onboarding(space_name, space)
            async with AsyncSessionLocal() as db:
                from app.services.weekly_poll import ensure_weekly_poll, send_weekly_poll_card

                poll = await ensure_weekly_poll(db)
                await send_weekly_poll_card(db, poll)
        except Exception:
            logger.exception("choose_mode_orig_failed")
            return _addon_response({"text": "Couldn't start original mode."})
        return JSONResponse(content={})

    return _addon_response({"text": "Unknown mode."})


async def _send_mode_choice(space_name: str, space: dict) -> None:
    """При добавлении в группу: записать space_id и спросить demo/orig."""
    if not space_name:
        return
    try:
        from app.services.weekly_poll import get_or_create_config

        async with AsyncSessionLocal() as db:
            if not _space_is_dm(space):
                cfg = await get_or_create_config(db, "space_id", space_name)
                if cfg.value != space_name:
                    cfg.value = space_name
                    await db.commit()
    except Exception:
        logger.exception("mode_choice_space_id_failed space=%s", space_name)
        return
    try:
        from app.services.chat_sender import send_message as send_space_message

        card = build_mode_choice_card(settings.chat_app_audience)
        await asyncio.to_thread(
            send_space_message,
            space_name,
            text="How should I run? Pick a mode 👇",
            cards_v2=card["cardsV2"],
        )
    except Exception:
        logger.exception("mode_choice_send_failed space=%s", space_name)


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


async def _run_onboarding(space_name: str, space: dict, force: bool = False) -> dict:
    """Онбординг при добавлении в пространство: анкета в личку, @упоминание в группу.

    space_id в config пишем ТОЛЬКО для группы/комнаты (не DM): джобы ежедневного
    опроса и итогов должны слать в группу, а не в личку. В DM space_id не трогаем.
    Через check_new_members планируем каналы (и помечаем onboarding_invite_sent,
    чтобы фоновый поллинг не прислал приглашение тем же людям повторно):
      - plan["dm"] — уже есть DM с ботом и онбординг не пройден → анкета в личку;
      - plan["mention"] — нет DM → @упоминание в группу с просьбой написать боту.
    force=True — онбордить всех участников (демо fast_cycle).
    Возвращает план: {'dm': [...], 'mention': [...]}.
    """
    from app.messaging import send_message
    from app.schemas import MessagePayload
    from app.services.chat_sender import send_text
    from app.services.space_onboarding import check_new_members
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
            plan = await check_new_members(db, space_name, force=force)
    except Exception:
        # Сбой планирования не должен ронять обработку события
        logger.exception("onboarding_plan_failed space=%s", space_name)
        return plan

    # Анкета в личку тем, у кого уже есть DM с ботом
    for ws in plan["dm"]:
        try:
            await asyncio.to_thread(
                send_message,
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
            await asyncio.to_thread(
                send_text,
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
            if profile.onboarding_completed or profile.onboarding_invite_sent:
                return  # уже онборднут/приглашён — не трогаем
            profile.onboarding_invite_sent = True
            await db.commit()
            if profile.chat_space_id:
                await asyncio.to_thread(
                    send_message,
                    member_name,
                    MessagePayload(text="Hi! Fill in a short form 🙌", card=_onboarding_card("friend")),
                )
            elif space_name:
                await asyncio.to_thread(send_text, space_name, f"<{member_name}> — DM me to fill in the form 👋")
    except Exception:
        logger.exception("member_added_onboarding_failed member=%s", member_name)










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
            if method == "choose_mode":
                return await _handle_choose_mode(chat_data, common)
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
            if method == "finish_voting":
                return await _handle_finish_voting()
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
                "menu_wheel", "menu_callready", "menu_leveled",
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
            if method in (
                "menu_crossword", "crossword_check", "crossword_reveal",
                "crossword_new", "crossword_quit",
            ):
                return await _handle_crossword_action(chat_data, common, method)
            if method in ("wheel_join", "wheel_start", "wheel_spin", "wheel_guess", "wheel_finish"):
                return await _handle_wheel_action(chat_data, common, method)
            if method.startswith("callready_"):
                return await _handle_callready_action(chat_data, common, method)
            if method.startswith("leveled_"):
                return await _handle_leveled_action(chat_data, common, method)
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

            # Выбор режима (demo/orig): показать стартовую карточку вручную.
            if _is_mode_command(raw_text):
                space = _extract_space_dict(chat_data)
                await _send_mode_choice(space.get("name", ""), space)
                return JSONResponse(content={})

            # Инфо о боте — работает и в личке, и в группе.
            if _is_info_command(raw_text):
                space = _extract_space_dict(chat_data)
                return _addon_response(_info_card(_space_is_dm(space)))

            # Курсы английского — только в личке.
            if _is_learn_command(raw_text) and _space_is_dm(_extract_space_dict(chat_data)):
                return await _callready_menu_response(chat_data)
            if _is_leveled_command(raw_text) and _space_is_dm(_extract_space_dict(chat_data)):
                return await _leveled_menu_response(chat_data)

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
            # Спросить demo/orig — режим запускается после ответа, а не сразу.
            await _send_mode_choice(space_name, space)
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
        # Спросить demo/orig — режим запускается после ответа, а не сразу.
        await _send_mode_choice(space_name, space)
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
        if _is_mode_command(raw_text):
            space = event.get("space", {})
            await _send_mode_choice(space.get("name", ""), space)
            return JSONResponse(content={})
        if _is_info_command(raw_text):
            return JSONResponse(content=_info_card(_space_is_dm(event.get("space", {}))))
        if _is_learn_command(raw_text) and _space_is_dm(event.get("space", {})):
            return await _callready_menu_response(event)
        if _is_leveled_command(raw_text) and _space_is_dm(event.get("space", {})):
            return await _leveled_menu_response(event)
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
        if function_name == "choose_mode" or method == "choose_mode":
            params = {}
            for p in action.get("parameters") or []:
                if isinstance(p, dict) and p.get("key"):
                    params[p.get("key")] = p.get("value")
            chat_data = {"user": event.get("user", {}), "space": event.get("space", {})}
            return await _handle_choose_mode(chat_data, {"parameters": params})
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
        if function_name == "finish_voting" or method == "finish_voting":
            return await _handle_finish_voting()
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
            "menu_wheel", "menu_callready", "menu_leveled",
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
        if method in (
            "menu_crossword", "crossword_check", "crossword_reveal",
            "crossword_new", "crossword_quit",
        ):
            return await _handle_crossword_action(event, common, method)
        if method in ("wheel_join", "wheel_start", "wheel_spin", "wheel_guess", "wheel_finish"):
            return await _handle_wheel_action(event, common, method)
        if method.startswith("callready_"):
            return await _handle_callready_action(event, common, method)
        if method.startswith("leveled_"):
            return await _handle_leveled_action(event, common, method)
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
