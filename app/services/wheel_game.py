"""Игра «Поле чудес» (Wheel of Fortune) — командная в группе.

Скрытое английское слово; игроки по очереди крутят барабан (очки за букву) и
называют букву или слово целиком. Угадал букву — открываются все вхождения,
очки = барабан × число вхождений, ход остаётся у того же игрока (крутит снова).
Ошибся — ход переходит следующему. Сектор «bankrupt» обнуляет очки и передаёт ход.
Угадал слово целиком — победа.

Состояние живёт в game_sessions.state (JSONB), `game_type = 'wheel'`, поэтому
переживает рестарты. Очки подбиваются в общий leaderboard_ledger (event_type
'game') при завершении через games._finish_game — как у Spy / Quiplash.

Контракт повторяет spy_game.py: setup → {"silent": True} (карточка постится
проактивно), клики кнопок → {"cards_v2": [...]} для обновления карточки на месте
(cardId «wheelGame»). Ввод буквы/слова — через textInput в карточке («✅ Submit» →
метод wheel_guess), принимается только от игрока, чей сейчас ход; после обработки
карточка патчится сама и возвращается {}.
"""
import asyncio
import logging
import random

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import GameSession, Profile
from app.services import party_games as games
from app.services.chat_sender import patch_message, send_message
from app.services.word_bank import WORDS, HANGMAN_WORDS

logger = logging.getLogger(__name__)

MIN_PLAYERS = 2
WIN_BONUS = 500
# Сектора барабана: очки за каждое вхождение буквы или спец-сектор "bankrupt".
WHEEL: list = [200, 300, 400, 500, 600, 800, 1000, 0, "bankrupt"]


def _action_url() -> str:
    """URL эндпоинта — в add-on режиме кнопка доставляет клик только при function=URL."""
    return get_settings().chat_app_audience or "wheel"


def _btn(text: str, method: str, game_id: int, **extra: str) -> dict:
    """Кнопка карточки «Поле чудес»: method + game_id (+доп. параметры) в parameters."""
    params = [
        {"key": "method", "value": method},
        {"key": "game_id", "value": str(game_id)},
    ]
    for key, value in extra.items():
        params.append({"key": key, "value": str(value)})
    return {
        "text": text,
        "onClick": {"action": {"function": _action_url(), "parameters": params}},
    }


# ---------------------------------------------------------------------------
# Чистые хелперы (без БД) — покрываются юнит-тестами напрямую
# ---------------------------------------------------------------------------

def pick_word(rng: random.Random | None = None) -> str:
    """Случайное скрытое слово: одно английское слово, 4–10 букв, только буквы."""
    rng = rng or random
    pool = [w for w in WORDS if w.isalpha() and 4 <= len(w) <= 10]
    return rng.choice(pool).lower()


# Краткая подсказка-объяснение для скрытого слова. Категории берём из HANGMAN_WORDS
# (тот же банк слов), формулируем человеческой фразой, чтобы участники понимали,
# что именно загадано, ещё до открытия букв.
_HINT_PHRASES: dict[str, str] = {
    "animal": "an animal 🐾",
    "bird": "a bird 🐦",
    "insect": "an insect 🐛",
    "sea animal": "a sea animal 🌊",
    "sweet food": "something sweet 🍬",
    "drink": "a drink 🥤",
    "fruit or vegetable": "a fruit or vegetable 🍎",
    "food": "something to eat 🍽️",
    "metal tool": "a tool 🛠️",
    "furniture": "furniture 🪑",
    "household item": "a household item 🏠",
    "place at home": "a place at home 🏡",
    "city place": "a place in the city 🏙️",
    "place in nature": "a place in nature 🌳",
    "transport": "a means of transport 🚗",
    "profession": "a profession 👩‍💼",
    "body part": "a body part 👤",
    "clothing": "an item of clothing 👕",
    "action": "an action (verb) 🏃",
    "quality": "a quality (adjective) ✨",
    "nature": "something in nature 🌿",
}


def word_hint(word: str) -> str:
    """Человекочитаемая подсказка к скрытому слову (категория из банка слов)."""
    category = HANGMAN_WORDS.get(word.lower(), "")
    return _HINT_PHRASES.get(category, "a common English word")


def spin_wheel(rng: random.Random | None = None):
    """Сектор барабана: число очков (за вхождение буквы) или 'bankrupt'."""
    rng = rng or random
    return rng.choice(WHEEL)


def render_word(word: str, revealed: list[bool]) -> str:
    """Скрытое слово для карточки: открытые буквы капсом, скрытые — «▢»."""
    return " ".join(
        ch.upper() if (i < len(revealed) and revealed[i]) else "▢"
        for i, ch in enumerate(word)
    )


def letter_positions(word: str, letter: str) -> list[int]:
    """Индексы всех вхождений буквы в слове (пусто, если буквы нет)."""
    return [i for i, ch in enumerate(word) if ch == letter]


def current_player(state: dict) -> str:
    """workspace_user_id игрока, чей сейчас ход (пусто, если не определить)."""
    players = state.get("players", [])
    turn = state.get("turn", 0)
    return players[turn] if players and 0 <= turn < len(players) else ""


# ---------------------------------------------------------------------------
# Карточка (cardId «wheelGame» — обновляется на месте по фазам)
# ---------------------------------------------------------------------------

def build_wheel_card(state: dict, names: dict[str, str], game_id: int) -> dict:
    phase = state.get("phase", "setup")
    players = state.get("players", [])
    finish_btn = _btn("🏁 End game", "wheel_finish", game_id)

    if phase == "setup":
        roster = (
            ", ".join(names.get(p, p) for p in players)
            if players else "Nobody yet — press «🙋 I'm playing!»"
        )
        widgets = [
            {"textParagraph": {"text": f"Players ({len(players)}): {roster}"}},
            {"buttonList": {"buttons": [
                _btn("🙋 I'm playing!", "wheel_join", game_id),
                _btn("▶️ Start", "wheel_start", game_id),
                finish_btn,
            ]}},
        ]
        header = {"title": "Wheel Game 🎡", "subtitle": "Wheel of Fortune"}

    elif phase == "active":
        word_text = render_word(state.get("word", ""), state.get("revealed", []))
        used = state.get("used_letters", [])
        used_text = "Letters used: " + (", ".join(ch.upper() for ch in used) if used else "—")
        scores = state.get("scores", {})
        turn = state.get("turn", 0)
        current = players[turn] if players and 0 <= turn < len(players) else ""
        score_lines = [
            f"{'🎯 ' if p == current else '     '}{names.get(p, p)}: {scores.get(p, 0)}"
            for p in players
        ]

        widgets = [
            {"textParagraph": {"text": f"**{word_text}**"}},
            {"textParagraph": {"text": f"💡 It's {word_hint(state.get('word', ''))}."}},
            {"textParagraph": {"text": used_text}},
            {"textParagraph": {"text": "\n".join(score_lines)}},
        ]
        if state.get("last_result"):
            widgets.append({"textParagraph": {"text": state["last_result"]}})

        if state.get("spin") is None:
            widgets.append({"buttonList": {"buttons": [
                _btn("🎡 Spin the wheel", "wheel_spin", game_id),
                finish_btn,
            ]}})
        else:
            widgets.append({"textParagraph": {"text": f"Spun: **{state['spin']}**"}})
            widgets.append({"textInput": {
                "name": "guess",
                "label": "Буква или слово",
                "hintText": "Write a letter or the whole word",
            }})
            widgets.append({"buttonList": {"buttons": [
                _btn("✅ Submit", "wheel_guess", game_id),
                finish_btn,
            ]}})
        header = {"title": "Wheel Game 🎡", "subtitle": f"Turn: {names.get(current, current)}"}

    else:  # finished
        widgets = [{"textParagraph": {"text": state.get("result_text", "Game over.")}}]
        header = {"title": "Wheel Game 🏁", "subtitle": "Game over"}

    return {"cardsV2": [{
        "cardId": "wheelGame",
        "card": {"header": header, "sections": [{"widgets": widgets}]},
    }]}


# ---------------------------------------------------------------------------
# Работа с БД
# ---------------------------------------------------------------------------

async def _active_wheel_session(db: AsyncSession, game_id: int) -> GameSession | None:
    """Активная wheel-сессия по id, иначе None."""
    session = await db.get(GameSession, game_id)
    if session is None or session.game_type != "wheel" or session.status != "active":
        return None
    return session


async def _patch_card(state: dict, cards_v2: list[dict]) -> None:
    """Обновить карточку в группе НА МЕСТЕ (messages.patch)."""
    msg_name = state.get("scoreboard_message_name", "")
    if not msg_name:
        return
    try:
        await asyncio.to_thread(patch_message, msg_name, cards_v2=cards_v2)
    except Exception:
        logger.exception("wheel_patch_failed")


async def setup_wheel(db: AsyncSession, space_name: str) -> dict:
    """Создать партию «Поле чудес»: карточка-лобби в группу (фаза setup)."""
    if await games.get_active_game(db, space_name) is not None:
        return {"text": "A game is already running — end it («стоп» or the «🏁 End game» button)."}

    state = {
        "game": "wheel",
        "phase": "setup",
        "word": "",
        "revealed": [],
        "players": [],
        "turn": 0,
        "scores": {},
        "used_letters": [],
        "spin": None,
        "last_result": "",
        "result_text": "",
        "scoreboard_message_name": "",
    }
    session = await games._start_session(db, space_name, "wheel", "Wheel Game", state)

    card = build_wheel_card(state, {}, session.id)
    try:
        resp = await asyncio.to_thread(
            send_message, space_name,
            text="🎡 Wheel Game! Join in — guess the hidden English word.",
            cards_v2=card["cardsV2"],
        )
        state["scoreboard_message_name"] = resp.get("name", "")
        session.state = state
        await db.commit()
    except Exception:
        logger.exception("wheel_setup_post_failed space=%s", space_name)
    return {"silent": True}


async def join_wheel(db: AsyncSession, profile: Profile, game_id: int) -> dict:
    """Кнопка «🙋 I'm playing!»: добавить игрока, обновить карточку на месте."""
    session = await _active_wheel_session(db, game_id)
    if session is None:
        return {"text": "Game not found 🤷"}
    state = session.state or {}
    if state.get("phase") != "setup":
        return {"text": "Game already started 🚀"}

    players = list(state.get("players", []))
    ws = profile.workspace_user_id or ""
    if ws and ws not in players:
        players.append(ws)
    state["players"] = players
    session.state = state
    await db.commit()

    names = await games._resolve_names(db, players)
    return {"cards_v2": build_wheel_card(state, names, game_id)["cardsV2"]}


async def start_wheel_game(db: AsyncSession, game_id: int) -> dict:
    """Кнопка «▶️ Start»: выбрать слово, раздать нулевые очки, ход первого игрока."""
    session = await _active_wheel_session(db, game_id)
    if session is None:
        return {"text": "Game not found 🤷"}
    state = session.state or {}
    if state.get("phase") != "setup":
        return {"text": "Game already started 🚀"}

    players = list(state.get("players", []))
    if len(players) < MIN_PLAYERS:
        return {"text": f"Need at least {MIN_PLAYERS} players — press «🙋 I'm playing!» 🙏"}

    word = pick_word()
    state.update({
        "phase": "active",
        "word": word,
        "revealed": [False] * len(word),
        "turn": 0,
        "scores": {p: 0 for p in players},
        "used_letters": [],
        "spin": None,
        "last_result": "",
    })
    session.state = state
    await db.commit()

    names = await games._resolve_names(db, players)
    current = players[0]
    state["last_result"] = f"🎡 {names.get(current, current)} starts — spin the wheel!"
    session.state = state
    await db.commit()
    return {"cards_v2": build_wheel_card(state, names, game_id)["cardsV2"]}


async def wheel_spin(db: AsyncSession, game_id: int, user_id: str) -> dict:
    """Кнопка «🎡 Spin the wheel»: определить очки за букву или «bankrupt»."""
    session = await _active_wheel_session(db, game_id)
    if session is None:
        return {"text": "Game not found 🤷"}
    state = session.state or {}
    players = list(state.get("players", []))
    if state.get("phase") != "active":
        return {"text": "Game not running ⏳"}

    turn = state.get("turn", 0)
    if not players or turn >= len(players):
        return {"text": "Game over 🏁"}
    current = players[turn]

    if user_id != current:
        return {}
    if state.get("spin") is not None:
        return {"text": "You already spun — write a letter or the whole word 😉"}

    names = await games._resolve_names(db, players)
    result = spin_wheel()
    if result == "bankrupt":
        state["scores"][current] = 0
        state["spin"] = None
        state["turn"] = (turn + 1) % len(players)
        state["last_result"] = (
            f"💥 Bankrupt! {names.get(current, current)} loses all points. Turn passes."
        )
    else:
        state["spin"] = result
        state["last_result"] = (
            f"🎡 {names.get(current, current)} spun **{result}** — "
            "write a letter or the whole word in the chat 👇"
        )
    session.state = state
    await db.commit()
    return {"cards_v2": build_wheel_card(state, names, game_id)["cardsV2"]}


async def wheel_guess(
    db: AsyncSession, game_id: int, user_id: str, form_inputs: dict | None,
) -> dict:
    """Кнопка «✅ Submit»: принять букву/слово из поля карточки (только ход игрока).

    Поле textInput видно всем, но принимается только ввод текущего игрока —
    проверка по workspace_user_id. Возвращает {} (карточка пропатчена) или
    {"text": ...} (подсказка/ошибка).
    """
    session = await _active_wheel_session(db, game_id)
    if session is None:
        return {"text": "Game not found 🤷"}
    state = session.state or {}
    if state.get("phase") != "active":
        return {"text": "Game not running ⏳"}

    players = list(state.get("players", []))
    current = current_player(state)
    if not current:
        return {"text": "Game over 🏁"}

    if user_id != current:
        return {}
    if state.get("spin") is None:
        return {"text": "🎡 Spin the wheel first!"}

    names = await games._resolve_names(db, players)
    guess = games._first_form_value(form_inputs or {}, "guess").lower().strip()
    if not guess:
        return {"text": "The field is empty — write a letter or the whole word 😊"}
    return await _apply_guess(db, session, state, user_id, guess, names)


async def _apply_guess(
    db: AsyncSession, session: GameSession, state: dict,
    user_id: str, guess: str, names: dict[str, str],
) -> dict:
    """Обработать валидированный ход текущего игрока: буква или слово целиком."""
    players = list(state.get("players", []))
    turn = state.get("turn", 0)
    current = current_player(state)
    word = state.get("word", "")
    revealed = list(state.get("revealed", []))
    used = list(state.get("used_letters", []))
    scores = dict(state.get("scores", {}))
    spin = state.get("spin") or 0

    # Одна буква.
    if len(guess) == 1 and guess.isalpha():
        letter = guess
        if letter in used:
            return {"text": f"'{letter.upper()}' was already used — name another letter 😉"}
        used.append(letter)
        positions = letter_positions(word, letter)

        if not positions:
            state["used_letters"] = used
            state["spin"] = None
            state["turn"] = (turn + 1) % len(players)
            state["last_result"] = f"❌ No **{letter.upper()}** in the word. Turn passes."
            session.state = state
            await db.commit()
            await _patch_card(state, build_wheel_card(state, names, session.id)["cardsV2"])
            return {}

        for i in positions:
            revealed[i] = True
        gained = spin * len(positions)
        scores[current] = scores.get(current, 0) + gained
        state["revealed"] = revealed
        state["used_letters"] = used
        state["scores"] = scores
        state["spin"] = None

        if all(revealed):
            # Последняя буква открыта — слово целиком, текущий игрок побеждает.
            scores[current] = scores.get(current, 0) + WIN_BONUS
            state["scores"] = scores
            state["phase"] = "finished"
            state["result_text"] = (
                f"🎉 **{names.get(current, current)}** revealed the whole word — "
                f"**{word.upper()}**! (+{WIN_BONUS} bonus)\n\n"
                "Final scores:\n"
                + "\n".join(f"  • {names.get(p, p)}: {scores.get(p, 0)}" for p in players)
            )
            session.state = state
            await games._finish_game(db, session, state)
            await _patch_card(state, build_wheel_card(state, names, session.id)["cardsV2"])
            return {}

        state["last_result"] = (
            f"✅ {len(positions)}× **{letter.upper()}** (+{gained}). "
            f"{names.get(current, current)} spins again!"
        )
        session.state = state
        await db.commit()
        await _patch_card(state, build_wheel_card(state, names, session.id)["cardsV2"])
        return {}

    # Слово целиком.
    if guess == word:
        gained = WIN_BONUS + (spin if spin else 0)
        scores[current] = scores.get(current, 0) + gained
        state["revealed"] = [True] * len(word)
        state["scores"] = scores
        state["phase"] = "finished"
        state["result_text"] = (
            f"🎉 **{names.get(current, current)}** guessed it — **{word.upper()}**!\n\n"
            "Final scores:\n"
            + "\n".join(f"  • {names.get(p, p)}: {scores.get(p, 0)}" for p in players)
        )
        session.state = state
        await games._finish_game(db, session, state)
        await _patch_card(state, build_wheel_card(state, names, session.id)["cardsV2"])
        return {}

    # Слово не угадано.
    state["spin"] = None
    state["turn"] = (turn + 1) % len(players)
    state["last_result"] = f"❌ Not it! The word isn't **{guess}**. Turn passes."
    session.state = state
    await db.commit()
    await _patch_card(state, build_wheel_card(state, names, session.id)["cardsV2"])
    return {}


async def finish_wheel(db: AsyncSession, game_id: int) -> dict:
    """Кнопка «🏁 End game»: закрыть партию без начисления очков."""
    session = await _active_wheel_session(db, game_id)
    if session is None:
        return {"text": "Game not found 🤷"}
    session.status = "cancelled"
    await db.commit()
    return {"text": "Game stopped 🛑"}
