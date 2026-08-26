"""Игра «Spy» (Шпион) — командная в группе.

Случайная тема + слово; один игрок — тайный шпион (слова не знает). Все
обсуждают слово, затем голосуют «кто шпион». Шпион пойман, только если набрал
строго больше голосов, чем любой другой игрок.

Состояние живёт в game_sessions.state (JSONB), `game_type = 'spy'`, поэтому
переживает рестарты. Очки подбиваются в общий leaderboard_ledger (event_type
'game') при завершении через award_points — как у Quiplash / «Кто я?».

Контракт функций повторяет games.py: setup → {"silent": True} (карточка постится
проактивно), остальные ходы → {"cards_v2": [...]} для обновления карточки на
месте (cardId «spyGame») или {"text": ...}.
"""
import asyncio
import logging
import random

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import GameSession, Profile
from app.services import games
from app.services.chat_sender import send_message, send_text

logger = logging.getLogger(__name__)

WORD_BANK: dict[str, list[str]] = {
    "food": ["pizza", "sushi", "pancake", "popcorn", "sandwich"],
    "animals": ["penguin", "kangaroo", "octopus", "hamster", "flamingo"],
    "objects": ["umbrella", "backpack", "toothbrush", "microwave", "scooter"],
    "places": ["airport", "beach", "library", "gym", "cinema"],
}

MIN_PLAYERS = 3


def _action_url() -> str:
    """URL эндпоинта — в add-on режиме кнопка доставляет клик только при function=URL."""
    return get_settings().chat_app_audience or "spy"


def _btn(text: str, method: str, game_id: int, **extra: str) -> dict:
    """Кнопка карточки Spy: method + game_id (+доп. параметры) в parameters."""
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

def assign_roles(players: list[str], rng: random.Random | None = None) -> dict:
    """Выбрать тему, слово и шпиона. rng — для детерминированных тестов."""
    rng = rng or random
    topic = rng.choice(list(WORD_BANK.keys()))
    word = rng.choice(WORD_BANK[topic])
    spy = rng.choice(players)
    return {"topic": topic, "word": word, "spy": spy}


def tally_votes(votes: dict[str, str], players: list[str]) -> dict[str, int]:
    """Сколько голосов набрал каждый игрок (нули для тех, за кого не голосовали)."""
    tally = {p: 0 for p in players}
    for target in votes.values():
        tally[target] = tally.get(target, 0) + 1
    return tally


def score_spy(spy: str, votes: dict[str, str], players: list[str]) -> dict[str, int]:
    """Очки за раунд: {user_id: positive_points}.

    Шпион пойман, только если у него строго больше голосов, чем у любого другого.
    """
    tally: dict[str, int] = {}
    for target in votes.values():
        tally[target] = tally.get(target, 0) + 1
    spy_votes = tally.get(spy, 0)
    others_max = max((c for t, c in tally.items() if t != spy), default=0)
    caught = spy_votes > 0 and spy_votes > others_max
    if caught:
        return {p: 1 for p in players if p != spy}
    return {spy: 3}


# ---------------------------------------------------------------------------
# Карточка (cardId «spyGame» — обновляется на месте по фазам)
# ---------------------------------------------------------------------------

def build_spy_card(state: dict, names: dict[str, str], game_id: int) -> dict:
    phase = state.get("phase", "setup")
    players = state.get("players", [])
    finish_btn = _btn("🏁 End game", "spy_finish", game_id)

    if phase == "setup":
        roster = (
            ", ".join(names.get(p, p) for p in players)
            if players else "Nobody yet — press «🙋 I'm playing!»"
        )
        widgets = [
            {"textParagraph": {"text": f"Players ({len(players)}): {roster}"}},
            {"buttonList": {"buttons": [
                _btn("🙋 I'm playing!", "spy_join", game_id),
                _btn("▶️ Start", "spy_start", game_id),
                finish_btn,
            ]}},
        ]
        header = {"title": "Spy 🕵️", "subtitle": "Who's the spy?"}
    elif phase == "discuss":
        widgets = [
            {"textParagraph": {"text": (
                f"Topic: **{state.get('topic', '')}**\n\n"
                "Discuss the word in the group. The spy must not be caught 🤫"
            )}},
            {"buttonList": {"buttons": [
                _btn("🗳️ Start voting", "spy_start_vote", game_id),
                finish_btn,
            ]}},
        ]
        header = {"title": "Spy 🕵️", "subtitle": f"Topic: {state.get('topic', '')}"}
    elif phase == "voting":
        votes = state.get("votes", {})
        tally = tally_votes(votes, players)
        status = "Votes: " + ", ".join(f"{names.get(p, p)} — {tally[p]}" for p in players)
        waiting = [p for p in players if p not in votes]
        if waiting:
            status += "\nWaiting to vote: " + ", ".join(names.get(p, p) for p in waiting)
        vote_buttons = [_btn(names.get(p, p), "spy_vote", game_id, target=p) for p in players]
        widgets = [
            {"textParagraph": {"text": status}},
            {"buttonList": {"buttons": vote_buttons}},
            {"buttonList": {"buttons": [finish_btn]}},
        ]
        header = {"title": "Who's the spy? 🕵️", "subtitle": "Vote for a suspect"}
    else:  # finished
        widgets = [{"textParagraph": {"text": state.get("result_text", "Game over.")}}]
        header = {"title": "Spy 🏁", "subtitle": "Game over"}

    return {"cardsV2": [{
        "cardId": "spyGame",
        "card": {"header": header, "sections": [{"widgets": widgets}]},
    }]}


# ---------------------------------------------------------------------------
# Работа с БД
# ---------------------------------------------------------------------------

async def _active_spy_session(db: AsyncSession, game_id: int) -> GameSession | None:
    """Активная spy-сессия по id, иначе None."""
    session = await db.get(GameSession, game_id)
    if session is None or session.game_type != "spy" or session.status != "active":
        return None
    return session


async def _dm_secret(db: AsyncSession, uid: str, text: str) -> bool:
    """Отправить секрет игроку в его DM с ботом. True — отправлено."""
    from app.services.broadcast import ensure_profile_dm

    profile = await games._profile_by_workspace(db, uid)
    if profile is None:
        return False
    try:
        if not await ensure_profile_dm(db, profile):
            return False
        await asyncio.to_thread(send_text, profile.chat_space_id, text)
        return True
    except Exception:
        logger.exception("spy_dm_secret_failed uid=%s", uid)
        return False


async def setup_spy(db: AsyncSession, space_name: str) -> dict:
    """Создать партию Spy: карточка-лобби в группу (фаза setup)."""
    if await games.get_active_game(db, space_name) is not None:
        return {"text": "A game is already running — end it («стоп» or the «🏁 End game» button)."}

    state = {
        "game": "spy",
        "phase": "setup",
        "topic": "",
        "word": "",
        "spy": "",
        "players": [],
        "votes": {},
        "scores": {},
        "scoreboard_message_name": "",
    }
    session = await games._start_session(db, space_name, "spy", "Spy", state)

    card = build_spy_card(state, {}, session.id)
    try:
        resp = await asyncio.to_thread(
            send_message, space_name, text="Spy! Who's the spy? 🕵️", cards_v2=card["cardsV2"],
        )
        state["scoreboard_message_name"] = resp.get("name", "")
        session.state = state
        await db.commit()
    except Exception:
        logger.exception("spy_setup_post_failed space=%s", space_name)
    return {"silent": True}


async def join_spy(db: AsyncSession, profile: Profile, game_id: int) -> dict:
    """Кнопка «🙋 I'm playing!»: добавить игрока, обновить карточку на месте."""
    session = await _active_spy_session(db, game_id)
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
    return {"cards_v2": build_spy_card(state, names, game_id)["cardsV2"]}


async def start_spy_game(db: AsyncSession, game_id: int) -> dict:
    """Кнопка «▶️ Start»: раздать роли, выслать секреты в личку, фаза «discuss»."""
    session = await _active_spy_session(db, game_id)
    if session is None:
        return {"text": "Game not found 🤷"}
    state = session.state or {}
    if state.get("phase") != "setup":
        return {"text": "Game already started 🚀"}

    players = list(state.get("players", []))
    if len(players) < MIN_PLAYERS:
        return {"text": f"Need at least {MIN_PLAYERS} players — press «🙋 I'm playing!» 🙏"}

    roles = assign_roles(players)
    topic, word, spy = roles["topic"], roles["word"], roles["spy"]
    state.update({
        "phase": "discuss",
        "topic": topic,
        "word": word,
        "spy": spy,
        "votes": {},
        "scores": {p: 0 for p in players},
    })
    session.state = state
    await db.commit()

    for player in players:
        if player == spy:
            await _dm_secret(db, player, f"You are the spy 🤫. Topic: {topic}. Blend in!")
        else:
            await _dm_secret(db, player, f"Your word: {word}")

    names = await games._resolve_names(db, players)
    return {"cards_v2": build_spy_card(state, names, game_id)["cardsV2"]}


async def spy_start_vote(db: AsyncSession, game_id: int) -> dict:
    """Кнопка «🗳️ Start voting»: открыть фазу голосования."""
    session = await _active_spy_session(db, game_id)
    if session is None:
        return {"text": "Game not found 🤷"}
    state = session.state or {}
    if state.get("phase") != "discuss":
        return {"text": "Voting isn't open yet ⏳"}

    state["phase"] = "voting"
    state["votes"] = {}
    session.state = state
    await db.commit()

    names = await games._resolve_names(db, state.get("players", []))
    return {"cards_v2": build_spy_card(state, names, game_id)["cardsV2"]}


async def submit_spy_vote(db: AsyncSession, game_id: int, user_id: str, target: str) -> dict:
    """Записать голос «кто шпион»; последний голос закрывает раунд и начисляет очки."""
    session = await _active_spy_session(db, game_id)
    if session is None:
        return {"text": "Game not found 🤷"}
    state = session.state or {}
    players = list(state.get("players", []))
    if state.get("phase") != "voting":
        return {"text": "It's not time to vote ⏳"}
    if user_id not in players:
        return {"text": "You're not in this game 🙂"}
    if target not in players:
        return {"text": "That player isn't in the game 🤷"}

    votes = dict(state.get("votes", {}))
    if user_id in votes:
        return {"text": "You already voted ✅"}
    votes[user_id] = target
    state["votes"] = votes

    names = await games._resolve_names(db, players)
    if len(votes) < len(players):
        session.state = state
        await db.commit()
        return {"cards_v2": build_spy_card(state, names, game_id)["cardsV2"]}

    # Все проголосовали — подсчёт и очки.
    score = score_spy(state["spy"], votes, players)
    spy_name = names.get(state["spy"], state["spy"])
    tally = tally_votes(votes, players)
    vote_lines = [f"{names.get(p, p)}: {tally[p]}" for p in players]
    score_lines = [f"{names.get(u, u)}: +{p}" for u, p in score.items()]
    state["scores"] = score
    state["phase"] = "finished"
    state["result_text"] = (
        f"The spy was **{spy_name}**! Word: **{state['word']}**\n\n"
        f"Voting:\n" + "\n".join(vote_lines) + "\n\n"
        f"Points:\n" + "\n".join(score_lines)
    )
    session.state = state
    await games._finish_game(db, session, state)
    return {"cards_v2": build_spy_card(state, names, game_id)["cardsV2"]}


async def finish_spy(db: AsyncSession, game_id: int) -> dict:
    """Кнопка «🏁 End game»: закрыть партию без начисления очков."""
    session = await _active_spy_session(db, game_id)
    if session is None:
        return {"text": "Game not found 🤷"}
    session.status = "cancelled"
    await db.commit()
    return {"text": "Game stopped 🛑"}
