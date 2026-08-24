# app/services/games/guesspionage.py
"""Guesspionage: угадай процент. Вопрос → число называющего → «выше/ниже» → очки."""
import logging

from app.messaging import send_message as send_dm
from app.schemas import MessagePayload
from app.services.chat_sender import send_message as send_to_space
from app.services.form_parsing import parse_form_inputs
from app.services.games.scores import award_points
from app.services.games.session import GameManager
from app.services.onboarding import get_or_create_profile

logger = logging.getLogger(__name__)

GUESS_QUESTIONS: list[tuple[str, int]] = [
    ("What percentage of people have peed in a shower?", 70),
    ("What percentage of people wear socks when they sleep?", 16),
    ("What percentage of people have Googled themselves?", 65),
    ("What percentage of people prefer smooth peanut butter to crunchy?", 62),
    ("What percentage of people believe there are aliens?", 85),
]


def score_round(true_pct: int, guess: int, higher: set[str], lower: set[str], guesser: str) -> dict[str, int]:
    """Очки за раунд: {user_id: positive_points}.

    Называющий — по близости (≤5 → 3, ≤10 → 2, иначе 1); остальные +1 за верное направление.
    """
    result: dict[str, int] = {}
    diff = abs(guess - true_pct)
    result[guesser] = 3 if diff <= 5 else (2 if diff <= 10 else 1)
    for voter in higher:
        if guess < true_pct:
            result[voter] = 1
    for voter in lower:
        if guess > true_pct:
            result[voter] = 1
    return result


def build_guess_card(question: str, action_url: str, space_name: str) -> dict:
    """Карточка для называющего (в личку): поле процента + кнопка «Отправить».

    В параметрах кнопки — space_name группы, чтобы по клику в личке найти сессию.
    """
    return {
        "cardsV2": [
            {
                "cardId": "guesspionage_guess",
                "card": {
                    "header": {"title": "Твой процент", "subtitle": question},
                    "sections": [
                        {"widgets": [{"textInput": {"name": "guess", "label": "Твой процент (0–100)"}}]},
                        {
                            "widgets": [
                                {
                                    "buttonList": {
                                        "buttons": [
                                            {
                                                "text": "Отправить",
                                                "onClick": {
                                                    "action": {
                                                        "function": action_url,
                                                        "parameters": [
                                                            {"key": "method", "value": "submit_guesspionage_guess"},
                                                            {"key": "space", "value": space_name},
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


def build_higher_lower_card(question: str, guess: int, action_url: str) -> dict:
    """Карточка «выше/ниже» для группы."""
    return {
        "cardsV2": [
            {
                "cardId": "guesspionage_vote",
                "card": {
                    "header": {
                        "title": question,
                        "subtitle": f"Называющий считает: {guess}%. Правда выше или ниже?",
                    },
                    "sections": [
                        {
                            "widgets": [
                                {
                                    "buttonList": {
                                        "buttons": [
                                            {
                                                "text": "Выше ⬆️",
                                                "onClick": {
                                                    "action": {
                                                        "function": action_url,
                                                        "parameters": [
                                                            {"key": "method", "value": "guesspionage_higher_lower"},
                                                            {"key": "choice", "value": "higher"},
                                                        ],
                                                    }
                                                },
                                            },
                                            {
                                                "text": "Ниже ⬇️",
                                                "onClick": {
                                                    "action": {
                                                        "function": action_url,
                                                        "parameters": [
                                                            {"key": "method", "value": "guesspionage_higher_lower"},
                                                            {"key": "choice", "value": "lower"},
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


def start_guesspionage(session, space_name: str, action_url: str) -> dict:
    """Запустить раунд: взять первый вопрос, назначить называющего, отправить карточку в личку."""
    question, true_pct = GUESS_QUESTIONS[0]
    guesser = session.players[0]
    session.state.update(
        {
            "question": question,
            "true_pct": true_pct,
            "guesser": guesser,
            "guess": None,
            "higher": set(),
            "lower": set(),
        }
    )
    send_dm(
        guesser,
        MessagePayload(
            text="Твой ход — напиши процент 👇",
            card=build_guess_card(question, action_url, space_name),
        ),
    )
    return {"text": f"{question}\n\nНазывающий, напиши свой процент — карточка у тебя в личке 🤫"}


def submit_guess(session, user_id: str, form_inputs: dict, space_name: str, action_url: str) -> dict:
    """Принять число называющего и огласить его группе (карточка «выше/ниже»)."""
    values = parse_form_inputs(form_inputs).get("guess", [])
    if not values:
        return {"text": "Напиши число и нажми «Отправить»."}
    try:
        guess = int(values[0])
    except ValueError:
        return {"text": "Это не число — напиши процент цифрами (0–100)."}
    if not 0 <= guess <= 100:
        return {"text": "Процент должен быть от 0 до 100."}
    session.state["guess"] = guess
    card = build_higher_lower_card(session.state["question"], guess, action_url)
    try:
        send_to_space(space_name, text="Называющий написал свой процент. Голосуем!", cards_v2=card["cardsV2"])
    except Exception:
        logger.exception("guesspionage_reveal_failed")
    return {"text": "Принято! 🎯 Остальные уже голосуют «выше/ниже»."}


async def vote(db, session, user_id: str, choice: str, space_name: str) -> dict | None:
    """Записать голос; когда проголосовали все, кроме называющего, — подсчёт и очки."""
    state = session.state
    guesser = state["guesser"]
    if user_id == guesser:
        return {"text": "Называющий не голосует."}
    state["higher"].discard(user_id)
    state["lower"].discard(user_id)
    (state["higher"] if choice == "higher" else state["lower"]).add(user_id)
    voters = [p for p in session.players if p != guesser]
    if len(state["higher"]) + len(state["lower"]) < len(voters):
        return None  # ждём остальных

    score = score_round(state["true_pct"], state["guess"], state["higher"], state["lower"], guesser)
    for user, points in score.items():
        profile = await get_or_create_profile(db, workspace_user_id=user)
        await award_points(db, profile.id, points, "guesspionage")
    GameManager.end(space_name)
    lines = [f"{session.names.get(u, u)}: +{p}" for u, p in score.items()]
    return {"text": f"Правильный ответ: {state['true_pct']}%\n\n" + "\n".join(lines)}
