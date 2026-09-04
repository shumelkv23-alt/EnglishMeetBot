"""Игра «Словесный пазл» (Word Puzzle) — соло в личке.

Бот даёт английскую фразу, разбитую на перемешанные куски (chunks). Игрок вводит
номера кусков в правильном порядке — как пазл, но со словами. Очки НЕ начисляются.
Состояние живёт в game_sessions.state (JSONB), `game_type = 'word_puzzle'`.

Вход:
- start_word_puzzle — создать партию (кнопка «Word puzzle» из меню ДМ-игр).
- check            — проверить порядок (поле «Your order», напр. «3 1 2»).
- new_game         — закрыть активную партию и взять новую фразу.
"""
import logging
import random

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import GameSession, Profile
from app.services.games import party_games
from app.services.games.banks.word_puzzle_bank import random_word_puzzle

logger = logging.getLogger(__name__)


def _action_url() -> str:
    """URL эндпоинта — в add-on режиме кнопка доставляет клик только при function=URL."""
    return get_settings().chat_app_audience or "word_puzzle"


def _btn(text: str, method: str, game_id: int) -> dict:
    return {
        "text": text,
        "onClick": {"action": {
            "function": _action_url(),
            "parameters": [
                {"key": "method", "value": method},
                {"key": "game_id", "value": str(game_id)},
            ],
        }},
    }


def _normalize(text: str) -> str:
    """Свернуть регистр и пробелы для сравнения (пунктуация остаётся)."""
    return " ".join((text or "").lower().split())


def _parse_order(text: str) -> list[int]:
    """Разобрать «3 1 2» / «3,1,2» в список индексов; пусто при нечисловом вводе."""
    tokens = (text or "").replace(",", " ").split()
    out: list[int] = []
    for t in tokens:
        if not t.isdigit():
            return []
        out.append(int(t))
    return out


def build_word_puzzle_card(state: dict, game_id: int) -> dict:
    """Карточка игры (cardId «wordPuzzle») — нумерованные куски + поле для ответа."""
    shuffled = state.get("shuffled", [])
    n = len(shuffled)
    lines = [f"{i + 1}. {chunk}" for i, chunk in enumerate(shuffled)]
    example = " ".join(str(i) for i in range(n, 0, -1))
    body = (
        "Put the pieces in the right order.\n\n"
        + "\n".join(lines)
        + f'\n\nType all {n} numbers in order (e.g. "{example}").'
    )

    return {"cardsV2": [{
        "cardId": "wordPuzzle",
        "card": {
            "header": {"title": "Word Puzzle 🧩", "subtitle": "Arrange the pieces"},
            "sections": [{"widgets": [
                {"textParagraph": {"text": body}},
                {
                    "textInput": {
                        "name": "order",
                        "label": "Your order",
                        "type": "SINGLE_LINE",
                        "hintText": f'e.g. "{example}"',
                    }
                },
                {"buttonList": {"buttons": [
                    _btn("✅ Check", "word_puzzle_check", game_id),
                    _btn("🆕 New puzzle", "word_puzzle_new", game_id),
                ]}},
            ]}],
        },
    }]}


def _result_card(state: dict, game_id: int, correct: bool, assembled: str) -> dict:
    """Финальная карточка: правильная фраза (+ попытка игрока, если ошибся)."""
    target = state.get("target", "")
    if correct:
        title = "🎉 Correct!"
        body = f"Nicely put together:\n\n**{target}**"
    else:
        title = "🤔 Not quite"
        body = f"You wrote: _{assembled or '…'}_\n\nThe right order was:\n\n**{target}**"

    return {"cardsV2": [{
        "cardId": "wordPuzzle",
        "card": {
            "header": {"title": title, "subtitle": "Word Puzzle"},
            "sections": [{"widgets": [
                {"textParagraph": {"text": body}},
                {"buttonList": {"buttons": [
                    _btn("🆕 New puzzle", "word_puzzle_new", game_id),
                ]}},
            ]}],
        },
    }]}


async def start_word_puzzle(db: AsyncSession, space_name: str, profile: Profile) -> dict:
    """Создать партию: взять фразу, перемешать куски и вернуть карточку."""
    if await party_games.get_active_game(db, space_name) is not None:
        return {"text": "A game is already running — finish it or press «🆕 New puzzle»."}

    chunks = random_word_puzzle()
    shuffled = random.sample(chunks, len(chunks))
    state = {
        "game": "word_puzzle",
        "target": " ".join(chunks),
        "shuffled": shuffled,
    }
    session = await party_games._start_session(db, space_name, "word_puzzle", "Word Puzzle", state)
    if session is None:
        return {"text": "A game is already running — finish it first."}
    return build_word_puzzle_card(state, session.id)


async def _active_session(db: AsyncSession, game_id: int) -> GameSession | None:
    """Активная word_puzzle-сессия по id, иначе None."""
    session = await db.get(GameSession, game_id)
    if session is None or session.game_type != "word_puzzle" or session.status != "active":
        return None
    return session


async def check(db: AsyncSession, game_id: int, profile: Profile, text: str) -> dict:
    """Проверить порядок: собрать фразу по номерам и сравнить с оригиналом."""
    session = await _active_session(db, game_id)
    if session is None:
        return {"text": "Game not found 🤷"}
    state = session.state or {}

    shuffled = state.get("shuffled", [])
    target = state.get("target", "")
    n = len(shuffled)

    order = _parse_order(text)
    if not order or sorted(order) != list(range(1, n + 1)):
        return {
            "text": f"Enter all numbers 1–{n} exactly once, e.g. «{' '.join(str(i) for i in range(n, 0, -1))}»",
            "cardsV2": build_word_puzzle_card(state, game_id),
        }

    assembled = " ".join(shuffled[i - 1] for i in order)
    correct = _normalize(assembled) == _normalize(target)

    session.status = "finished"
    await db.commit()
    return _result_card(state, session.id, correct, assembled)


async def new_game(db: AsyncSession, game_id: int, profile: Profile) -> dict:
    """Закрыть активную партию в space и взять новую фразу."""
    session = await db.get(GameSession, game_id)
    space_name = session.space_name if session else ""
    if not space_name:
        return {"text": "Game not found 🤷"}

    active = await party_games.get_active_game(db, space_name)
    if active is not None:
        active.status = "cancelled"
        await db.commit()

    return await start_word_puzzle(db, space_name, profile)
