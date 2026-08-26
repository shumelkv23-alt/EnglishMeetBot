"""Игра «Две правды, одна ложь» (Two Truths and a Lie) — соло в личке.

Бот выдаёт три утверждения на английском: два правдивых, одно ложное. Игрок
кнопкой (1/2/3) выбирает, какое из них — ложь. Очки НЕ начисляются — это чистая
разминка на чтение/логику. Состояние живёт в game_sessions.state (JSONB),
`game_type = 'two_truths'`, поэтому переживает рестарты приложения.

Вход:
- start_two_truths — создать партию (кнопка «Two truths & a lie» из меню ДМ-игр).
- pick            — выбор утверждения (параметр choice = 1..3).
- new_game        — закрыть активную партию и взять новый набор.
"""
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import GameSession, Profile
from app.services import games
from app.services.games_llm import generate_two_truths_game

logger = logging.getLogger(__name__)


def _action_url() -> str:
    """URL эндпоинта — в add-on режиме кнопка доставляет клик только при function=URL."""
    return get_settings().chat_app_audience or "two_truths"


def _btn(text: str, method: str, game_id: int, **params) -> dict:
    parameters = [
        {"key": "method", "value": method},
        {"key": "game_id", "value": str(game_id)},
    ]
    for key, value in params.items():
        parameters.append({"key": key, "value": str(value)})
    return {
        "text": text,
        "onClick": {"action": {"function": _action_url(), "parameters": parameters}},
    }


def _number_emoji(i: int) -> str:
    return ("1️⃣", "2️⃣", "3️⃣")[i]


def build_two_truths_card(state: dict, game_id: int) -> dict:
    """Карточка игры (cardId «twoTruths») — три утверждения + три кнопки выбора."""
    topic = state.get("topic", "Fun facts")
    statements = state.get("statements", [])
    lines = [f"{_number_emoji(i)}  {s}" for i, s in enumerate(statements)]
    body = (
        f"*{topic}*\n\n"
        "Two of these are true, one is a lie.\n"
        "Which one is the lie?\n\n"
        + "\n\n".join(lines)
    )

    return {"cardsV2": [{
        "cardId": "twoTruths",
        "card": {
            "header": {"title": "Two Truths & a Lie 🤥", "subtitle": "Pick the lie"},
            "sections": [{"widgets": [
                {"textParagraph": {"text": body}},
                {"buttonList": {"buttons": [
                    _btn("1️⃣", "two_truths_pick", game_id, choice=1),
                    _btn("2️⃣", "two_truths_pick", game_id, choice=2),
                    _btn("3️⃣", "two_truths_pick", game_id, choice=3),
                    _btn("🆕 New set", "two_truths_new", game_id),
                ]}},
            ]}],
        },
    }]}


def _result_card(state: dict, game_id: int, choice: int, correct: bool) -> dict:
    """Финальная карточка: какое утверждение было ложью и угадал ли игрок."""
    topic = state.get("topic", "Fun facts")
    statements = state.get("statements", [])
    lie = state.get("lie", 1)
    lie_text = statements[lie - 1] if 0 < lie <= len(statements) else "?"

    if correct:
        title = "🎉 Correct!"
        note = f"Well done — number {lie} was the lie."
    else:
        title = "🤥 Not quite"
        note = f"The lie was number {lie}. You picked {choice}."

    lines = []
    for i, s in enumerate(statements, start=1):
        mark = "❌ the lie" if i == lie else "✅ true"
        lines.append(f"{_number_emoji(i - 1)}  {s}\n      _{mark}_")

    body = f"*{topic}*\n\n{note}\n\n" + "\n\n".join(lines)

    return {"cardsV2": [{
        "cardId": "twoTruths",
        "card": {
            "header": {"title": title, "subtitle": "Two Truths & a Lie"},
            "sections": [{"widgets": [
                {"textParagraph": {"text": body}},
                {"buttonList": {"buttons": [
                    _btn("🆕 New set", "two_truths_new", game_id),
                ]}},
            ]}],
        },
    }]}


async def start_two_truths(db: AsyncSession, space_name: str, profile: Profile) -> dict:
    """Создать партию: сгенерировать набор и вернуть карточку."""
    if await games.get_active_game(db, space_name) is not None:
        return {"text": "A game is already running — finish it or press «🆕 New set»."}

    data = await generate_two_truths_game()
    statements = data.get("statements") or []
    if len(statements) != 3:
        return {"text": "Couldn't build a set 🤷"}

    state = {
        "game": "two_truths",
        "topic": data.get("topic") or "Fun facts",
        "statements": statements,
        "lie": int(data.get("lie", 1)),
    }
    session = await games._start_session(db, space_name, "two_truths", state["topic"], state)
    return build_two_truths_card(state, session.id)


async def _active_session(db: AsyncSession, game_id: int) -> GameSession | None:
    """Активная two_truths-сессия по id, иначе None."""
    session = await db.get(GameSession, game_id)
    if session is None or session.game_type != "two_truths" or session.status != "active":
        return None
    return session


async def pick(db: AsyncSession, game_id: int, profile: Profile, choice: int) -> dict:
    """Выбор утверждения (1..3): сравнить с ложью и показать разгадку."""
    session = await _active_session(db, game_id)
    if session is None:
        return {"text": "Game not found 🤷"}
    state = session.state or {}

    if choice not in (1, 2, 3):
        return {
            "text": "Pick 1, 2 or 3 🤷",
            "cardsV2": build_two_truths_card(state, game_id),
        }

    correct = choice == int(state.get("lie", 1))
    session.status = "finished"
    await db.commit()
    return _result_card(state, session.id, choice, correct)


async def new_game(db: AsyncSession, game_id: int, profile: Profile) -> dict:
    """Закрыть активную партию в space и взять новый набор."""
    session = await db.get(GameSession, game_id)
    space_name = session.space_name if session else ""
    if not space_name:
        return {"text": "Game not found 🤷"}

    active = await games.get_active_game(db, space_name)
    if active is not None:
        active.status = "cancelled"
        await db.commit()

    return await start_two_truths(db, space_name, profile)
