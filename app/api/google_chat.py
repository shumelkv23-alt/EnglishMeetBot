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


def _extract_space_name(chat_data: dict) -> str:
    """Имя пространства из события аддон-формата (несколько запасных путей).

    В DM-событиях workspace-addon space обычно лежит в chat.space.
    """
    for candidate in (
        chat_data.get("space", {}),
        chat_data.get("messagePayload", {}).get("space", {}),
        chat_data.get("buttonClickedPayload", {}).get("space", {}),
        (chat_data.get("messagePayload", {}).get("message", {}) or {}),
    ):
        if isinstance(candidate, dict):
            name = candidate.get("name")
            if isinstance(name, str) and name.startswith("spaces/"):
                return name
    return ""


async def _handle_checkin_present(chat_data: dict, common: dict) -> dict:
    """Кнопка «Я на встрече»: запись self-check-in, если в окне (REQ-9.6)."""
    params = common.get("parameters") or {}
    instance_id = str(params.get("instance", ""))
    user = chat_data.get("user", {})
    workspace_user_id = user.get("name", "")
    result = {"ok": False, "within": False}
    if workspace_user_id and instance_id.isdigit():
        try:
            from app.services.checkin import submit_checkin

            async with AsyncSessionLocal() as db:
                profile = await get_or_create_profile(db, workspace_user_id=workspace_user_id)
                result = await submit_checkin(db, profile, int(instance_id))
        except Exception:
            logger.exception("checkin_submit_failed")
    text = "Ты на встрече! Баллы зачислены 🎉" if result.get("within") else (
        "Кнопка вне окна встречи — отметка не засчитана ⏳"
    )
    return {"text": text}


async def _submit_weekly_poll(chat_data: dict, common: dict) -> dict:
    """Обработать сабмит карточки еженедельного опроса (add-on формат)."""
    form_inputs = common.get("formInputs", {}) or {}
    user = chat_data.get("user", {})
    workspace_user_id = user.get("name", "")
    result = {"ok": False, "reason": "no_user"}
    if workspace_user_id:
        try:
            async with AsyncSessionLocal() as db:
                profile = await get_or_create_profile(
                    db, workspace_user_id=workspace_user_id,
                    email=user.get("email"), display_name=user.get("displayName"),
                    chat_space_id=_extract_space_name(chat_data) or None,
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


async def _submit_daily_poll(chat_data: dict, common: dict) -> dict:
    """Обработать клик по кнопке ежедневного опроса (add-on и classic формат).

    Кнопки карточки шлют время в action.parameters, а не в formInputs —
    перекладываем его в formInputs, чтобы submit_poll нашёл слот по ключу "time".
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
            async with AsyncSessionLocal() as db:
                profile = await get_or_create_profile(
                    db, workspace_user_id=workspace_user_id,
                    email=user.get("email"), display_name=user.get("displayName"),
                    chat_space_id=_extract_space_name(chat_data) or None,
                )
                from app.services.weekly_poll import submit_poll
                result = await submit_poll(db, profile, form_inputs)
        except Exception:
            logger.exception("daily_poll_submit_failed")
            result = {"ok": False, "reason": "db_error"}
    if result.get("ok"):
        return {"text": "Спасибо, учёл! 🙌"}
    if result.get("reason") == "closed":
        return {"text": "Голосование уже закрыто — итог объявлен."}
    return {"text": "Не получилось сохранить — попробуй ещё раз."}


async def _submit_onboarding(user: dict, space_name: str, form_inputs: dict) -> dict:
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
                chat_space_id=space_name or None,
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
                space_name = _extract_space_name(chat_data)
                user = chat_data.get("user", {})
                response_msg = await _submit_onboarding(user, space_name, form_inputs)
                return _addon_response(response_msg)
            if method == "submit_weekly_poll":
                return _addon_response(await _submit_weekly_poll(chat_data, common))
            if method == "submit_daily_poll":
                return _addon_response(await _submit_daily_poll(chat_data, common))
            if method == "checkin_present":
                return _addon_response(await _handle_checkin_present(chat_data, common))
            logger.info("event=BUTTON_CLICKED format=addon method=%r", method)
            return JSONResponse(content={})

        # Пользователь написал сообщение
        if "messagePayload" in chat_data:
            message = chat_data["messagePayload"].get("message", {})
            raw_text = (message.get("argumentText") or message.get("text") or "").strip()
            logger.info("event=MESSAGE format=addon user=%r text=%r", user_name, raw_text)
            if not raw_text:
                return JSONResponse(content={})

            # Явный запрос анкеты — показываем карточку заново
            if _is_onboarding_command(raw_text):
                return _addon_response(_onboarding_card(user_name))

            # Сохраняем профиль и ответ в БД
            user = chat_data.get("user", {})
            workspace_user_id = user.get("name", "")
            if workspace_user_id:
                try:
                    space_name = _extract_space_name(chat_data)
                    async with AsyncSessionLocal() as db:
                        profile = await get_or_create_profile(
                            db,
                            workspace_user_id=workspace_user_id,
                            email=user.get("email"),
                            display_name=user.get("displayName"),
                            chat_space_id=space_name or None,
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
            space_name = chat_data["addedToSpacePayload"].get("space", {}).get("name", "")
            logger.info("event=ADDED_TO_SPACE format=addon user=%r space=%s", user_name, space_name)
            # Регистрируем профиль в момент первого контакта;
            # chat_space_id нужен для проактивных DM-рассылок
            user = chat_data.get("user", {})
            workspace_user_id = user.get("name", "")
            if workspace_user_id:
                try:
                    async with AsyncSessionLocal() as db:
                        await get_or_create_profile(
                            db,
                            workspace_user_id=workspace_user_id,
                            email=user.get("email"),
                            display_name=user.get("displayName"),
                            chat_space_id=space_name or None,
                        )
                except Exception:
                    logger.exception("db_write_failed")
            else:
                logger.warning("added_to_space_without_user_name, db write skipped")
            return _addon_response(_onboarding_card(user_name))

        # Нажали кнопку на карточке (submit анкеты онбординга)
        action = chat_data.get("action", {})
        function_name = action.get("function") or action.get("functionName") or action.get("actionMethodName")
        if function_name == "submit_onboarding":
            form_inputs = chat_data.get("common", {}).get("formInputs", {})
            space_name = _extract_space_name(chat_data)
            user = chat_data.get("user", {})
            response_msg = await _submit_onboarding(user, space_name, form_inputs)
            return _addon_response(response_msg)

        # Прочие события аддон-формата
        logger.info("event=unhandled format=addon chat_keys=%s", sorted(chat_data.keys()))
        return JSONResponse(content={})

    # 3b. Классический формат Chat App (interaction events): type/user/message/space наверху
    event_type = event.get("type")

    if event_type == "ADDED_TO_SPACE":
        user_name = event.get("user", {}).get("displayName", "")
        logger.info("event=ADDED_TO_SPACE format=classic user=%s", user_name)
        return JSONResponse(content=_onboarding_card(user_name or "друг"))

    if event_type == "MESSAGE":
        user_name = event.get("user", {}).get("displayName", "друг")
        message = event.get("message", {})
        raw_text = (message.get("text") or message.get("argumentText") or "").strip()
        logger.info("event=MESSAGE format=classic user=%s text=%r", user_name, raw_text)
        if not raw_text:
            return JSONResponse(content={})
        if _is_onboarding_command(raw_text):
            return JSONResponse(content=_onboarding_card(user_name))
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
            space_name = event.get("space", {}).get("name", "")
            form_inputs = event.get("common", {}).get("formInputs", {})
            response_msg = await _submit_onboarding(user, space_name, form_inputs)
            return _addon_response(response_msg)
        if function_name == "weekly_poll_submit" or method == "submit_weekly_poll":
            user = event.get("user", {})
            space_name = event.get("space", {}).get("name", "")
            form_inputs = event.get("common", {}).get("formInputs", {})
            response_msg = await _submit_weekly_poll(
                {"user": user, "space": {"name": space_name}},
                {"formInputs": form_inputs},
            )
            return _addon_response(response_msg)
        if function_name == "submit_daily_poll" or method == "submit_daily_poll":
            user = event.get("user", {})
            space_name = event.get("space", {}).get("name", "")
            params = {}
            for p in action.get("parameters") or []:
                if isinstance(p, dict) and p.get("key"):
                    params[p.get("key")] = p.get("value")
            form_inputs = event.get("common", {}).get("formInputs", {})
            response_msg = await _submit_daily_poll(
                {"user": user, "space": {"name": space_name}},
                {"formInputs": form_inputs, "parameters": params},
            )
            return _addon_response(response_msg)
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
        logger.info("event=CARD_CLICKED format=classic function=%s method=%s", function_name, method)
        return JSONResponse(content={})

    # REMOVED_FROM_SPACE и неизвестные типы — тихо отвечаем пустым JSON
    logger.info("event=unhandled type=%r keys=%s", event_type, sorted(event.keys()))
    return JSONResponse(content={})
