"""Игра Wordle — соло в личке против бота.

Бот загадывает английское слово из 5 букв (wordle_bank.WORDLE_WORDS), игрок
угадывает слово целиком (поле «Your word»). После каждой попытки буквы
подсвечиваются:
- 🟩 буква на месте;
- 🟨 буква есть в слове, но на другом месте;
- ⬛ буквы в слове нет.

У игрока 6 попыток. Баллы: победа с 1-й попытки = +6, со 2-й = +5 … с 6-й = +1,
проигрыш = 0 (без штрафа). Состояние живёт в game_sessions.state (JSONB),
`game_type = 'wordle'`, поэтому переживает рестарты. Рейтинг — отдельная таблица
wordle_scores (НЕ общий leaderboard_ledger).

Вход:
- start_wordle        — создать партию (кнопка «Wordle» из меню ДМ-игр).
- guess               — попытка угадать слово (поле «Your word»).
- new_game / quit_game — закрыть активную партию и начать заново / просто выйти.
- leaderboard_response — топ-N.
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Config, GameSession, Profile, WordleScore
from app.services import party_games
from app.services.wordle_bank import random_wordle_word

logger = logging.getLogger(__name__)

MAX_GUESSES = 6
WORD_LENGTH = 5

GREEN = "🟩"
YELLOW = "🟨"
BLACK = "⬛"
EMPTY = "⬜"


def _action_url() -> str:
    """URL эндпоинта — в add-on режиме кнопка доставляет клик только при function=URL."""
    return get_settings().chat_app_audience or "wordle"


async def _load_wordle_config(db: AsyncSession) -> dict:
    """Параметры Wordle из config с fallback на дефолты."""
    rows = (await db.execute(select(Config.key, Config.value))).all()
    cfg = {k: v for k, v in rows}

    def _int(key: str, default: int) -> int:
        v = cfg.get(key)
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    return {
        "max_guesses": _int("wordle_max_guesses", MAX_GUESSES),
        "word_length": _int("wordle_word_length", WORD_LENGTH),
    }


# ---------------------------------------------------------------------------
# Чистые хелперы
# ---------------------------------------------------------------------------

def _feedback(target: str, guess: str) -> str:
    """Подсветка догадки: 'g' = зелёный, 'y' = жёлтый, 'b' = серый.

    Корректно обрабатывает повторяющиеся буквы (классический алгоритм Wordle):
    сначала отмечаем точные совпадения (зелёные), затем по остатку — жёлтые.
    """
    res = ["b"] * len(target)
    remaining: dict[str, int] = {}
    for ch in target:
        remaining[ch] = remaining.get(ch, 0) + 1
    for i in range(len(target)):
        if guess[i] == target[i]:
            res[i] = "g"
            remaining[guess[i]] -= 1
    for i in range(len(target)):
        if res[i] == "g":
            continue
        ch = guess[i]
        if remaining.get(ch, 0) > 0:
            res[i] = "y"
            remaining[ch] -= 1
    return "".join(res)


def _emoji_row(feedback: str) -> str:
    return "".join({"g": GREEN, "y": YELLOW, "b": BLACK}.get(c, BLACK) for c in feedback)


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


def _normalize_guess(text: str) -> str:
    """Оставить только латинские буквы (строчные); кириллицу и прочее отбрасываем."""
    return "".join(ch for ch in (text or "").lower() if ch.isascii() and ch.isalpha())


def _has_cyrillic(text: str) -> bool:
    """Есть ли в вводе кириллические буквы (пользователь печатал в русской раскладке)."""
    low = (text or "").lower()
    return any("а" <= ch <= "я" or ch == "ё" for ch in low)


def _win_points(guesses_used: int, max_guesses: int) -> int:
    """Баллы за победу: меньше попыток = больше баллов (6..1)."""
    return max_guesses - guesses_used + 1


# ---------------------------------------------------------------------------
# Карточки
# ---------------------------------------------------------------------------

def _history_text(state: dict, word_length: int) -> str:
    """Строки прошлых попыток + пустые строки на оставшиеся ходы."""
    guesses = state.get("guesses", [])
    max_guesses = state.get("max_guesses", MAX_GUESSES)
    lines = []
    for word, fb in guesses:
        lines.append(f"{word.upper()}\n{_emoji_row(fb)}")
    for _ in range(max(0, max_guesses - len(guesses))):
        lines.append(EMPTY * word_length)
    return "\n\n".join(lines) if lines else EMPTY * word_length


def build_wordle_card(state: dict, game_id: int) -> dict:
    """Карточка игры (cardId «wordle») — обновляется на месте после каждой попытки."""
    word_length = state.get("word_length", WORD_LENGTH)
    guesses = state.get("guesses", [])
    max_guesses = state.get("max_guesses", MAX_GUESSES)
    remaining = max_guesses - len(guesses)

    body = (
        f"Guess the {word_length}-letter word!\n"
        f"🟩 correct spot · 🟨 wrong spot · ⬛ not in word\n\n"
        f"{_history_text(state, word_length)}"
    )

    return {"cardsV2": [{
        "cardId": "wordle",
        "card": {
            "header": {
                "title": "Wordle 🟩",
                "subtitle": f"Guess {len(guesses) + 1}/{max_guesses} · {remaining} left",
            },
            "sections": [{"widgets": [
                {"textParagraph": {"text": body}},
                {
                    "textInput": {
                        "name": "word",
                        "label": "Your word",
                        "type": "SINGLE_LINE",
                        "hintText": f"{word_length} English letters",
                    }
                },
                {"buttonList": {"buttons": [
                    _btn("🎯 Guess", "wordle_guess", game_id),
                    _btn("🆕 New game", "wordle_new", game_id),
                    _btn("🛑 Quit", "wordle_quit", game_id),
                ]}},
            ]}],
        },
    }]}


def _result_card(state: dict, game_id: int, won: bool, delta: int) -> dict:
    """Финальная карточка (победа/поражение) с кнопками «Новая игра»/«Рейтинг»."""
    word = state.get("word", "").upper()
    guesses = state.get("guesses", [])
    max_guesses = state.get("max_guesses", MAX_GUESSES)
    board = "\n\n".join(f"{w.upper()}\n{_emoji_row(fb)}" for w, fb in guesses)

    if won:
        title = "🎉 You got it!"
        body = f"{board}\n\nWord: **{word}** in {len(guesses)}/{max_guesses}.\n\n+{delta} to the Wordle rating 🏆"
    else:
        title = "💔 Out of guesses"
        body = f"{board}\n\nThe word was **{word}**.\n\nNo points this time — try again!"

    return {"cardsV2": [{
        "cardId": "wordle",
        "card": {
            "header": {"title": title, "subtitle": "Wordle"},
            "sections": [{"widgets": [
                {"textParagraph": {"text": body}},
                {"buttonList": {"buttons": [
                    _btn("🆕 New game", "wordle_new", game_id),
                ]}},
            ]}],
        },
    }]}


# ---------------------------------------------------------------------------
# Игровой цикл
# ---------------------------------------------------------------------------

async def _get_or_create_score(db: AsyncSession, profile_id: int) -> WordleScore:
    row = (
        await db.execute(select(WordleScore).where(WordleScore.profile_id == profile_id))
    ).scalar_one_or_none()
    if row is None:
        row = WordleScore(profile_id=profile_id, games_played=0, wins=0, points=0, best_guesses=0)
        db.add(row)
        await db.flush()
    return row


async def start_wordle(db: AsyncSession, space_name: str, profile: Profile) -> dict:
    """Создать партию: загадать слово и вернуть карточку."""
    if await party_games.get_active_game(db, space_name) is not None:
        return {"text": "A game is already running — finish it or press «🆕 New game»."}

    word = random_wordle_word()
    if not word:
        return {"text": "No words available 🤷"}

    cfg = await _load_wordle_config(db)
    state = {
        "game": "wordle",
        "word": word,
        "guesses": [],
        "max_guesses": cfg["max_guesses"],
        "word_length": cfg["word_length"],
    }
    session = await party_games._start_session(db, space_name, "wordle", "Wordle", state)
    return build_wordle_card(state, session.id)


async def _active_wordle_session(db: AsyncSession, game_id: int) -> GameSession | None:
    """Активная wordle-сессия по id, иначе None."""
    session = await db.get(GameSession, game_id)
    if session is None or session.game_type != "wordle" or session.status != "active":
        return None
    return session


async def guess(db: AsyncSession, game_id: int, profile: Profile, text: str) -> dict:
    """Попытка угадать слово: проверить длину, подсветить буквы, подбить исход."""
    session = await _active_wordle_session(db, game_id)
    if session is None:
        return {"text": "Game not found 🤷"}
    state = session.state or {}

    word = state.get("word", "")
    if not word:
        return {"text": "Game not found 🤷"}

    if _has_cyrillic(text):
        return {
            "text": "⚠️ Type in English letters!",
            "cardsV2": build_wordle_card(state, game_id),
        }

    raw = _normalize_guess(text)
    word_length = state.get("word_length", WORD_LENGTH)
    if len(raw) != word_length:
        return {
            "text": f"Enter exactly {word_length} letters 😊",
            "cardsV2": build_wordle_card(state, game_id),
        }

    fb = _feedback(word, raw)
    guesses = list(state.get("guesses", []))
    guesses.append([raw, fb])
    state["guesses"] = guesses
    max_guesses = state.get("max_guesses", MAX_GUESSES)
    guess_count = len(guesses)

    if raw == word:
        delta = _win_points(guess_count, max_guesses)
        score = await _get_or_create_score(db, profile.id)
        score.games_played += 1
        score.wins += 1
        score.points += delta
        if score.best_guesses == 0 or guess_count < score.best_guesses:
            score.best_guesses = guess_count

        state["won"] = True
        session.state = state
        session.status = "finished"
        await db.commit()
        return _result_card(state, session.id, won=True, delta=delta)

    if guess_count >= max_guesses:
        score = await _get_or_create_score(db, profile.id)
        score.games_played += 1

        state["won"] = False
        session.state = state
        session.status = "finished"
        await db.commit()
        return _result_card(state, session.id, won=False, delta=0)

    session.state = state
    await db.commit()
    return build_wordle_card(state, session.id)


async def new_game(db: AsyncSession, game_id: int, profile: Profile) -> dict:
    """Закрыть активную партию в space и начать новую."""
    session = await db.get(GameSession, game_id)
    space_name = session.space_name if session else ""
    if not space_name:
        return {"text": "Game not found 🤷"}

    active = await party_games.get_active_game(db, space_name)
    if active is not None:
        active.status = "cancelled"
        await db.commit()

    return await start_wordle(db, space_name, profile)


async def quit_game(db: AsyncSession, game_id: int, profile: Profile) -> dict:
    """Просто закрыть активную партию без изменения счёта."""
    session = await db.get(GameSession, game_id)
    if session is None:
        return {"text": "Game not found 🤷"}
    session.status = "cancelled"
    await db.commit()
    return {"text": "Game closed. Press «🟩 Wordle» in the games menu to play again."}


# ---------------------------------------------------------------------------
# Лидерборд
# ---------------------------------------------------------------------------

async def leaderboard_response(db: AsyncSession) -> dict:
    """Топ-20 Wordle с пьедесталом топ-3."""
    rows = (
        await db.execute(
            select(WordleScore, Profile.user_name, Profile.workspace_user_id)
            .join(Profile, WordleScore.profile_id == Profile.id)
            .order_by(WordleScore.points.desc(), WordleScore.wins.desc())
            .limit(20)
        )
    ).all()

    if not rows:
        return {"text": "Nobody has played Wordle yet 🤷"}

    entries = [
        (name or ws or f"Player {score.profile_id}", score.wins, score.games_played,
         score.best_guesses, score.points)
        for score, name, ws in rows
    ]

    medals = ("🥇", "🥈", "🥉")
    lines = []
    for i, (name, _w, _g, _b, pts) in enumerate(entries[:3]):
        indent = ("        ", "  ", "              ")[i]
        lines.append(f"{indent}{medals[i]} {name} — {pts}")
    body = "\n".join(lines)

    rest = [
        f"{i}. {name} — {pts} ({wins} wins, best {best}/{MAX_GUESSES})"
        for i, (name, wins, _g, best, pts) in enumerate(entries[3:], start=4)
    ]
    if rest:
        body += "\n\n" + "\n".join(rest)

    return {"cardsV2": [{
        "cardId": "wordleLeaderboard",
        "card": {
            "header": {
                "title": "🟩 Wordle rating",
                "subtitle": "Win in 1 → +6 … in 6 → +1",
            },
            "sections": [
                {"widgets": [{"textParagraph": {"text": body}}]},
            ],
        },
    }]}
