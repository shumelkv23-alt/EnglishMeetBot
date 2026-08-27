"""Игровой движок: «Кто я?» и Quiplash.

Состояние игр живёт в game_sessions.state (JSONB) — переживает рестарты uvicorn.
Отправка сообщений разделена:
- анонсы раундов, результаты и секреты «Кто я?» — проактивно через
  app.services.chat_sender (реальный transport);
- ответ на входящее сообщение/клик — возвращается из вебхука как dict.

Контракт `handle_message` / `handle_card_action`:
- None  — активной игры в space нет (вебхук продолжает обычную обработку);
- dict  — ответ бота; пустой {} означает «сообщение поглощено, ничего не постим».

Таймауты раундов закрывает периодическая задача `close_stale_games` (APScheduler
в lifespan): состояние хранит phase_deadline (epoch-секунды).

ИИ-генерация — app.services.games_llm (Anthropic Messages API, Azati). Очки
подбиваются через app.services.leaderboard.award_points (event_type 'game',
идемпотентно — UNIQUE(profile_id, meeting_instance_id, event_type)).
"""
import asyncio
import logging
import random
import re
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import Answer, Config, GameSession, MeetingInstance, Profile
from app.schemas import WeeklyAnswer
from app.services.chat_sender import (
    find_user_dm_space,
    patch_message,
    send_message,
    send_text,
)
from app.services.games_llm import generate_quiplash_game, generate_who_am_i_game, judge_guess
from app.services.leaderboard import award_points
from app.services.onboarding import current_week_start

logger = logging.getLogger(__name__)

# Дефолты игр (перекрываются значениями из config, см. _load_config)
QUIPLASH_ROUNDS = 10
QUIPLASH_WINNER_POINTS = 3
QUIPLASH_SECOND_POINTS = 1
WHO_AM_I_GUESS_POINTS = 2
QUIPLASH_ANSWER_TIMEOUT_SECONDS = 300
QUIPLASH_VOTE_TIMEOUT_SECONDS = 120
WHO_AM_I_TURN_TIMEOUT_SECONDS = 600

_STOP_WORDS = {
    "a", "an", "the", "some", "famous", "well", "known", "very", "person", "character",
}

# Синтетические профили ботов для одиночных режимов «тест».
# В Quiplash их два: партия минимум на 3 игроков = ты + 2 бота.
QUIPLASH_TEST_BOT_IDS = ("users/quiplash_bot_test", "users/quiplash_bot_test_2")
WHO_AM_I_TEST_BOT_USER_ID = "users/who_am_i_bot_test"

# В тестовой партии Quiplash раундов меньше, чтобы прогнать цикл целиком побыстрее.
QUIPLASH_TEST_ROUNDS = 3

# Банк «смешных» ответов бота для тестового режима (без LLM — быстро и надёжно).
_BOT_ANSWERS = [
    "A sudden, unexplained power outage",
    "My cat walking across the keyboard",
    "An email sent to the whole company by accident",
    "Realizing your mic was on the whole time",
    "A coworker who just has a quick question",
    "The printer deciding today is the day",
    "Waking up and forgetting your own name",
    "A meeting that could have been an email",
    "Trying to unmute but turning on video instead",
    "The Wi-Fi dying at the worst possible moment",
]


# ---------------------------------------------------------------------------
# Чистые хелперы (без БД) — покрываются юнит-тестами напрямую
# ---------------------------------------------------------------------------

def _pad(items: list[str], n: int) -> list[str]:
    """Дополнить список до n элементов повторением."""
    if not items or n <= len(items):
        return items[:n]
    return (items * ((n // len(items)) + 1))[:n]


def _guess_text(text: str) -> str:
    """Вытащить догадку из команды «угадываю: X»."""
    lowered = text.lower().strip()
    for prefix in ("угадываю:", "угадываю ", "guess:", "guess ", "я думаю", "я -", "я —"):
        if lowered.startswith(prefix):
            return text[len(prefix):].strip()
    return text.strip()


def _significant_words(text: str) -> set[str]:
    """Значимые слова (без стоп-слов) для сравнения сущности и догадки."""
    words = re.findall(r"[a-zа-яё0-9]+", text.lower())
    return {w for w in words if w not in _STOP_WORDS and len(w) > 1}


def _entities_match(secret: str, guess: str) -> bool:
    """Догадка совпадает с секретом, если все её значимые слова есть в секрете."""
    secret_words = _significant_words(secret)
    guess_words = _significant_words(guess)
    if not secret_words or not guess_words:
        return False
    return guess_words.issubset(secret_words)


def tally_votes(votes: dict) -> list[tuple[str, int]]:
    """Подсчёт голосов: [(user_id, count), ...] по убыванию."""
    tally: dict[str, int] = {}
    for author in votes.values():
        if author:
            tally[author] = tally.get(author, 0) + 1
    return sorted(tally.items(), key=lambda kv: kv[1], reverse=True)


def apply_round_points(
    scores: dict, ranked: list[tuple[str, int]], winner_pts: int, second_pts: int
) -> dict:
    """Начислить очки за раунд: победителю winner_pts, второму second_pts."""
    if not ranked:
        return scores
    winner = ranked[0][0]
    scores[winner] = scores.get(winner, 0) + winner_pts
    if len(ranked) > 1:
        second = ranked[1][0]
        scores[second] = scores.get(second, 0) + second_pts
    return scores


def _first_form_value(form_inputs: dict, name: str) -> str:
    """Первое значение поля формы (radio/checkbox/text), оба формата Google.

    Плоский:  {"name": {"stringInputs": {"value": [...]}}}
    Add-on:   {"name": {"": {"stringInputs": {"value": [...]}}}}
    """
    field = (form_inputs or {}).get(name, {})
    if not isinstance(field, dict):
        return ""
    si = field.get("stringInputs")
    if not isinstance(si, dict):
        inner = field.get("")
        si = inner.get("stringInputs") if isinstance(inner, dict) else None
    if not isinstance(si, dict):
        return ""
    values = si.get("value", [])
    return str(values[0]).strip() if values else ""


def _action_url() -> str:
    """URL эндпоинта — в add-on режиме кнопка доставляет клик только при function=URL."""
    return get_settings().chat_app_audience or "quiplash"


def _btn(text: str, method: str, game_id: int, **extra: str) -> dict:
    """Кнопка карточки Quiplash: method + game_id (+доп. параметры) в parameters."""
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


def is_test_command(raw_text: str) -> bool:
    """«квиплаш тест» / «кто я тест» — одиночная партия против бота."""
    tokens = raw_text.lower().strip().split()
    return len(tokens) >= 2 and any(t in ("тест", "test") for t in tokens[1:])


def _is_quiplash_solo(state: dict) -> bool:
    """В партии есть синтетический бот (одиночный тестовый режим)."""
    players = state.get("players", [])
    return any(uid in QUIPLASH_TEST_BOT_IDS for uid in players)


def _is_who_am_i_bot(uid: str) -> bool:
    return uid == WHO_AM_I_TEST_BOT_USER_ID


def _bot_funny_answer(prompt: str) -> str:
    """Ответ бота для тестового режима Quiplash (детерминированный банк)."""
    return random.choice(_BOT_ANSWERS)


def build_quiplash_card(state: dict, names: dict[str, str], game_id: int) -> dict:
    """Единая карточка в группе (cardId «quiplashGame» — меняется НА МЕСТЕ по фазам)."""
    phase = state.get("phase", "setup")
    rounds = state.get("config", {}).get("rounds", QUIPLASH_ROUNDS)
    round_num = state.get("round", 1)
    finish_btn = _btn("🏁 Finish game", "game_finish", game_id)

    if phase == "setup":
        players = state.get("players", [])
        roster = (
            ", ".join(names.get(p, p) for p in players)
            if players else "No one yet — press '🙋 I'm in!'"
        )
        widgets = [
            {"textParagraph": {"text": f"Players ({len(players)}): {roster}"}},
            {"buttonList": {"buttons": [
                _btn("🙋 I'm in!", "game_join", game_id),
                _btn("▶️ Start", "game_start", game_id),
                finish_btn,
            ]}},
        ]
        header = {"title": "Quiplash 🎮", "subtitle": f"Topic: {state.get('topic', '')}"}
    elif phase == "voting":
        answers = state.get("answers", {})
        items = list(answers.items())
        widgets = [
            {"textParagraph": {"text": f"Prompt: {state.get('prompt', '')}"}},
            {
                "selectionInput": {
                    "name": "vote",
                    "label": "Pick the funniest answer",
                    "type": "RADIO_BUTTON",
                    "items": [
                        {"text": f"#{i}. {text}", "value": author}
                        for i, (author, text) in enumerate(items, 1)
                    ],
                }
            },
            {"buttonList": {"buttons": [
                _btn("Submit vote", "game_vote", game_id),
                finish_btn,
            ]}},
        ]
        header = {"title": f"Round {round_num} — voting 🗳️", "subtitle": "Pick the funniest answer (not your own 😉)"}
    elif phase == "finished":
        widgets = [{"textParagraph": {"text": _final_standings_text(state, names)}}]
        header = {"title": "Quiplash 🏁", "subtitle": "Game over"}
    else:  # answering
        widgets = []
        if state.get("last_result"):
            widgets.append({"textParagraph": {"text": state["last_result"]}})
        widgets.append({"textParagraph": {"text": f"Round {round_num}/{rounds}: {state.get('prompt', '')}"}})
        widgets.append({"textParagraph": {"text": "✍️ Answer in DMs — answers stay hidden until voting 🤫"}})
        widgets.append({"buttonList": {"buttons": [finish_btn]}})
        header = {"title": f"Quiplash 🎮 — round {round_num}/{rounds}", "subtitle": state.get("topic", "")}

    return {"cardsV2": [{
        "cardId": "quiplashGame",
        "card": {"header": header, "sections": [{"widgets": widgets}]},
    }]}


def build_quiplash_answer_card(state: dict, game_id: int) -> dict:
    """Карточка ответа в личке: textInput + кнопка «Submit answer» (cardId «quiplashAnswer»)."""
    round_num = state.get("round", 1)
    rounds = state.get("config", {}).get("rounds", QUIPLASH_ROUNDS)
    return {"cardsV2": [{
        "cardId": "quiplashAnswer",
        "card": {
            "header": {"title": f"Round {round_num}/{rounds} — your answer", "subtitle": state.get("topic", "")},
            "sections": [{"widgets": [
                {"textParagraph": {"text": state.get("prompt", "")}},
                {
                    "textInput": {
                        "name": "answer",
                        "label": "Your funny answer",
                        "type": "MULTIPLE_LINE",
                        "hintText": "Write the funniest answer",
                    }
                },
                {"buttonList": {"buttons": [
                    _btn("Submit answer", "game_answer", game_id, round=round_num),
                ]}},
            ]}],
        },
    }]}


def _quiplash_answer_confirmation_card(state: dict) -> dict:
    """Карточка «✅ Answer received» в личке (тот же cardId, что и поле ответа)."""
    return {"cardsV2": [{
        "cardId": "quiplashAnswer",
        "card": {
            "header": {"title": "✅ Answer received", "subtitle": "Waiting for the others…"},
            "sections": [{"widgets": [{"textParagraph": {
                "text": f"Раунд {state.get('round', 1)}: {state.get('prompt', '')}\n\n"
                        "Your answer is saved. Voting starts when everyone answers 🤫"
            }}]}],
        },
    }]}


def _round_result_text(ranked: list[tuple[str, int]], names: dict[str, str]) -> str:
    """Строка результата раунда."""
    if not ranked:
        return "No one got votes 🤷"
    parts = []
    for i, (uid, _) in enumerate(ranked[:2], 1):
        pts = QUIPLASH_WINNER_POINTS if i == 1 else QUIPLASH_SECOND_POINTS
        parts.append(f"{i} place: {names.get(uid, uid)} (+{pts})")
    return "🏆 " + " | ".join(parts)


def _final_standings_text(state: dict, names: dict[str, str]) -> str:
    """Итоговая таблица очков."""
    scores = state.get("scores", {})
    if not scores:
        return "🏁 Result: no points."
    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    lines = ["🏁 Final results:"]
    for uid, pts in ordered:
        lines.append(f"  • {names.get(uid, uid)}: {pts}")
    return "\n".join(lines)


def build_who_am_i_card(state: dict, names: dict[str, str], game_id: int) -> dict:
    """Единая карточка «Кто я?» в группе (cardId «whoAmIGame»): ход + кнопка отмены."""
    phase = state.get("phase", "guessing")
    if phase == "finished":
        header = {"title": "Who am I? 🏁", "subtitle": "Game over"}
        widgets = [{"textParagraph": {"text": _final_standings_text(state, names)}}]
    else:
        current = state.get("current_guesser", "")
        header = {"title": "Who am I? 🎭", "subtitle": f"Topic: {state.get('topic', '')}"}
        widgets = [
            {"textParagraph": {"text": f"Current turn: {names.get(current, current)}"}},
            {"buttonList": {"buttons": [_btn("🏁 Finish game", "who_finish", game_id)]}},
        ]
    return {"cardsV2": [{
        "cardId": "whoAmIGame",
        "card": {"header": header, "sections": [{"widgets": widgets}]},
    }]}


def _now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


def _set_deadline(state: dict, seconds: int) -> None:
    state["phase_deadline"] = _now_ts() + seconds


# ---------------------------------------------------------------------------
# Работа с БД
# ---------------------------------------------------------------------------

async def _load_config(db: AsyncSession) -> dict:
    """Настройки игр из config с fallback на дефолты."""
    rows = (await db.execute(select(Config.key, Config.value))).all()
    cfg = {k: v for k, v in rows}

    def _int(key: str, default: int) -> int:
        v = cfg.get(key)
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    return {
        "rounds": _int("quiplash_rounds", QUIPLASH_ROUNDS),
        "winner_points": _int("quiplash_winner_points", QUIPLASH_WINNER_POINTS),
        "second_points": _int("quiplash_second_points", QUIPLASH_SECOND_POINTS),
        "who_am_i_guess_points": _int("who_am_i_guess_points", WHO_AM_I_GUESS_POINTS),
        "answer_timeout": _int("quiplash_answer_timeout_seconds", QUIPLASH_ANSWER_TIMEOUT_SECONDS),
        "vote_timeout": _int("quiplash_vote_timeout_seconds", QUIPLASH_VOTE_TIMEOUT_SECONDS),
        "turn_timeout": _int("who_am_i_turn_timeout_seconds", WHO_AM_I_TURN_TIMEOUT_SECONDS),
    }


async def load_weekly_answers(
    db: AsyncSession, week_start: date | None = None
) -> list[WeeklyAnswer]:
    """Публичные ответы участников за неделю (по умолчанию текущую)."""
    week = week_start or current_week_start()
    rows = (
        await db.execute(
            select(Answer, Profile.workspace_user_id)
            .join(Profile, Answer.profile_id == Profile.id)
            .where(Answer.week_start == week, Answer.is_public.is_(True))
        )
    ).all()
    return [
        WeeklyAnswer(
            user_id=ws or f"profile-{answer.profile_id}",
            question_id=answer.question_text,
            answer_text=answer.answer_text or answer.answer_choice or "",
            week_id=week.isoformat(),
        )
        for answer, ws in rows
    ]


async def get_active_game(db: AsyncSession, space_name: str) -> GameSession | None:
    """Активная игровая сессия в space (если есть)."""
    res = await db.execute(
        select(GameSession).where(
            GameSession.space_name == space_name,
            GameSession.status == "active",
        )
    )
    return res.scalar_one_or_none()


async def find_week_meeting(db: AsyncSession) -> MeetingInstance | None:
    """Ближайшая запланированная встреча текущей недели (или None)."""
    week_start = datetime.combine(current_week_start(), time.min, tzinfo=timezone.utc)
    week_end = week_start + timedelta(days=7)
    res = await db.execute(
        select(MeetingInstance)
        .where(
            MeetingInstance.scheduled_start >= week_start,
            MeetingInstance.scheduled_start < week_end,
            MeetingInstance.status == "scheduled",
        )
        .order_by(MeetingInstance.scheduled_start)
    )
    return res.scalars().first()


async def _profile_by_workspace(db: AsyncSession, user_id: str) -> Profile | None:
    res = await db.execute(
        select(Profile).where(Profile.workspace_user_id == user_id)
    )
    return res.scalar_one_or_none()


async def _resolve_names(db: AsyncSession, user_ids: list[str]) -> dict[str, str]:
    """user_id -> отображаемое имя (fallback на сам user_id)."""
    if not user_ids:
        return {}
    rows = (
        await db.execute(
            select(Profile.workspace_user_id, Profile.user_name).where(
                Profile.workspace_user_id.in_(user_ids)
            )
        )
    ).all()
    return {ws: (name or ws) for ws, name in rows}


async def _start_session(
    db: AsyncSession,
    space_name: str,
    game_type: str,
    topic: str,
    state: dict,
    meeting_instance_id: int | None = None,
) -> GameSession | None:
    session = GameSession(
        space_name=space_name,
        game_type=game_type,
        topic=topic,
        meeting_instance_id=meeting_instance_id,
        status="active",
        state=state,
    )
    db.add(session)
    try:
        await db.commit()
    except IntegrityError:
        # Гонка: кто-то уже стартовал активную игру в этом space (unique index).
        await db.rollback()
        return None
    await db.refresh(session)
    return session


async def setup_quiplash(db: AsyncSession, space_name: str) -> dict:
    """Создать партию Quiplash: тема + промпты, карточка в группу (фаза setup)."""
    if await get_active_game(db, space_name) is not None:
        return {"text": "A game is already running — finish it ('stop' or the '🏁 Finish game' button)."}

    cfg = await _load_config(db)
    rounds = cfg["rounds"]
    game = await generate_quiplash_game(rounds)
    topic = game.get("topic") or "General conversation"
    prompts = _pad(game.get("prompts", []), rounds)

    meeting = await find_week_meeting(db)
    if meeting is not None:
        meeting.activity_type = "quiplash"
        meeting.activity_data = {"topic": topic, "prompts": prompts}

    state = {
        "game": "quiplash",
        "phase": "setup",
        "round": 1,
        "topic": topic,
        "prompts": prompts,
        "prompt": prompts[0],
        "players": [],
        "answers": {},
        "votes": {},
        "scores": {},
        "config": cfg,
    }
    session = await _start_session(db, space_name, "quiplash", topic, state, meeting.id if meeting else None)
    if session is None:
        return {"text": "A game is already running — finish it first."}

    card = build_quiplash_card(state, {}, session.id)
    try:
        resp = await asyncio.to_thread(
            send_message, space_name, text="Quiplash! Join in 🎮", cards_v2=card["cardsV2"],
        )
        state["scoreboard_message_name"] = resp.get("name", "")
        session.state = state
        await db.commit()
    except Exception:
        logger.exception("quiplash_setup_post_failed space=%s", space_name)
    return {"silent": True}


async def _get_or_create_quiplash_bots(db: AsyncSession) -> list[Profile]:
    """Синтетические профили ботов для тестового режима (лениво создаются)."""
    bots: list[Profile] = []
    for i, bot_id in enumerate(QUIPLASH_TEST_BOT_IDS, 1):
        bot = (
            await db.execute(
                select(Profile).where(Profile.workspace_user_id == bot_id)
            )
        ).scalar_one_or_none()
        if bot is None:
            bot = Profile(
                workspace_user_id=bot_id,
                user_email=f"quiplash_bot{i}@test.local",
                user_name=f"Bot {i} 🤖",
            )
            db.add(bot)
            await db.flush()
        bots.append(bot)
    return bots


async def setup_quiplash_test(db: AsyncSession, space_name: str, user_profile: Profile) -> dict:
    """«квиплаш тест»: одиночная партия — игрок против бота (бот отвечает и голосует сам)."""
    if await get_active_game(db, space_name) is not None:
        return {"text": "A game is already running — finish it ('stop' or the '🏁 Finish game' button)."}

    cfg = await _load_config(db)
    cfg["rounds"] = QUIPLASH_TEST_ROUNDS
    game = await generate_quiplash_game(QUIPLASH_TEST_ROUNDS)
    topic = game.get("topic") or "General conversation"
    prompts = _pad(game.get("prompts", []), QUIPLASH_TEST_ROUNDS)

    await _get_or_create_quiplash_bots(db)
    players = [user_profile.workspace_user_id or "", *QUIPLASH_TEST_BOT_IDS]
    players = [p for p in players if p]

    meeting = await find_week_meeting(db)
    if meeting is not None:
        meeting.activity_type = "quiplash"
        meeting.activity_data = {"topic": topic, "prompts": prompts}

    state = {
        "game": "quiplash",
        "phase": "setup",
        "round": 1,
        "topic": topic,
        "prompts": prompts,
        "prompt": prompts[0],
        "players": players,
        "answers": {},
        "votes": {},
        "scores": {p: 0 for p in players},
        "config": cfg,
    }
    session = await _start_session(
        db, space_name, "quiplash", topic, state, meeting.id if meeting else None,
    )
    if session is None:
        return {"text": "A game is already running — finish it first."}

    names = await _resolve_names(db, players)
    card = build_quiplash_card(state, names, session.id)
    try:
        resp = await asyncio.to_thread(
            send_message, space_name, text="Quiplash (solo): you vs the bots! 🤖", cards_v2=card["cardsV2"],
        )
        state["scoreboard_message_name"] = resp.get("name", "")
        session.state = state
        await db.commit()
    except Exception:
        logger.exception("quiplash_test_setup_post_failed space=%s", space_name)
    return {"silent": True}


async def join_quiplash(db: AsyncSession, profile: Profile, game_id: int) -> dict:
    """Кнопка «🙋 I'm in!»: добавить игрока в партию, обновить карточку на месте."""
    session = await db.get(GameSession, game_id)
    if session is None or session.game_type != "quiplash":
        return {"text": "Game not found 🤷"}
    state = session.state or {}
    if state.get("phase") != "setup":
        return {"text": "Game already started 🚀"}

    players = list(state.get("players", []))
    ws = profile.workspace_user_id or ""
    if ws and ws not in players:
        players.append(ws)
    scores = state.get("scores", {})
    state["players"] = players
    state["scores"] = {p: scores.get(p, 0) for p in players}
    session.state = state
    await db.commit()

    names = await _resolve_names(db, players)
    return {"cards_v2": build_quiplash_card(state, names, session.id)["cardsV2"]}


async def start_quiplash_game(db: AsyncSession, game_id: int) -> dict:
    """Кнопка «▶️ Start»: проверка состава, старт раунда 1 + карточки ответов в личку."""
    session = await db.get(GameSession, game_id)
    if session is None or session.game_type != "quiplash":
        return {"text": "Game not found 🤷"}
    state = session.state or {}
    if state.get("phase") != "setup":
        return {"text": "Game already started 🚀"}

    players = list(state.get("players", []))
    if len(players) < 3:
        return {"text": "Need at least 3 players — press '🙋 I'm in!' 🙏"}

    cfg = state.get("config", {})
    state["phase"] = "answering"
    state["round"] = 1
    state["prompt"] = state["prompts"][0]
    state["answers"] = {}
    state["votes"] = {}
    state["last_result"] = ""
    _set_deadline(state, cfg.get("answer_timeout", QUIPLASH_ANSWER_TIMEOUT_SECONDS))
    session.state = state
    await db.commit()

    await _send_answer_cards(db, session, state)
    if _is_quiplash_solo(state):
        _schedule_quiplash_bot_tick(session.id)
    names = await _resolve_names(db, players)
    return {"cards_v2": build_quiplash_card(state, names, session.id)["cardsV2"]}


async def finish_quiplash(db: AsyncSession, game_id: int) -> dict:
    """Кнопка «🏁 Finish game»: завершить досрочно и показать итог."""
    session = await db.get(GameSession, game_id)
    if session is None or session.game_type != "quiplash":
        return {"text": "Game not found 🤷"}
    if session.status == "finished":
        return {"text": "Game already finished"}

    state = session.state or {}
    state["phase"] = "finished"
    session.state = state
    await _finish_game(db, session, state)
    names = await _resolve_names(db, list(state.get("scores", {}).keys()))
    return {"cards_v2": build_quiplash_card(state, names, session.id)["cardsV2"]}


async def finish_who_am_i(db: AsyncSession, game_id: int) -> dict:
    """Кнопка «🏁 Finish game» для «Кто я?»: завершить досрочно и показать итог."""
    session = await db.get(GameSession, game_id)
    if session is None or session.game_type != "who_am_i":
        return {"text": "Game not found 🤷"}
    if session.status == "finished":
        return {"text": "Game already finished"}

    state = session.state or {}
    state["phase"] = "finished"
    session.state = state
    await _finish_game(db, session, state)
    names = await _resolve_names(db, list(state.get("scores", {}).keys()))
    return {"cards_v2": build_who_am_i_card(state, names, session.id)["cardsV2"]}


async def start_who_am_i(db: AsyncSession, space_name: str, player_ids: list[str]) -> dict:
    """Запустить «Кто я?»: тема + сущности одним вызовом ИИ, секреты в DM."""
    if not player_ids:
        return {"text": "Couldn't determine the players 😕"}

    cfg = await _load_config(db)
    game = await generate_who_am_i_game(len(player_ids))
    topic = game.get("topic") or "General conversation"
    entities = _pad(game.get("entities", []), len(player_ids))
    secrets = dict(zip(player_ids, entities))

    # Привязать к встрече текущей недели, если она есть
    meeting = await find_week_meeting(db)
    if meeting is not None:
        meeting.activity_type = "who_am_i"
        meeting.activity_data = {"topic": topic, "entities": entities}

    state = {
        "game": "who_am_i",
        "phase": "guessing",
        "topic": topic,
        "order": list(player_ids),
        "secrets": secrets,
        "current_guesser": player_ids[0],
        "scores": {p: 0 for p in player_ids},
        "config": cfg,
    }
    _set_deadline(state, cfg["turn_timeout"])
    session = await _start_session(db, space_name, "who_am_i", topic, state, meeting.id if meeting else None)
    if session is None:
        return {"text": "A game is already running — finish it first."}

    missed = [uid for uid, entity in secrets.items() if not await _dm_secret(db, uid, entity)]

    names = await _resolve_names(db, player_ids)
    text = f"🎭 'Who am I?'! Topic: {topic}\n\nSecrets were sent to your DMs."
    if missed:
        miss_names = await _resolve_names(db, missed)
        text += (
            "\n⚠️ Couldn't DM: "
            + ", ".join(miss_names.get(u, u) for u in missed)
            + " — open a DM with the bot and write 'my secret'."
        )
    text += f"\n\n{names.get(player_ids[0], player_ids[0])} starts: ask the others 'yes/no' questions!"

    card = build_who_am_i_card(state, names, session.id)
    try:
        resp = await asyncio.to_thread(
            send_message, space_name, text=text, cards_v2=card["cardsV2"],
        )
        state["scoreboard_message_name"] = resp.get("name", "")
        session.state = state
        await db.commit()
    except Exception:
        logger.exception("who_am_i_start_post_failed space=%s", space_name)
    return {"silent": True}


async def _get_or_create_who_am_i_bot(db: AsyncSession) -> Profile:
    """Синтетический профиль бота для тестового режима «Кто я?» (лениво создаётся)."""
    bot = (
        await db.execute(
            select(Profile).where(Profile.workspace_user_id == WHO_AM_I_TEST_BOT_USER_ID)
        )
    ).scalar_one_or_none()
    if bot is None:
        bot = Profile(
            workspace_user_id=WHO_AM_I_TEST_BOT_USER_ID,
            user_email="who_am_i_bot@test.local",
            user_name="Bot 🤖",
        )
        db.add(bot)
        await db.flush()
    return bot


async def setup_who_am_i_test(db: AsyncSession, space_name: str, user_profile: Profile) -> dict:
    """«кто я тест»: одиночная партия — игрок против бота (бот угадывает сам)."""
    if await get_active_game(db, space_name) is not None:
        return {"text": "A game is already running — finish it ('stop' or the '🏁 Finish game' button)."}

    bot = await _get_or_create_who_am_i_bot(db)
    player_ids = [p for p in (user_profile.workspace_user_id or "", WHO_AM_I_TEST_BOT_USER_ID) if p]

    cfg = await _load_config(db)
    game = await generate_who_am_i_game(len(player_ids))
    topic = game.get("topic") or "General conversation"
    entities = _pad(game.get("entities", []), len(player_ids))
    secrets = dict(zip(player_ids, entities))

    meeting = await find_week_meeting(db)
    if meeting is not None:
        meeting.activity_type = "who_am_i"
        meeting.activity_data = {"topic": topic, "entities": entities}

    state = {
        "game": "who_am_i",
        "phase": "guessing",
        "topic": topic,
        "order": player_ids,
        "secrets": secrets,
        "current_guesser": player_ids[0],
        "scores": {p: 0 for p in player_ids},
        "config": cfg,
    }
    _set_deadline(state, cfg["turn_timeout"])
    session = await _start_session(
        db, space_name, "who_am_i", topic, state, meeting.id if meeting else None,
    )
    if session is None:
        return {"text": "A game is already running — finish it first."}

    # Секрет в личку шлём только человеку (боту DM не нужен).
    missed = [
        uid for uid in player_ids
        if not _is_who_am_i_bot(uid) and not await _dm_secret(db, uid, secrets.get(uid, ""))
    ]

    names = await _resolve_names(db, player_ids)
    text = f"🎭 \'Who am I?\' (solo): you vs the bot! 🤖\n\nTopic: {topic}\nYour secret is in your DMs."
    if missed:
        miss_names = await _resolve_names(db, missed)
        text += (
            "\n⚠️ Couldn't DM: "
            + ", ".join(miss_names.get(u, u) for u in missed)
            + " — open a DM with the bot and write 'my secret'."
        )
    text += f"\n\nYou start: write 'I guess: <who you are>'."

    card = build_who_am_i_card(state, names, session.id)
    try:
        resp = await asyncio.to_thread(
            send_message, space_name, text=text, cards_v2=card["cardsV2"],
        )
        state["scoreboard_message_name"] = resp.get("name", "")
        session.state = state
        await db.commit()
    except Exception:
        logger.exception("who_am_i_test_setup_post_failed space=%s", space_name)
    return {"silent": True}


async def _dm_secret(db: AsyncSession, uid: str, entity: str) -> bool:
    """Submit секрет игроку в его DM с ботом. True — отправлено."""
    from app.services.broadcast import ensure_profile_dm

    profile = await _profile_by_workspace(db, uid)
    if profile is None:
        return False
    try:
        if not await ensure_profile_dm(db, profile):
            return False
        await asyncio.to_thread(
            send_text,
            profile.chat_space_id,
            f"🤫 You are {entity}. Ask 'yes/no' questions to guess who you are!",
        )
        return True
    except Exception:
        logger.exception("dm_secret_failed uid=%s", uid)
        return False


async def _who_am_i_secret(db: AsyncSession, state: dict, user_id: str) -> dict:
    """Повторно отправить секрет игроку в личку."""
    secret = state.get("secrets", {}).get(user_id, "")
    if not secret:
        return {"text": "You have no secret in this game 🤷"}
    if await _dm_secret(db, user_id, secret):
        return {"text": "Secret sent to your DMs 🤫"}
    return {"text": "Can't DM you — open a DM with the bot and write 'my secret' again."}


async def _post_to_space(space_name: str, message: dict) -> None:
    """Проактивно отправить сообщение/карточку в space (неблокирующе)."""
    if not space_name:
        return
    try:
        if "cardsV2" in message:
            await asyncio.to_thread(send_message, space_name, cards_v2=message["cardsV2"])
        elif message.get("text"):
            await asyncio.to_thread(send_text, space_name, message["text"])
    except Exception:
        logger.exception("post_to_space_failed space=%s", space_name)


# ---------------------------------------------------------------------------
# Обработка входящих сообщений и кликов
# ---------------------------------------------------------------------------

async def handle_message(
    db: AsyncSession, space_name: str, user_id: str, text: str
) -> dict | None:
    """Обработать сообщение, если в space идёт игра. None — игры нет."""
    session = await get_active_game(db, space_name)
    if session is None:
        return None

    state = session.state or {}
    lowered = text.lower().strip()

    ctrl = await _handle_control_command(db, session, state, lowered)
    if ctrl is not None:
        return ctrl

    if session.game_type == "quiplash":
        return _quiplash_reminder(state)
    if session.game_type == "who_am_i":
        return await _handle_who_am_i_message(db, session, state, user_id, text, lowered)
    return None


async def _handle_control_command(
    db: AsyncSession, session: GameSession, state: dict, lowered: str
) -> dict | None:
    """Управляющие команды, общие для группы и лички: «стоп», «счёт». None — не команда."""
    if lowered in ("стоп", "отмена", "stop", "cancel"):
        session.status = "cancelled"
        await db.commit()
        return {"text": "Game stopped 🛑"}
    if lowered in ("счёт", "счет", "score"):
        names = await _resolve_names(db, list(state.get("scores", {}).keys()))
        return {"text": _final_standings_text(state, names)}
    return None


async def handle_dm_message(db: AsyncSession, user_id: str, text: str) -> dict | None:
    """Сообщение в личку во время игры. None — у игрока нет активной игры.

    Ответ Quiplash приходит через карточку (кнопка «Submit answer»), поэтому
    свободный текст здесь лишь напоминает об этом. Для «Кто я?» — повторный
    запрос секрета («my secret»).
    """
    sessions = (
        await db.execute(select(GameSession).where(GameSession.status == "active"))
    ).scalars().all()
    for session in sessions:
        state = session.state or {}
        if user_id not in (state.get("players") or []):
            continue
        lowered = text.lower().strip()
        ctrl = await _handle_control_command(db, session, state, lowered)
        if ctrl is not None:
            return ctrl
        if session.game_type == "quiplash":
            return {"text": "Send your answer via the card in your DMs — press the 'Submit answer' button 🤫"}
        if session.game_type == "who_am_i":
            return await _handle_who_am_i_dm(db, state, user_id, lowered)
    return None


async def _handle_who_am_i_dm(db: AsyncSession, state: dict, user_id: str, lowered: str) -> dict:
    """В личке во время «Кто я?» — повторно выслать секрет по запросу."""
    if lowered in ("my secret", "my secret", "show my secret", "my secret"):
        return await _who_am_i_secret(db, state, user_id)
    return {}


def _quiplash_reminder(state: dict) -> dict:
    """Напомнить текущую фазу/промпт текстом (карточка обновляется на месте)."""
    phase = state.get("phase")
    rounds = state.get("config", {}).get("rounds", QUIPLASH_ROUNDS)
    if phase == "voting":
        return {"text": "Voting is underway — pick the funniest answer in the group card 👇"}
    if phase == "setup":
        return {"text": "Game hasn't started — press '🙋 I'm in!' to join."}
    return {"text": f"Раунд {state.get('round', 1)}/{rounds}: {state.get('prompt', '')}\n\nОтвет пришли через карточку в личке 🤫"}


async def handle_card_action(
    db: AsyncSession,
    game_id: int,
    user_id: str,
    method: str,
    form_inputs: dict | None = None,
    params: dict | None = None,
    profile: Profile | None = None,
) -> dict | None:
    """Обработать клик по карточке Quiplash (join/start/answer/vote/finish)."""
    if method == "game_join":
        if profile is None:
            return {"text": "Couldn't identify you 😕"}
        return await join_quiplash(db, profile, game_id)

    if method == "who_finish":
        return await finish_who_am_i(db, game_id)

    session = await db.get(GameSession, game_id)
    if session is None or session.game_type != "quiplash":
        return {"text": "Game not found 🤷"}
    state = session.state or {}

    if method == "game_start":
        return await start_quiplash_game(db, game_id)
    if method == "game_answer":
        return await submit_quiplash_answer(db, session, state, user_id, form_inputs, params)
    if method == "game_vote":
        return await submit_quiplash_vote(db, session, state, user_id, form_inputs)
    if method == "game_finish":
        return await finish_quiplash(db, game_id)
    return {"text": "Unknown action 🤷"}


async def submit_quiplash_answer(
    db: AsyncSession, session: GameSession, state: dict, user_id: str,
    form_inputs: dict | None, params: dict | None,
) -> dict:
    """Записать ответ из карточки в личке; при полном сборе — открыть голосование в группе."""
    players = state.get("players", [])
    if user_id not in players:
        return {"text": "You're not in this game 🙂"}
    if state.get("phase") != "answering":
        return {"text": "It's not time to answer ⏳"}

    # Защита от устаревшей карточки (номер раунда в параметрах кнопки).
    if params and params.get("round"):
        try:
            if int(params["round"]) != state.get("round", 1):
                return {"text": "That round is over — check the fresh card 😉"}
        except (TypeError, ValueError):
            pass

    answers = state.get("answers", {})
    if user_id in answers:
        return {"text": "You already answered this round 😉"}

    text = _first_form_value(form_inputs or {}, "answer")
    if not text.strip():
        return {"text": "The answer field is empty — write something 😊"}

    answers[user_id] = text.strip()
    state["answers"] = answers
    session.state = state
    await db.commit()

    confirmation = _quiplash_answer_confirmation_card(state)
    remaining = [p for p in players if p not in answers]
    if remaining:
        return {"cards_v2": confirmation["cardsV2"]}

    await _open_voting(db, session, state)
    return {"cards_v2": confirmation["cardsV2"]}


async def submit_quiplash_vote(
    db: AsyncSession, session: GameSession, state: dict, user_id: str, form_inputs: dict | None
) -> dict:
    """Записать голос; последний голос закрывает раунд и возвращает карточку следующего."""
    players = state.get("players", [])
    if user_id not in players:
        return {"text": "You're not in this game 🙂"}
    if state.get("phase") != "voting":
        return {"text": "It's not time to vote ⏳"}

    votes = state.get("votes", {})
    if user_id in votes:
        return {"text": "You already voted ✅"}

    vote_for = _first_form_value(form_inputs or {}, "vote")
    if not vote_for:
        return {"text": "No option selected 😕"}
    if vote_for == user_id:
        # Свой вариант в карточке есть, но голос за него просто не засчитываем —
        # без отдельного сообщения в группу.
        return {"silent": True}

    votes[user_id] = vote_for
    state["votes"] = votes

    answered = [p for p in players if p in state.get("answers", {})]
    if len(votes) < len(answered):
        session.state = state
        await db.commit()
        return {"silent": True}

    return await _finalize_quiplash_round(db, session, state)


async def _patch_group(session: GameSession, state: dict, cards_v2: list[dict]) -> None:
    """Обновить карточку в группе НА МЕСТЕ (messages.patch)."""
    msg_name = state.get("scoreboard_message_name", "")
    if not msg_name:
        return
    try:
        await asyncio.to_thread(patch_message, msg_name, cards_v2=cards_v2)
    except Exception:
        logger.exception("quiplash_group_patch_failed game=%s", session.id)


async def _send_answer_cards(db: AsyncSession, session: GameSession, state: dict) -> None:
    """Разослать карточки ответа в личку каждому игроку (запомнить имена сообщений)."""
    card = build_quiplash_answer_card(state, session.id)
    names: dict[str, str] = {}
    for uid in state.get("players", []):
        dm = await asyncio.to_thread(find_user_dm_space, uid)
        if not dm:
            logger.warning("quiplash_dm_not_found player=%s", uid)
            continue
        try:
            resp = await asyncio.to_thread(send_message, dm, text="", cards_v2=card["cardsV2"])
            names[uid] = resp.get("name", "")
        except Exception:
            logger.exception("quiplash_dm_send_failed player=%s", uid)
    state["answer_message_names"] = names
    session.state = state
    await db.commit()


async def _open_voting(db: AsyncSession, session: GameSession, state: dict) -> None:
    """Перевести раунд в фазу голосования и обновить карточку в группе на месте."""
    cfg = state.get("config", {})
    state["phase"] = "voting"
    state["votes"] = {}
    _set_deadline(state, cfg.get("vote_timeout", QUIPLASH_VOTE_TIMEOUT_SECONDS))
    session.state = state
    await db.commit()
    await _patch_group(session, state, build_quiplash_card(state, {}, session.id)["cardsV2"])
    if _is_quiplash_solo(state):
        _schedule_quiplash_bot_tick(session.id)


async def _advance_round(db: AsyncSession, session: GameSession, state: dict) -> None:
    """Перейти к следующему раунду: промпт, дедлайн, новые карточки ответов в личку."""
    cfg = state.get("config", {})
    round_num = state.get("round", 1) + 1
    state["round"] = round_num
    state["phase"] = "answering"
    state["prompt"] = state["prompts"][round_num - 1]
    state["answers"] = {}
    state["votes"] = {}
    _set_deadline(state, cfg.get("answer_timeout", QUIPLASH_ANSWER_TIMEOUT_SECONDS))
    session.state = state
    await db.commit()
    await _send_answer_cards(db, session, state)
    if _is_quiplash_solo(state):
        _schedule_quiplash_bot_tick(session.id)


def _schedule_quiplash_bot_tick(game_id: int) -> None:
    """Запланировать авто-ход бота Quiplash (ответ/голос) через APScheduler."""
    from app.scheduler import scheduler

    if scheduler is None:
        return
    run_at = datetime.now(timezone.utc) + timedelta(seconds=3)
    scheduler.add_job(
        _quiplash_bot_tick, "date", run_date=run_at,
        id=f"quiplash_bot_{game_id}", replace_existing=True, args=[game_id],
    )


async def _quiplash_bot_tick(game_id: int) -> None:
    """Авто-ход бота в тестовой партии: ответить в фазе answering, голосовать в voting."""
    async with AsyncSessionLocal() as db:
        session = await db.get(GameSession, game_id)
        if session is None or session.status != "active":
            return
        state = session.state or {}
        if not _is_quiplash_solo(state):
            return
        phase = state.get("phase")
        if phase == "answering":
            await _bot_answer_quiplash(db, session, state)
        elif phase == "voting":
            await _bot_vote_quiplash(db, session, state)


async def _bot_answer_quiplash(db: AsyncSession, session: GameSession, state: dict) -> None:
    """Боты записывают ответы; если все ответили — открыть голосование."""
    answers = state.get("answers", {})
    players = state.get("players", [])
    changed = False
    for bot_id in QUIPLASH_TEST_BOT_IDS:
        if bot_id not in players or bot_id in answers:
            continue
        answers[bot_id] = _bot_funny_answer(state.get("prompt", ""))
        changed = True
    if not changed:
        return
    state["answers"] = answers
    session.state = state
    await db.commit()

    remaining = [p for p in players if p not in state.get("answers", {})]
    if not remaining:
        await _open_voting(db, session, state)


async def _bot_vote_quiplash(db: AsyncSession, session: GameSession, state: dict) -> None:
    """Боты голосуют за случайный чужой ответ; последний голос закрывает раунд."""
    votes = state.get("votes", {})
    answers = state.get("answers", {})
    players = state.get("players", [])
    changed = False
    for bot_id in QUIPLASH_TEST_BOT_IDS:
        if bot_id not in players or bot_id in votes:
            continue
        candidates = [a for a in answers if a != bot_id]
        if not candidates:
            continue
        votes[bot_id] = random.choice(candidates)
        changed = True
    if not changed:
        return
    state["votes"] = votes
    session.state = state
    await db.commit()

    answered = [p for p in players if p in state.get("answers", {})]
    if len(votes) < len(answered):
        return
    result = await _finalize_quiplash_round(db, session, state)
    cards_v2 = result.get("cards_v2")
    if cards_v2:
        await _patch_group(session, state, cards_v2)


async def _finalize_quiplash_round(db: AsyncSession, session: GameSession, state: dict) -> dict:
    """Подсчёт раунда по голосам; возврат карточки следующего раунда или итога."""
    cfg = state.get("config", {})
    ranked = tally_votes(state.get("votes", {}))
    state["scores"] = apply_round_points(
        state.get("scores", {}), ranked,
        cfg.get("winner_points", QUIPLASH_WINNER_POINTS),
        cfg.get("second_points", QUIPLASH_SECOND_POINTS),
    )
    names = await _resolve_names(db, [uid for uid, _ in ranked])
    state["last_result"] = _round_result_text(ranked, names)

    round_num = state.get("round", 1)
    rounds = cfg.get("rounds", QUIPLASH_ROUNDS)
    if round_num >= rounds:
        state["phase"] = "finished"
        session.state = state
        await _finish_game(db, session, state)
        all_names = await _resolve_names(db, list(state.get("scores", {}).keys()))
        return {"cards_v2": build_quiplash_card(state, all_names, session.id)["cardsV2"]}

    await _advance_round(db, session, state)
    all_names = await _resolve_names(db, list(state.get("scores", {}).keys()))
    return {"cards_v2": build_quiplash_card(state, all_names, session.id)["cardsV2"]}


async def _skip_quiplash_round(db: AsyncSession, session: GameSession, state: dict) -> dict:
    """Никто не ответил — пропустить раунд без очков, вернуть карточку следующего."""
    cfg = state.get("config", {})
    round_num = state.get("round", 1)
    rounds = cfg.get("rounds", QUIPLASH_ROUNDS)
    state["last_result"] = f"⏰ No one answered in round {round_num} — skipping."

    if round_num >= rounds:
        state["phase"] = "finished"
        session.state = state
        await _finish_game(db, session, state)
        all_names = await _resolve_names(db, list(state.get("scores", {}).keys()))
        return {"cards_v2": build_quiplash_card(state, all_names, session.id)["cardsV2"]}

    await _advance_round(db, session, state)
    all_names = await _resolve_names(db, list(state.get("scores", {}).keys()))
    return {"cards_v2": build_quiplash_card(state, all_names, session.id)["cardsV2"]}


async def _handle_who_am_i_message(
    db: AsyncSession, session: GameSession, state: dict, user_id: str, text: str, lowered: str
) -> dict:
    current = state.get("current_guesser")
    if current is None:
        return {"text": "Game over 🏁"}

    # Переслать/показать свой секрет (fallback, если DM недоступен)
    if lowered in ("my secret", "my secret", "show my secret", "my secret"):
        return await _who_am_i_secret(db, state, user_id)

    if lowered in ("пропустить", "skip", "пас"):
        if user_id != current:
            return {"text": "It's another player's turn 😊"}
        names = await _resolve_names(db, [user_id])
        return await _advance_guesser(
            db, session, state,
            prefix=f"⏭️ {names.get(user_id, user_id)} skipped their turn.\n",
        )

    if lowered.startswith(("угадываю", "guess", "я думаю", "я -", "я —", "я это")):
        return await _check_guess(db, session, state, user_id, current, _guess_text(text))

    # Вопросы/ответы «да/нет» идут между людьми — бот их не перехватывает
    return {}


async def _check_guess(
    db: AsyncSession, session: GameSession, state: dict, user_id: str, current: str, guess: str
) -> dict:
    if user_id != current:
        return {"text": "It's not your turn to guess 😊"}

    secret = state.get("secrets", {}).get(current, "")
    if not secret or not guess:
        return {"text": "Didn't get that. Write 'I guess: <who you are>'."}

    matched = _entities_match(secret, guess)
    if not matched:
        # ИИ-судья ловит синонимы/перефразировки, которые пропустил матчер
        matched = await judge_guess(secret, guess) is True

    if matched:
        cfg = state.get("config", {})
        scores = state.get("scores", {})
        scores[current] = scores.get(current, 0) + cfg.get("who_am_i_guess_points", WHO_AM_I_GUESS_POINTS)
        state["scores"] = scores
        names = await _resolve_names(db, [current])
        return await _advance_guesser(
            db, session, state,
            prefix=f"✅ {names.get(current, current)} guessed it! It's: {secret}\n",
        )

    return {"text": "Not it! Keep asking questions or try again 😉"}


async def _advance_guesser(
    db: AsyncSession, session: GameSession, state: dict, prefix: str = ""
) -> dict:
    order = state.get("order", [])
    current = state.get("current_guesser")
    idx = order.index(current) if current in order else -1
    next_idx = idx + 1

    if next_idx >= len(order):
        names = await _resolve_names(db, list(state.get("scores", {}).keys()))
        await _finish_game(db, session, state)
        return {"text": prefix + "\n" + _final_standings_text(state, names)}

    state["current_guesser"] = order[next_idx]
    cfg = state.get("config", {})
    _set_deadline(state, cfg.get("turn_timeout", WHO_AM_I_TURN_TIMEOUT_SECONDS))
    session.state = state
    await db.commit()

    if _is_who_am_i_bot(order[next_idx]):
        _schedule_who_am_i_bot_tick(session.id)

    names = await _resolve_names(db, [order[next_idx]])
    nxt = names.get(order[next_idx], order[next_idx])
    return {"text": f"{prefix}\nNext: {nxt} — ask 'yes/no' questions!"}


def _schedule_who_am_i_bot_tick(game_id: int) -> None:
    """Запланировать авто-ход бота «Кто я?» через APScheduler."""
    from app.scheduler import scheduler

    if scheduler is None:
        return
    run_at = datetime.now(timezone.utc) + timedelta(seconds=3)
    scheduler.add_job(
        _who_am_i_bot_tick, "date", run_date=run_at,
        id=f"who_am_i_bot_{game_id}", replace_existing=True, args=[game_id],
    )


async def _who_am_i_bot_tick(game_id: int) -> None:
    """Авто-ход бота «Кто я?»: угадать свой секрет и передать ход/завершить."""
    async with AsyncSessionLocal() as db:
        session = await db.get(GameSession, game_id)
        if session is None or session.status != "active":
            return
        state = session.state or {}
        current = state.get("current_guesser")
        if current != WHO_AM_I_TEST_BOT_USER_ID:
            return
        secret = state.get("secrets", {}).get(current, "")
        if not secret:
            return

        cfg = state.get("config", {})
        scores = state.get("scores", {})
        scores[current] = scores.get(current, 0) + cfg.get("who_am_i_guess_points", WHO_AM_I_GUESS_POINTS)
        state["scores"] = scores
        names = await _resolve_names(db, [current])
        result = await _advance_guesser(
            db, session, state,
            prefix=f"✅ {names.get(current, current)} guessed it! It's: {secret}\n",
        )
        await _post_to_space(session.space_name, result)


async def _finish_game(db: AsyncSession, session: GameSession, state: dict) -> None:
    """Подбить очки в leaderboard_ledger (event_type 'game') и закрыть сессию.

    Начисление через award_points (идемпотентно, on_conflict_do_nothing). За счёт
    UNIQUE(profile_id, meeting_instance_id, event_type) у одного профиля в рамках
    одной встречи будет одна запись 'game' — суммарные очки за игру активности.
    """
    scores = state.get("scores", {})
    for uid, pts in scores.items():
        if not pts:
            continue
        profile = await _profile_by_workspace(db, uid)
        if profile is None:
            continue
        await award_points(
            db,
            profile.id,
            "game",
            pts,
            meeting_instance_id=session.meeting_instance_id,
            reason=f"{session.game_type} — final points",
            metadata={"game_type": session.game_type},
        )
    session.status = "finished"
    await db.commit()


# ---------------------------------------------------------------------------
# Таймауты (вызывается планировщиком из lifespan)
# ---------------------------------------------------------------------------

async def close_stale_games() -> None:
    """Закрыть просроченные фазы активных игр (ответы/голосование/ход)."""
    now = _now_ts()
    try:
        async with AsyncSessionLocal() as db:
            sessions = (
                await db.execute(
                    select(GameSession).where(GameSession.status == "active")
                )
            ).scalars().all()
            for session in sessions:
                state = session.state or {}
                deadline = state.get("phase_deadline")
                if not isinstance(deadline, (int, float)) or now < deadline:
                    continue
                if session.game_type == "quiplash":
                    await _timeout_quiplash(db, session, state)
                elif session.game_type == "who_am_i":
                    await _timeout_who_am_i(db, session, state)
    except Exception:
        logger.exception("close_stale_games_failed")


async def _timeout_quiplash(db: AsyncSession, session: GameSession, state: dict) -> None:
    phase = state.get("phase")
    if phase == "answering":
        if not state.get("answers"):
            result = await _skip_quiplash_round(db, session, state)
            await _patch_group(session, state, result["cards_v2"])
            return
        await _open_voting(db, session, state)
    elif phase == "voting":
        result = await _finalize_quiplash_round(db, session, state)
        await _patch_group(session, state, result["cards_v2"])


async def _timeout_who_am_i(db: AsyncSession, session: GameSession, state: dict) -> None:
    current = state.get("current_guesser")
    if current is None:
        return
    names = await _resolve_names(db, [current])
    prefix = f"⏰ {names.get(current, current)} ran out of time — skipping.\n"
    result = await _advance_guesser(db, session, state, prefix=prefix)
    await _post_to_space(session.space_name, result)
