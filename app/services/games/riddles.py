"""Игра «Riddles» (Загадки) — соло в личке.

Бот показывает английскую загадку, игрок печатает ответ. Проверка: точное
совпадение по нормализованной строке (регистр/артикли/знаки), затем LLM-судья
ловит синонимы и перефразировки. Очки НЕ ведутся в общий рейтинг — внутри партии
считается серия (solved/seen/streak/best). Состояние живёт в game_sessions.state,
`game_type = 'riddles'`.

Вход:
- start       — создать партию (кнопка «Riddles» из меню ДМ-игр).
- check       — проверить ответ (поле «answer»).
- hint        — показать подсказку к текущей загадке.
- reveal      — сдаться: показать ответ, перейти дальше.
- next_riddle — следующая загадка (серия сохраняется).
- finish      — завершить и показать итог сессии.
"""
import logging
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import GameSession, Profile
from app.services.games import party_games
from app.services.games.games_llm import judge_riddle_answer
from app.services.games.banks.riddles_bank import random_riddle

logger = logging.getLogger(__name__)


def _action_url() -> str:
    """URL эндпоинта — в add-on режиме кнопка доставляет клик только при function=URL."""
    return get_settings().chat_app_audience or "riddles"


def _btn(text: str, method: str, game_id: int | None = None) -> dict:
    parameters = [{"key": "method", "value": method}]
    if game_id is not None:
        parameters.append({"key": "game_id", "value": str(game_id)})
    return {
        "text": text,
        "onClick": {"action": {"function": _action_url(), "parameters": parameters}},
    }


def _normalize(text: str) -> str:
    """Свернуть ответ: нижний регистр, только буквы/цифры, без артиклей."""
    lowered = re.sub(r"[^a-z0-9 ]", " ", (text or "").lower())
    words = [w for w in lowered.split() if w]
    if words and words[0] in ("a", "an", "the"):
        words = words[1:]
    return " ".join(words)


def _new_state(riddle: dict) -> dict:
    return {
        "game": "riddles",
        "riddle": riddle["riddle"],
        "answer": riddle["answer"],
        "hint": riddle.get("hint", ""),
        "solved": 0,
        "seen": 0,
        "streak": 0,
        "best": 0,
        "hint_shown": False,
    }


def _score_line(state: dict) -> str:
    return (
        f"✅ Solved {state.get('solved', 0)}   ·   "
        f"👀 Seen {state.get('seen', 0)}   ·   "
        f"🔥 Streak {state.get('streak', 0)}"
    )


def build_card(state: dict, game_id: int) -> dict:
    """Карточка игры (cardId «riddles») — загадка + поле ответа + серия."""
    num = state.get("seen", 0) + 1
    riddle = state.get("riddle", "")

    parts = [f"**Riddle {num}**\n\n{riddle}"]
    if state.get("hint_shown") and state.get("hint"):
        parts.append(f"💡 Hint: _{state['hint']}_")
    parts.append(_score_line(state))
    body = "\n\n".join(parts)

    return {"cardsV2": [{
        "cardId": "riddles",
        "card": {
            "header": {"title": "Riddles 🤔", "subtitle": "Guess the answer"},
            "sections": [{"widgets": [
                {"textParagraph": {"text": body}},
                {
                    "textInput": {
                        "name": "answer",
                        "label": "Your answer",
                        "type": "SINGLE_LINE",
                        "hintText": "Type the answer",
                    }
                },
                {"buttonList": {"buttons": [
                    _btn("✅ Check", "riddle_check", game_id),
                    _btn("💡 Hint", "riddle_hint", game_id),
                    _btn("🔍 Give up", "riddle_reveal", game_id),
                    _btn("🛑 Finish", "riddle_finish", game_id),
                ]}},
            ]}],
        },
    }]}


def _result_card(state: dict, game_id: int, correct: bool, guess: str) -> dict:
    """Карточка после проверки/сдачи: ответ + серия + переход дальше."""
    riddle = state.get("riddle", "")
    answer = state.get("answer", "")

    if correct:
        title = "🎉 Correct!"
        note = f"The answer is **{answer}**."
    else:
        title = "🔍 The answer was…"
        guess_part = f"You said: _{guess}_\n" if guess else ""
        note = f"{guess_part}The answer: **{answer}**"

    body = f"{riddle}\n\n{note}\n\n{_score_line(state)}"

    return {"cardsV2": [{
        "cardId": "riddles",
        "card": {
            "header": {"title": title, "subtitle": "Riddles"},
            "sections": [{"widgets": [
                {"textParagraph": {"text": body}},
                {"buttonList": {"buttons": [
                    _btn("🆕 Next riddle", "riddle_next", game_id),
                    _btn("🛑 Finish", "riddle_finish", game_id),
                ]}},
            ]}],
        },
    }]}


def _summary_card(state: dict) -> dict:
    """Итог сессии: решено/увидено/лучшая серия."""
    body = (
        "Session over!\n\n"
        f"Solved: {state.get('solved', 0)}\n"
        f"Seen: {state.get('seen', 0)}\n"
        f"Best streak: {state.get('best', 0)} 🔥"
    )
    return {"cardsV2": [{
        "cardId": "riddles",
        "card": {
            "header": {"title": "Riddles 🤔", "subtitle": "Session summary"},
            "sections": [{"widgets": [
                {"textParagraph": {"text": body}},
                {"buttonList": {"buttons": [
                    _btn("🤔 Play again", "menu_riddles"),
                ]}},
            ]}],
        },
    }]}


async def start(db: AsyncSession, space_name: str, profile: Profile) -> dict:
    """Создать партию: первая загадка из банка + карточка."""
    if await party_games.get_active_game(db, space_name) is not None:
        return {"text": "A game is already running — finish it or press «🛑 Finish»."}

    state = _new_state(random_riddle())
    session = await party_games._start_session(db, space_name, "riddles", "Riddles", state)
    if session is None:
        return {"text": "A game is already running — finish it first."}
    return build_card(state, session.id)


async def _active_session(db: AsyncSession, game_id: int) -> GameSession | None:
    """Активная riddles-сессия по id, иначе None."""
    session = await db.get(GameSession, game_id)
    if session is None or session.game_type != "riddles" or session.status != "active":
        return None
    return session


async def check(db: AsyncSession, game_id: int, profile: Profile, text: str) -> dict:
    """Проверить ответ: точное совпадение → LLM-судья; обновить серию."""
    session = await _active_session(db, game_id)
    if session is None:
        return {"text": "Game not found 🤷"}
    state = session.state or {}

    guess = (text or "").strip()
    if not guess:
        return {"text": "Type your answer 🙂", "cardsV2": build_card(state, game_id)}

    correct = _normalize(guess) == _normalize(state.get("answer", ""))
    if not correct:
        verdict = await judge_riddle_answer(
            state.get("riddle", ""), state.get("answer", ""), guess
        )
        correct = verdict is True

    if correct:
        state["solved"] = state.get("solved", 0) + 1
        state["seen"] = state.get("seen", 0) + 1
        state["streak"] = state.get("streak", 0) + 1
        state["best"] = max(state.get("best", 0), state["streak"])
        session.state = state
        await db.commit()
        return _result_card(state, session.id, True, guess)

    # Неверно: показать подсказку (если есть) и дать попробовать ещё раз.
    state["hint_shown"] = True
    session.state = state
    await db.commit()
    notice = "Not quite — here's a hint 😉" if state.get("hint") else "Not quite — try again 😉"
    return {"text": notice, "cardsV2": build_card(state, session.id)}


async def hint(db: AsyncSession, game_id: int, profile: Profile) -> dict:
    """Кнопка «💡 Hint»: показать подсказку к текущей загадке."""
    session = await _active_session(db, game_id)
    if session is None:
        return {"text": "Game not found 🤷"}
    state = session.state or {}
    state["hint_shown"] = True
    session.state = state
    await db.commit()
    if state.get("hint"):
        return {"text": "Here's a hint 💡", "cardsV2": build_card(state, session.id)}
    return {"text": "No hint for this one — keep guessing 😉", "cardsV2": build_card(state, session.id)}


async def reveal(db: AsyncSession, game_id: int, profile: Profile) -> dict:
    """Сдаться: показать ответ, сбросить серию, оставить партию активной."""
    session = await _active_session(db, game_id)
    if session is None:
        return {"text": "Game not found 🤷"}
    state = session.state or {}
    state["seen"] = state.get("seen", 0) + 1
    state["streak"] = 0
    session.state = state
    await db.commit()
    return _result_card(state, session.id, False, "")


async def next_riddle(db: AsyncSession, game_id: int, profile: Profile) -> dict:
    """Следующая загадка (серия сохраняется)."""
    session = await _active_session(db, game_id)
    if session is None:
        return {"text": "Game not found 🤷"}
    state = session.state or {}

    new_state = _new_state(random_riddle())
    new_state.update({
        "solved": state.get("solved", 0),
        "seen": state.get("seen", 0),
        "streak": state.get("streak", 0),
        "best": state.get("best", 0),
    })
    session.state = new_state
    await db.commit()
    return build_card(new_state, session.id)


async def finish(db: AsyncSession, game_id: int, profile: Profile) -> dict:
    """Завершить партию и показать итог сессии."""
    session = await db.get(GameSession, game_id)
    if session is None:
        return {"text": "Game not found 🤷"}
    state = session.state or {}
    session.status = "finished"
    await db.commit()
    return _summary_card(state)
