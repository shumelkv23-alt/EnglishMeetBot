"""Игра «Guesspionage» — командная в группе.

Бот задаёт вопрос «Какой процент людей…». Один игрок (называющий) называет свой
процент в личке; остальные голосуют «правда выше или ниже». Очки: называющий —
по близости к ответу (≤5 → 3, ≤10 → 2, иначе 1), остальные +1 за верное
направление.

Состояние живёт в game_sessions.state (JSONB), `game_type = 'guesspionage'`,
поэтому переживает рестарты. Очки подбиваются в общий leaderboard_ledger
(event_type 'game') через games._finish_game — как у Quiplash / «Кто я?».

Контракт функций повторяет games.py: setup → {"silent": True} (карточка постится
проактивно), остальные ходы → {"cards_v2": [...]} для обновления карточки на
месте (cardId «guesspionageGame») или {"text": ...}.
"""
import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import GameSession, Profile
from app.services import games
from app.services.chat_sender import patch_message, send_message
from app.services.form_parsing import parse_form_inputs

logger = logging.getLogger(__name__)

GUESS_QUESTIONS: list[tuple[str, int]] = [
    ("What percentage of people have peed in a shower?", 70),
    ("What percentage of people wear socks when they sleep?", 16),
    ("What percentage of people have Googled themselves?", 65),
    ("What percentage of people prefer smooth peanut butter to crunchy?", 62),
    ("What percentage of people believe there are aliens?", 85),
]

MIN_PLAYERS = 2


def _action_url() -> str:
    """URL эндпоинта — в add-on режиме кнопка доставляет клик только при function=URL."""
    return get_settings().chat_app_audience or "guesspionage"


def _btn(text: str, method: str, game_id: int, **extra: str) -> dict:
    """Кнопка карточки Guesspionage: method + game_id (+доп. параметры) в parameters."""
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

def score_round(
    true_pct: int, guess: int, higher: set[str], lower: set[str], guesser: str
) -> dict[str, int]:
    """Очки за раунд: {user_id: positive_points}.

    Называющий — по близости (≤5 → 3, ≤10 → 2, иначе 1); остальные +1 за верное
    направление.
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


# ---------------------------------------------------------------------------
# Карточки
# ---------------------------------------------------------------------------

def build_guesspionage_card(state: dict, names: dict[str, str], game_id: int) -> dict:
    """Единая карточка в группе (cardId «guesspionageGame» — меняется по фазам)."""
    phase = state.get("phase", "setup")
    players = state.get("players", [])
    guesser = state.get("guesser", "")
    finish_btn = _btn("🏁 End game", "guesspionage_finish", game_id)

    if phase == "setup":
        roster = (
            ", ".join(names.get(p, p) for p in players)
            if players else "Nobody yet — press «🙋 I'm playing!»"
        )
        widgets = [
            {"textParagraph": {"text": f"Players ({len(players)}): {roster}"}},
            {"buttonList": {"buttons": [
                _btn("🙋 I'm playing!", "guesspionage_join", game_id),
                _btn("▶️ Start", "guesspionage_start", game_id),
                finish_btn,
            ]}},
        ]
        header = {"title": "Guesspionage 📊", "subtitle": "Guess the percentage"}
    elif phase == "guessing":
        widgets = [
            {"textParagraph": {"text": (
                f"**{state.get('question', '')}**\n\n"
                f"{names.get(guesser, guesser)} is writing their guess… 🤫"
            )}},
            {"buttonList": {"buttons": [finish_btn]}},
        ]
        header = {"title": "Guesspionage 📊", "subtitle": "Guesser is thinking…"}
    elif phase == "voting":
        widgets = [
            {"textParagraph": {"text": (
                f"**{state.get('question', '')}**\n\n"
                f"{names.get(guesser, guesser)} guesses **{state.get('guess')}%**.\n"
                "Is the truth higher or lower?"
            )}},
            {"buttonList": {"buttons": [
                _btn("Higher ⬆️", "guesspionage_vote", game_id, choice="higher"),
                _btn("Lower ⬇️", "guesspionage_vote", game_id, choice="lower"),
                finish_btn,
            ]}},
        ]
        header = {"title": "Guesspionage 📊", "subtitle": "Higher or lower?"}
    else:  # finished
        widgets = [{"textParagraph": {"text": state.get("result_text", "Game over.")}}]
        header = {"title": "Guesspionage 🏁", "subtitle": "Game over"}

    return {"cardsV2": [{
        "cardId": "guesspionageGame",
        "card": {"header": header, "sections": [{"widgets": widgets}]},
    }]}


def build_guess_card(question: str, game_id: int) -> dict:
    """Карточка для называющего (в личку): поле процента + кнопка «Submit»."""
    return {"cardsV2": [{
        "cardId": "guesspionageGuess",
        "card": {
            "header": {"title": "Your percentage", "subtitle": question},
            "sections": [{"widgets": [
                {"textInput": {
                    "name": "guess",
                    "label": "Your percentage (0–100)",
                    "type": "SINGLE_LINE",
                }},
                {"buttonList": {"buttons": [
                    _btn("Submit", "guesspionage_submit", game_id),
                ]}},
            ]}],
        },
    }]}


# ---------------------------------------------------------------------------
# Работа с БД
# ---------------------------------------------------------------------------

async def _active_guesspionage_session(db: AsyncSession, game_id: int) -> GameSession | None:
    """Активная guesspionage-сессия по id, иначе None."""
    session = await db.get(GameSession, game_id)
    if session is None or session.game_type != "guesspionage" or session.status != "active":
        return None
    return session


async def _patch_group(session: GameSession, state: dict, cards_v2: list[dict]) -> None:
    """Обновить карточку в группе НА МЕСТЕ (messages.patch)."""
    msg_name = state.get("scoreboard_message_name", "")
    if not msg_name:
        return
    try:
        await asyncio.to_thread(patch_message, msg_name, cards_v2=cards_v2)
    except Exception:
        logger.exception("guesspionage_group_patch_failed game=%s", session.id)


async def _dm_guess_card(db: AsyncSession, uid: str, question: str, game_id: int) -> bool:
    """Отправить карточку ввода процента называющему в личку. True — отправлено."""
    from app.services.broadcast import ensure_profile_dm

    profile = await games._profile_by_workspace(db, uid)
    if profile is None:
        return False
    try:
        if not await ensure_profile_dm(db, profile):
            return False
        card = build_guess_card(question, game_id)
        await asyncio.to_thread(
            send_message, profile.chat_space_id,
            text="Your turn — write a percentage 👇", cards_v2=card["cardsV2"],
        )
        return True
    except Exception:
        logger.exception("guesspionage_dm_failed uid=%s", uid)
        return False


async def setup_guesspionage(db: AsyncSession, space_name: str) -> dict:
    """Создать партию Guesspionage: карточка-лобби в группу (фаза setup)."""
    if await games.get_active_game(db, space_name) is not None:
        return {"text": "A game is already running — end it («стоп» or the «🏁 End game» button)."}

    state = {
        "game": "guesspionage",
        "phase": "setup",
        "players": [],
        "question": "",
        "true_pct": 0,
        "guesser": "",
        "guess": None,
        "higher": [],
        "lower": [],
        "scores": {},
        "scoreboard_message_name": "",
    }
    session = await games._start_session(db, space_name, "guesspionage", "Guesspionage", state)

    card = build_guesspionage_card(state, {}, session.id)
    try:
        resp = await asyncio.to_thread(
            send_message, space_name, text="Guesspionage! Guess the percentage 📊",
            cards_v2=card["cardsV2"],
        )
        state["scoreboard_message_name"] = resp.get("name", "")
        session.state = state
        await db.commit()
    except Exception:
        logger.exception("guesspionage_setup_post_failed space=%s", space_name)
    return {"silent": True}


async def join_guesspionage(db: AsyncSession, profile: Profile, game_id: int) -> dict:
    """Кнопка «🙋 I'm playing!»: добавить игрока, обновить карточку на месте."""
    session = await _active_guesspionage_session(db, game_id)
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
    return {"cards_v2": build_guesspionage_card(state, names, game_id)["cardsV2"]}


async def start_guesspionage_game(db: AsyncSession, game_id: int) -> dict:
    """Кнопка «▶️ Start»: выбрать вопрос и называющего, выслать карточку в личку."""
    session = await _active_guesspionage_session(db, game_id)
    if session is None:
        return {"text": "Game not found 🤷"}
    state = session.state or {}
    if state.get("phase") != "setup":
        return {"text": "Game already started 🚀"}

    players = list(state.get("players", []))
    if len(players) < MIN_PLAYERS:
        return {"text": f"Need at least {MIN_PLAYERS} players — press «🙋 I'm playing!» 🙏"}

    question, true_pct = GUESS_QUESTIONS[0]
    guesser = players[0]
    state.update({
        "phase": "guessing",
        "question": question,
        "true_pct": true_pct,
        "guesser": guesser,
        "guess": None,
        "higher": [],
        "lower": [],
        "scores": {p: 0 for p in players},
    })
    session.state = state
    await db.commit()

    await _dm_guess_card(db, guesser, question, game_id)

    names = await games._resolve_names(db, players)
    return {"cards_v2": build_guesspionage_card(state, names, game_id)["cardsV2"]}


async def submit_guess(db: AsyncSession, game_id: int, user_id: str, form_inputs: dict) -> dict:
    """Называющий прислал число (из лички): принять и огласить группе."""
    session = await _active_guesspionage_session(db, game_id)
    if session is None:
        return {"text": "Game not found 🤷"}
    state = session.state or {}
    if state.get("phase") != "guessing":
        return {"text": "It's not time to guess ⏳"}
    if user_id != state.get("guesser"):
        return {"text": "You're not the guesser 🙂"}

    values = parse_form_inputs(form_inputs or {}).get("guess", [])
    if not values:
        return {"text": "Write a number and press 'Submit'."}
    try:
        guess = int(values[0])
    except ValueError:
        return {"text": "That's not a number — write a percentage as digits (0–100)."}
    if not 0 <= guess <= 100:
        return {"text": "The percentage must be from 0 to 100."}

    state["guess"] = guess
    state["phase"] = "voting"
    state["higher"] = []
    state["lower"] = []
    session.state = state
    await db.commit()

    names = await games._resolve_names(db, state.get("players", []))
    card = build_guesspionage_card(state, names, game_id)
    await _patch_group(session, state, card["cardsV2"])

    return {"text": "Got it! 🎯 The rest are already voting 'higher/lower'."}


async def vote_guesspionage(db: AsyncSession, game_id: int, user_id: str, choice: str) -> dict:
    """Записать голос «выше/ниже»; когда проголосовали все — подсчёт и очки."""
    session = await _active_guesspionage_session(db, game_id)
    if session is None:
        return {"text": "Game not found 🤷"}
    state = session.state or {}
    players = list(state.get("players", []))
    guesser = state.get("guesser")
    if state.get("phase") != "voting":
        return {"text": "It's not time to vote ⏳"}
    if user_id not in players:
        return {"text": "You're not in this game 🙂"}
    if user_id == guesser:
        return {"text": "The guesser doesn't vote."}

    higher = set(state.get("higher", []))
    lower = set(state.get("lower", []))
    higher.discard(user_id)
    lower.discard(user_id)
    if choice == "higher":
        higher.add(user_id)
    else:
        lower.add(user_id)

    voters = [p for p in players if p != guesser]
    if len(higher) + len(lower) < len(voters):
        state["higher"] = sorted(higher)
        state["lower"] = sorted(lower)
        session.state = state
        await db.commit()
        return {"silent": True}

    score = score_round(state["true_pct"], state["guess"], higher, lower, guesser)
    names = await games._resolve_names(db, players)
    lines = [f"{names.get(u, u)}: +{p}" for u, p in score.items()]
    state["scores"] = score
    state["phase"] = "finished"
    state["result_text"] = f"Correct answer: **{state['true_pct']}%**\n\n" + "\n".join(lines)
    session.state = state
    await games._finish_game(db, session, state)
    return {"cards_v2": build_guesspionage_card(state, names, game_id)["cardsV2"]}


async def finish_guesspionage(db: AsyncSession, game_id: int) -> dict:
    """Кнопка «🏁 End game»: закрыть партию без начисления очков."""
    session = await _active_guesspionage_session(db, game_id)
    if session is None:
        return {"text": "Game not found 🤷"}
    session.status = "cancelled"
    await db.commit()
    return {"text": "Game stopped 🛑"}
