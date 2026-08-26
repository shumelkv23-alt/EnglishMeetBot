"""Игра «Виселица» (Hangman) — соло в личке против бота.

Бот загадывает английское слово (word_bank.HANGMAN_WORDS) с короткой подсказкой,
игрок угадывает по буквам (поле «Буква») или называет слово целиком (поле
«Целое слово»). Состояние живёт в game_sessions.state (JSONB),
`game_type = 'hangman'`, поэтому переживает рестарты приложения.

Если пользователь вводит кириллицей, ход отклоняется с коротким предупреждением
«пиши английскими буквами» (попытка при этом не тратится).

Лидерборд «Виселицы» — отдельная таблица hangman_scores (НЕ общий
leaderboard_ledger): победа +hangman_win_points, поражение -hangman_lose_points.

Вход:
- start_hangman       — создать партию (кнопка «Виселица» из меню ДМ-игр).
- guess               — ход буквой (поле «Буква»).
- guess_word          — ход словом (поле «Целое слово»).
- new_game            — закрыть активную партию и начать заново.
- leaderboard_response — топ-N с пьедесталом.
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Config, GameSession, HangmanScore, Profile
from app.services import party_games
from app.services.word_bank import random_hangman_word

logger = logging.getLogger(__name__)

# Дефолты (перекрываются значениями из config, см. _load_hangman_config)
HANGMAN_MAX_WRONG = 6
WIN_POINTS = 2
LOSE_POINTS = 3

# Кадры виселицы по количеству неверных попыток (0..6).
# Столбик (вертикальная «|») — на одной колонке на каждой строке, поэтому он
# «не убегает»; человечек висит правее — на конце перекладины «+---+».
GALLOWS = [
    "  +---+\n  |   |\n  |\n  |\n  |\n  |\n=========",
    "  +---+\n  |   |\n  |   O\n  |\n  |\n  |\n=========",
    "  +---+\n  |   |\n  |   O\n  |   |\n  |\n  |\n=========",
    "  +---+\n  |   |\n  |   O\n  |  /|\n  |\n  |\n=========",
    "  +---+\n  |   |\n  |   O\n  |  /|\\\n  |\n  |\n=========",
    "  +---+\n  |   |\n  |   O\n  |  /|\\\n  |  /\n  |\n=========",
    "  +---+\n  |   |\n  |   O\n  |  /|\\\n  |  / \\\n  |\n=========",
]


def _action_url() -> str:
    """URL эндпоинта — в add-on режиме кнопка доставляет клик только при function=URL."""
    return get_settings().chat_app_audience or "hangman"


async def _load_hangman_config(db: AsyncSession) -> dict:
    """Параметры «Виселицы» из config с fallback на дефолты (паттерн _load_config)."""
    rows = (await db.execute(select(Config.key, Config.value))).all()
    cfg = {k: v for k, v in rows}

    def _int(key: str, default: int) -> int:
        v = cfg.get(key)
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    return {
        "max_wrong": _int("hangman_max_wrong", HANGMAN_MAX_WRONG),
        "win_points": _int("hangman_win_points", WIN_POINTS),
        "lose_points": _int("hangman_lose_points", LOSE_POINTS),
    }


# ---------------------------------------------------------------------------
# Чистые хелперы
# ---------------------------------------------------------------------------

def _masked_word(word: str, guessed: set[str]) -> str:
    return " ".join(ch if ch in guessed else "_" for ch in word)


def _is_won(word: str, guessed: set[str]) -> bool:
    return all(ch in guessed for ch in set(word))


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


def _podium_text(entries: list[tuple[str, int, int, int]]) -> str:
    """Пьедестал топ-3: 1-е место сверху по центру, 2-е слева, 3-е справа."""
    medals = ("🥇", "🥈", "🥉")
    lines = []
    for i, (name, _w, _l, pts) in enumerate(entries[:3]):
        indent = ("        ", "  ", "              ")[i]
        lines.append(f"{indent}{medals[i]} {name} — {pts}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Карточки
# ---------------------------------------------------------------------------

def build_hangman_card(state: dict, game_id: int) -> dict:
    """Карточка игры (cardId «hangman») — обновляется на месте после каждого хода."""
    word = state.get("word", "")
    hint = state.get("hint", "")
    guessed = set(state.get("guessed", []))
    wrong = state.get("wrong", [])
    wrong_count = state.get("wrong_count", 0)
    max_wrong = state.get("max_wrong", HANGMAN_MAX_WRONG)
    remaining = max_wrong - wrong_count

    gallows = GALLOWS[min(wrong_count, len(GALLOWS) - 1)]
    masked = _masked_word(word, guessed)
    wrong_text = ", ".join(wrong) if wrong else "—"
    body = (
        f"{gallows}\n\n"
        f"Word:  {masked}\n"
        f"Hint: it's {hint}\n"
        f"Misses ({wrong_count}/{max_wrong}): {wrong_text}"
    )

    return {"cardsV2": [{
        "cardId": "hangman",
        "card": {
            "header": {"title": "Hangman 💀", "subtitle": f"Attempts left: {remaining}"},
            "sections": [{"widgets": [
                {"textParagraph": {"text": body}},
                {
                    "textInput": {
                        "name": "letter",
                        "label": "Letter",
                        "type": "SINGLE_LINE",
                        "hintText": "One English letter",
                    }
                },
                {
                    "textInput": {
                        "name": "word",
                        "label": "Whole word",
                        "type": "SINGLE_LINE",
                        "hintText": "Guess the whole word",
                    }
                },
                {"buttonList": {"buttons": [
                    _btn("🎯 Guess a letter", "hangman_guess", game_id),
                    _btn("🔤 Name the word", "hangman_word_guess", game_id),
                    _btn("🆕 New game", "hangman_new", game_id),
                ]}},
            ]}],
        },
    }]}


def _result_card(state: dict, game_id: int, won: bool, delta: int) -> dict:
    """Финальная карточка (победа/поражение) с кнопкой «Новая игра»."""
    word = state.get("word", "")
    wrong_count = state.get("wrong_count", 0)
    gallows = GALLOWS[min(wrong_count, len(GALLOWS) - 1)]
    if won:
        title = "🎉 You won!"
        body = f"{gallows}\n\nWord: **{word}**\n\nNice! +{delta} to the Hangman rating 🏆"
    else:
        title = "💀 You lost"
        body = f"{gallows}\n\nWord: **{word}**\n\nNot this time. {delta} to the Hangman rating 📉"

    return {"cardsV2": [{
        "cardId": "hangman",
        "card": {
            "header": {"title": title, "subtitle": "Hangman"},
            "sections": [{"widgets": [
                {"textParagraph": {"text": body}},
                {"buttonList": {"buttons": [
                    _btn("🆕 New game", "hangman_new", game_id),
                ]}},
            ]}],
        },
    }]}


# ---------------------------------------------------------------------------
# Игровой цикл
# ---------------------------------------------------------------------------

async def _get_or_create_score(db: AsyncSession, profile_id: int) -> HangmanScore:
    row = (
        await db.execute(select(HangmanScore).where(HangmanScore.profile_id == profile_id))
    ).scalar_one_or_none()
    if row is None:
        row = HangmanScore(profile_id=profile_id, wins=0, losses=0, points=0)
        db.add(row)
        await db.flush()
    return row


async def start_hangman(db: AsyncSession, space_name: str, profile: Profile) -> dict:
    """Создать партию «Виселицы»: загадать слово и вернуть карточку."""
    if await party_games.get_active_game(db, space_name) is not None:
        return {"text": "A game is already running — finish it or press «🆕 New game»."}

    cfg = await _load_hangman_config(db)
    chosen = random_hangman_word()
    if chosen is None:
        return {"text": "Couldn't find a suitable word 🤷"}
    word, hint = chosen

    state = {
        "game": "hangman",
        "word": word,
        "hint": hint,
        "guessed": [],
        "wrong": [],
        "wrong_count": 0,
        "max_wrong": cfg["max_wrong"],
        "config": cfg,
    }
    session = await party_games._start_session(db, space_name, "hangman", "Hangman", state)
    return build_hangman_card(state, session.id)


async def _finish(
    db: AsyncSession, session: GameSession, state: dict, profile: Profile, won: bool
) -> dict:
    """Подбить счёт в hangman_scores и закрыть сессию, вернув финальную карточку."""
    cfg = state.get("config") or await _load_hangman_config(db)
    win_points = cfg.get("win_points", WIN_POINTS)
    lose_points = cfg.get("lose_points", LOSE_POINTS)

    score = await _get_or_create_score(db, profile.id)
    if won:
        score.wins += 1
        score.points += win_points
        delta = win_points
    else:
        score.losses += 1
        score.points -= lose_points
        delta = -lose_points

    state["won"] = won
    session.state = state
    session.status = "finished"
    await db.commit()
    return _result_card(state, session.id, won, delta)


async def _active_hangman_session(db: AsyncSession, game_id: int) -> GameSession | None:
    """Активная hangman-сессия по id, иначе None."""
    session = await db.get(GameSession, game_id)
    if session is None or session.game_type != "hangman" or session.status != "active":
        return None
    return session


def _cyrillic_rejection(state: dict, game_id: int) -> dict:
    """Ответ на ввод кириллицей: короткое предупреждение без траты попытки."""
    return {
        "text": "⚠️ Type in English letters!",
        "cardsV2": build_hangman_card(state, game_id),
    }


async def _apply_guess(
    db: AsyncSession,
    session: GameSession,
    state: dict,
    profile: Profile,
    raw: str,
    as_word: bool,
) -> dict:
    """Общая логика хода: буква (as_word=False) или целое слово (as_word=True)."""
    word = state.get("word", "")
    if not word:
        return {"text": "Game not found 🤷"}

    guessed = set(state.get("guessed", []))
    wrong = list(state.get("wrong", []))
    wrong_count = state.get("wrong_count", 0)
    max_wrong = state.get("max_wrong", HANGMAN_MAX_WRONG)

    if as_word:
        if raw == word:
            guessed.update(set(word))
        else:
            wrong.append(raw)
            wrong_count += 1
    else:
        if raw in guessed or raw in wrong:
            return {
                "text": "You already tried that letter 😉",
                "cardsV2": build_hangman_card(state, game_id),
            }
        if raw in word:
            guessed.add(raw)  # верная буква — попытка НЕ тратится
        else:
            wrong.append(raw)
            wrong_count += 1

    state["guessed"] = sorted(guessed)
    state["wrong"] = wrong
    state["wrong_count"] = wrong_count
    session.state = state

    if _is_won(word, guessed):
        return await _finish(db, session, state, profile, won=True)
    if wrong_count >= max_wrong:
        return await _finish(db, session, state, profile, won=False)

    await db.commit()
    return build_hangman_card(state, session.id)


async def guess(db: AsyncSession, game_id: int, profile: Profile, text: str) -> dict:
    """Ход буквой (поле «Буква»): ровно одна латинская буква."""
    session = await _active_hangman_session(db, game_id)
    if session is None:
        return {"text": "Game not found 🤷"}
    state = session.state or {}

    if _has_cyrillic(text):
        return _cyrillic_rejection(state, game_id)

    raw = _normalize_guess(text)
    if len(raw) != 1:
        return {"text": "Enter one letter 😊", "cardsV2": build_hangman_card(state, game_id)}

    return await _apply_guess(db, session, state, profile, raw, as_word=False)


async def guess_word(db: AsyncSession, game_id: int, profile: Profile, text: str) -> dict:
    """Ход словом (поле «Целое слово»): слово целиком."""
    session = await _active_hangman_session(db, game_id)
    if session is None:
        return {"text": "Game not found 🤷"}
    state = session.state or {}

    if _has_cyrillic(text):
        return _cyrillic_rejection(state, game_id)

    raw = _normalize_guess(text)
    if len(raw) < 2:
        return {"text": "A word has several letters 😊", "cardsV2": build_hangman_card(state, game_id)}

    return await _apply_guess(db, session, state, profile, raw, as_word=True)


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

    return await start_hangman(db, space_name, profile)


# ---------------------------------------------------------------------------
# Лидерборд
# ---------------------------------------------------------------------------

async def leaderboard_response(db: AsyncSession) -> dict:
    """Топ-20 «Виселицы» с пьедесталом топ-3."""
    rows = (
        await db.execute(
            select(HangmanScore, Profile.user_name, Profile.workspace_user_id)
            .join(Profile, HangmanScore.profile_id == Profile.id)
            .order_by(HangmanScore.points.desc(), HangmanScore.wins.desc())
            .limit(20)
        )
    ).all()

    if not rows:
        return {"text": "Nobody has played Hangman yet 🤷"}

    entries = [
        (name or ws or f"Player {score.profile_id}", score.wins, score.losses, score.points)
        for score, name, ws in rows
    ]

    body = _podium_text(entries)
    rest = [
        f"{i}. {name} — {pts} (wins {wins}, losses {losses})"
        for i, (name, wins, losses, pts) in enumerate(entries[3:], start=4)
    ]
    if rest:
        body += "\n\n" + "\n".join(rest)

    return {"cardsV2": [{
        "cardId": "hangmanLeaderboard",
        "card": {
            "header": {
                "title": "🏆 Hangman rating",
                "subtitle": "Win +2 · Loss -3",
            },
            "sections": [
                {"widgets": [{"textParagraph": {"text": body}}]},
            ],
        },
    }]}
