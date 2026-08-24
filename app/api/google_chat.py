# app/api/google_chat.py
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from google.auth.transport import requests as grequests
from google.oauth2 import id_token
import logging

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
        return {"text": "Спасибо! Ответы и голоса сохранены. 🤝"}
    if result.get("reason") == "closed":
        return {"text": "Опрос на эту неделю уже закрыт — встретимся на следующей! ⏳"}
    return {"text": "Не получилось сохранить ответы — заполни хотя бы что-нибудь и нажми «Отправить»."}


async def _submit_daily_poll(chat_data: dict, common: dict, message_name: str | None = None) -> JSONResponse:
    """Обработать клик по кнопке ежедневного опроса.

    При успехе и наличии message_name — обновляет карточку счётчиками
    (updateMessageAction), иначе/при закрытии — текст (createMessageAction).
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
                    active_daily_poll, build_daily_poll_card, poll_counts, submit_poll, today,
                )
                result = await submit_poll(db, profile, form_inputs)
                if result.get("ok") and message_name:
                    try:
                        poll = await active_daily_poll(db, today())
                        if poll is not None:
                            slots, counts = await poll_counts(db, poll.id)
                            updated_card = build_daily_poll_card(
                                slots, settings.chat_app_audience, counts,
                            )
                    except Exception:
                        # голос уже записан — карточку просто не обновим
                        logger.exception("daily_poll_card_build_failed")
        except Exception:
            logger.exception("daily_poll_submit_failed")
            result = {"ok": False, "reason": "db_error"}
    if result.get("ok"):
        if updated_card is not None and message_name:
            return _addon_update_message(message_name, updated_card)
        return _addon_response({"text": "Спасибо, учёл! 🙌"})
    if result.get("reason") == "closed":
        return _addon_response({"text": "Голосование уже закрыто — итог объявлен."})
    return _addon_response({"text": "Не получилось сохранить — попробуй ещё раз."})


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
        return _addon_response({"text": "Спасибо за ответ! 🎉"})
    return _addon_response({"text": "Напиши ответ и нажми «Отправить ответ»."})


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
                    MessagePayload(text="Привет! Заполни короткую анкету 🙌", card=_onboarding_card("друг")),
                )
            elif space_name:
                send_text(space_name, f"<{member_name}> — напиши мне в личку, чтобы пройти анкету 👋")
    except Exception:
        logger.exception("member_added_onboarding_failed member=%s", member_name)


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
            if method == "submit_weekly_question":
                return await _submit_weekly_question(chat_data, common)
            if method == "submit_weekly_poll":
                return _addon_response(await _submit_weekly_poll(chat_data, common))
            if method == "submit_daily_poll":
                message_name = (chat_data.get("buttonClickedPayload", {}).get("message") or {}).get("name")
                return await _submit_daily_poll(chat_data, common, message_name=message_name)
            if method == "checkin_present":
                return await _handle_checkin_present(chat_data, common)
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
        user_name = event.get("user", {}).get("displayName", "друг")
        message = event.get("message", {})
        raw_text = (message.get("text") or message.get("argumentText") or "").strip()
        logger.info("event=MESSAGE format=classic user=%s text=%r", user_name, raw_text)
        if not raw_text:
            return JSONResponse(content={})
        if _is_onboarding_command(raw_text):
            space = event.get("space", {})
            return JSONResponse(content=_onboarding_response_payload(user_name, space))
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
        logger.info("event=CARD_CLICKED format=classic function=%s method=%s", function_name, method)
        return JSONResponse(content={})

    # REMOVED_FROM_SPACE и неизвестные типы — тихо отвечаем пустым JSON
    logger.info("event=unhandled type=%r keys=%s", event_type, sorted(event.keys()))
    return JSONResponse(content={})
