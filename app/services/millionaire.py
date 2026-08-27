"""Игра «Кто хочет стать миллионером» (Millionaire) — соло в личке против бота.

15 вопросов с растущей сложностью (5 тиров × 3 вопроса), нацеленных на изучение
и улучшение английского. Баллы начисляются ТОЛЬКО за полное прохождение (все 15
верных). Неправильный ответ — конец игры (классика): показываем правильный ответ
и объяснение, баллы не начисляем.

Подсказки (по одной на партию):
- 50:50  — убирает два неверных варианта;
- Hint   — показывает объяснение к текущему вопросу.

Состояние живёт в game_sessions.state (JSONB), `game_type = 'millionaire'`,
поэтому переживает рестарты приложения. Рейтинг — отдельная таблица
millionaire_scores (НЕ общий leaderboard_ledger): +completion_points за прохождение.

Вход:
- start_millionaire    — создать партию (кнопка «Millionaire» из меню ДМ-игр).
- answer               — ответ на текущий вопрос (параметр answer = индекс варианта).
- use_5050             — подсказка 50:50.
- use_hint             — подсказка (показать объяснение).
- new_game / quit_game — закрыть активную партию и начать заново / просто выйти.
- leaderboard_response — топ-N.
"""
import logging
import random

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Config, GameSession, MillionaireScore, Profile
from app.services import party_games
from app.services.millionaire_bank import pick_millionaire_game

logger = logging.getLogger(__name__)

TOTAL_QUESTIONS = 15
COMPLETION_POINTS_DEFAULT = 15

TIER_LABELS = {1: "Warm-up", 2: "Easy", 3: "Medium", 4: "Hard", 5: "Expert"}
OPTION_LETTERS = ("A", "B", "C", "D")


def _action_url() -> str:
    """URL эндпоинта — в add-on режиме кнопка доставляет клик только при function=URL."""
    return get_settings().chat_app_audience or "millionaire"


async def _load_millionaire_config(db: AsyncSession) -> dict:
    """Параметры «Миллионера» из config с fallback на дефолты."""
    rows = (await db.execute(select(Config.key, Config.value))).all()
    cfg = {k: v for k, v in rows}

    def _int(key: str, default: int) -> int:
        v = cfg.get(key)
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    return {
        "completion_points": _int("millionaire_completion_points", COMPLETION_POINTS_DEFAULT),
        "total_questions": _int("millionaire_total_questions", TOTAL_QUESTIONS),
    }


# ---------------------------------------------------------------------------
# Чистые хелперы
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Карточки
# ---------------------------------------------------------------------------

def build_millionaire_card(state: dict, game_id: int) -> dict:
    """Карточка текущего вопроса (cardId «millionaire») — обновляется на месте."""
    questions = state.get("questions", [])
    level = state.get("level", 1)
    if not questions or not (1 <= level <= len(questions)):
        return {"text": "Game not found 🤷"}

    question = questions[level - 1]
    tier = question.get("tier", 1)
    tier_label = TIER_LABELS.get(tier, "")
    total = len(questions)
    eliminated = set(state.get("eliminated", []))
    hint_shown = state.get("hint_shown", False)
    fifty_used = state.get("fifty_used", False)
    hint_used = state.get("hint_used", False)

    body = f"**Question {level}/{total}** · {tier_label}\n\n{question['prompt']}"
    if hint_shown:
        body += f"\n\n💡 Hint: {question['explanation']}"

    answer_buttons = []
    for i, opt in enumerate(question["options"]):
        if i in eliminated:
            continue
        answer_buttons.append(
            _btn(f"{OPTION_LETTERS[i]}. {opt}", "millionaire_answer", game_id, answer=i)
        )

    widgets = [{"textParagraph": {"text": body}}]
    widgets.append({"buttonList": {"buttons": answer_buttons}})

    lifelines = []
    if not fifty_used:
        lifelines.append(_btn("🎯 50:50", "millionaire_5050", game_id))
    if not hint_used:
        lifelines.append(_btn("💡 Hint", "millionaire_hint", game_id))
    if lifelines:
        widgets.append({"buttonList": {"buttons": lifelines}})

    widgets.append({"buttonList": {"buttons": [_btn("🛑 Quit", "millionaire_quit", game_id)]}})

    return {"cardsV2": [{
        "cardId": "millionaire",
        "card": {
            "header": {
                "title": "Millionaire 💎",
                "subtitle": f"Question {level}/{total} · {tier_label}",
            },
            "sections": [{"widgets": widgets}],
        },
    }]}


def _finish_card(state: dict, game_id: int, won: bool, delta: int) -> dict:
    """Финальная карточка (победа или конец игры) с кнопками «Новая игра»/«Рейтинг»."""
    questions = state.get("questions", [])
    level = state.get("level", 1)
    total = len(questions) or TOTAL_QUESTIONS
    question = questions[level - 1] if questions and 1 <= level <= len(questions) else None

    if won:
        title = "🎉 You won!"
        body = (
            f"Incredible! You answered all **{total}** questions correctly!\n\n"
            f"+{delta} to the Millionaire rating 🏆"
        )
    else:
        title = "❌ Wrong answer"
        if question is not None:
            correct = question["options"][question["answer"]]
            body = (
                f"That's not right.\n\n"
                f"Correct answer: **{correct}**\n\n"
                f"💡 {question['explanation']}\n\n"
                f"You reached question {level}/{total}."
            )
        else:
            body = "Game over."

    return {"cardsV2": [{
        "cardId": "millionaire",
        "card": {
            "header": {"title": title, "subtitle": "Millionaire"},
            "sections": [{"widgets": [
                {"textParagraph": {"text": body}},
                {"buttonList": {"buttons": [
                    _btn("🆕 New game", "millionaire_new", game_id),
                ]}},
            ]}],
        },
    }]}


# ---------------------------------------------------------------------------
# Игровой цикл
# ---------------------------------------------------------------------------

async def _get_or_create_score(db: AsyncSession, profile_id: int) -> MillionaireScore:
    row = (
        await db.execute(select(MillionaireScore).where(MillionaireScore.profile_id == profile_id))
    ).scalar_one_or_none()
    if row is None:
        row = MillionaireScore(profile_id=profile_id, completed=0, best_level=0, points=0)
        db.add(row)
        await db.flush()
    return row


async def start_millionaire(db: AsyncSession, space_name: str, profile: Profile) -> dict:
    """Создать партию: выбрать 15 вопросов и вернуть карточку первого вопроса."""
    if await party_games.get_active_game(db, space_name) is not None:
        return {"text": "A game is already running — finish it or press «🆕 New game»."}

    questions = pick_millionaire_game()
    if len(questions) < TOTAL_QUESTIONS:
        return {"text": "Not enough questions in the bank 🤷"}

    state = {
        "game": "millionaire",
        "level": 1,
        "questions": questions,
        "hint_used": False,
        "hint_shown": False,
        "fifty_used": False,
        "eliminated": [],
        "config": await _load_millionaire_config(db),
    }
    session = await party_games._start_session(db, space_name, "millionaire", "Millionaire", state)
    if session is None:
        return {"text": "A game is already running — finish it first."}
    return build_millionaire_card(state, session.id)


async def _active_millionaire_session(db: AsyncSession, game_id: int) -> GameSession | None:
    """Активная millionaire-сессия по id, иначе None."""
    session = await db.get(GameSession, game_id)
    if session is None or session.game_type != "millionaire" or session.status != "active":
        return None
    return session


async def answer(db: AsyncSession, game_id: int, profile: Profile, answer_index: int) -> dict:
    """Ответ на текущий вопрос: верно → следующий вопрос/победа; неверно → конец игры."""
    session = await _active_millionaire_session(db, game_id)
    if session is None:
        return {"text": "Game not found 🤷"}
    state = session.state or {}

    questions = state.get("questions", [])
    level = state.get("level", 1)
    if not questions or not (1 <= level <= len(questions)):
        return {"text": "Game not found 🤷"}

    question = questions[level - 1]
    correct = question["answer"]
    cfg = state.get("config") or await _load_millionaire_config(db)
    completion_points = cfg.get("completion_points", COMPLETION_POINTS_DEFAULT)
    total = len(questions)

    if answer_index == correct:
        if level >= total:
            # Победа: все вопросы пройдены — начисляем баллы только здесь.
            state["won"] = True
            # CAS: только один финальный клик начисляет счёт и закрывает сессию.
            res = await db.execute(
                update(GameSession)
                .where(GameSession.id == session.id, GameSession.status == "active")
                .values(status="finished", state=state)
            )
            if res.rowcount == 0:
                return {"text": "Game already finished"}

            score = await _get_or_create_score(db, profile.id)
            score.completed += 1
            score.best_level = max(score.best_level, total)
            score.points += completion_points

            await db.commit()
            return _finish_card(state, session.id, won=True, delta=completion_points)

        # Верно, но ещё есть вопросы: переходим к следующему.
        state["level"] = level + 1
        state["hint_shown"] = False
        state["eliminated"] = []
        session.state = state
        await db.commit()
        return build_millionaire_card(state, session.id)

    # Неверно: конец игры, баллы НЕ начисляем.
    state["won"] = False
    # CAS: только один финальный клик начисляет счёт и закрывает сессию.
    res = await db.execute(
        update(GameSession)
        .where(GameSession.id == session.id, GameSession.status == "active")
        .values(status="finished", state=state)
    )
    if res.rowcount == 0:
        return {"text": "Game already finished"}

    score = await _get_or_create_score(db, profile.id)
    score.best_level = max(score.best_level, level - 1)

    await db.commit()
    return _finish_card(state, session.id, won=False, delta=0)


async def use_5050(db: AsyncSession, game_id: int, profile: Profile) -> dict:
    """Подсказка 50:50 — убрать два неверных варианта из текущего вопроса."""
    session = await _active_millionaire_session(db, game_id)
    if session is None:
        return {"text": "Game not found 🤷"}
    state = session.state or {}

    if state.get("fifty_used"):
        return build_millionaire_card(state, session.id)

    questions = state.get("questions", [])
    level = state.get("level", 1)
    if not questions or not (1 <= level <= len(questions)):
        return {"text": "Game not found 🤷"}

    question = questions[level - 1]
    correct = question["answer"]
    wrong = [i for i in range(len(question["options"])) if i != correct]

    # Оставляем правильный + один случайный неверный, остальное прячем.
    keep_wrong = random.choice(wrong)
    eliminated = [i for i in wrong if i != keep_wrong]

    state["fifty_used"] = True
    state["eliminated"] = eliminated
    session.state = state
    await db.commit()
    return build_millionaire_card(state, session.id)


async def use_hint(db: AsyncSession, game_id: int, profile: Profile) -> dict:
    """Подсказка — показать объяснение к текущему вопросу."""
    session = await _active_millionaire_session(db, game_id)
    if session is None:
        return {"text": "Game not found 🤷"}
    state = session.state or {}

    if state.get("hint_used"):
        return build_millionaire_card(state, session.id)

    state["hint_used"] = True
    state["hint_shown"] = True
    session.state = state
    await db.commit()
    return build_millionaire_card(state, session.id)


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

    return await start_millionaire(db, space_name, profile)


async def quit_game(db: AsyncSession, game_id: int, profile: Profile) -> dict:
    """Просто закрыть активную партию без начисления баллов."""
    session = await db.get(GameSession, game_id)
    if session is None:
        return {"text": "Game not found 🤷"}
    session.status = "cancelled"
    await db.commit()
    return {"text": "Game closed. Press «💎 Millionaire» in the games menu to play again."}


# ---------------------------------------------------------------------------
# Лидерборд
# ---------------------------------------------------------------------------

async def leaderboard_response(db: AsyncSession) -> dict:
    """Топ-20 «Миллионера» с пьедесталом топ-3."""
    rows = (
        await db.execute(
            select(MillionaireScore, Profile.user_name, Profile.workspace_user_id)
            .join(Profile, MillionaireScore.profile_id == Profile.id)
            .order_by(MillionaireScore.points.desc(), MillionaireScore.completed.desc())
            .limit(20)
        )
    ).all()

    if not rows:
        return {"text": "Nobody has played Millionaire yet 🤷"}

    entries = [
        (name or ws or f"Player {score.profile_id}", score.completed, score.best_level, score.points)
        for score, name, ws in rows
    ]

    medals = ("🥇", "🥈", "🥉")
    lines = []
    for i, (name, completed, best_level, pts) in enumerate(entries[:3]):
        indent = ("        ", "  ", "              ")[i]
        lines.append(f"{indent}{medals[i]} {name} — {pts}")
    body = "\n".join(lines)

    rest = [
        f"{i}. {name} — {pts} ({completed} completed, best {best_level}/{TOTAL_QUESTIONS})"
        for i, (name, completed, best_level, pts) in enumerate(entries[3:], start=4)
    ]
    if rest:
        body += "\n\n" + "\n".join(rest)

    return {"cardsV2": [{
        "cardId": "millionaireLeaderboard",
        "card": {
            "header": {
                "title": "🏆 Millionaire rating",
                "subtitle": f"+{COMPLETION_POINTS_DEFAULT} for a full run",
            },
            "sections": [
                {"widgets": [{"textParagraph": {"text": body}}]},
            ],
        },
    }]}
