"""Игра «Переведи-ка» (Translate it) — соло в личке.

Бот показывает фразу (случайно рус или англ) и просит перевести на другой язык.
Направление случайное: рус → англ (production) или англ → рус (comprehension).
Судья — LLM (принимает синонимы и даёт подсказку), фолбэк — точное совпадение по
банку. Очки НЕ ведутся в общий рейтинг: внутри партии считается лёгкая серия
(streak/best/total). Состояние живёт в game_sessions.state, `game_type = 'translation'`.

Вход:
- start_translation — создать партию (кнопка «Translate it» из меню ДМ-игр).
- check            — проверить перевод (поле «Your answer»).
- next_round       — следующая пара (серия сохраняется).
- finish           — завершить и показать итог сессии.
"""
import logging
import random

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import GameSession, Profile
from app.services import games
from app.services.games_llm import judge_translation
from app.services.translation_bank import random_translation_pair

logger = logging.getLogger(__name__)


def _action_url() -> str:
    """URL эндпоинта — в add-on режиме кнопка доставляет клик только при function=URL."""
    return get_settings().chat_app_audience or "translation"


def _btn(text: str, method: str, game_id: int | None = None) -> dict:
    parameters = [{"key": "method", "value": method}]
    if game_id is not None:
        parameters.append({"key": "game_id", "value": str(game_id)})
    return {
        "text": text,
        "onClick": {"action": {"function": _action_url(), "parameters": parameters}},
    }


def _normalize(text: str) -> str:
    """Свернуть регистр и пробелы для сравнения (фолбэк без LLM)."""
    return " ".join((text or "").lower().split())


def _new_round_state(ru: str, en: str, direction: str, streak: int, best: int, correct: int, total: int) -> dict:
    if direction == "ru_en":
        source, target, sl, tl = ru, en, "ru", "en"
    else:
        source, target, sl, tl = en, ru, "en", "ru"
    return {
        "game": "translation",
        "direction": direction,
        "source": source,
        "target": target,
        "source_lang": sl,
        "target_lang": tl,
        "streak": streak,
        "best": best,
        "correct": correct,
        "total": total,
    }


def build_translation_card(state: dict, game_id: int) -> dict:
    """Карточка игры (cardId «translateIt») — фраза + поле перевода + серия."""
    source = state.get("source", "")
    direction = state.get("direction", "ru_en")
    streak = state.get("streak", 0)

    if direction == "ru_en":
        instruction = "Translate into English:"
        label = "In English"
        sub = f"Russian → English · 🔥 streak {streak}"
    else:
        instruction = "Переведи на русский:"
        label = "На русском"
        sub = f"English → Russian · 🔥 streak {streak}"

    body = f"{instruction}\n\n**{source}**"

    return {"cardsV2": [{
        "cardId": "translateIt",
        "card": {
            "header": {"title": "Translate it 🔤", "subtitle": sub},
            "sections": [{"widgets": [
                {"textParagraph": {"text": body}},
                {
                    "textInput": {
                        "name": "answer",
                        "label": label,
                        "type": "SINGLE_LINE",
                        "hintText": "Type your translation",
                    }
                },
                {"buttonList": {"buttons": [
                    _btn("✅ Check", "translation_check", game_id),
                    _btn("🛑 Finish", "translation_finish", game_id),
                ]}},
            ]}],
        },
    }]}


def _result_card(state: dict, game_id: int, correct: bool, guess: str, note: str) -> dict:
    """Карточка после проверки: результат + подсказка + серия."""
    source = state.get("source", "")
    target = state.get("target", "")
    streak = state.get("streak", 0)

    if correct:
        title = "🎉 Correct!"
        body = f"**{source}**  →  **{target}**\n\n🔥 Streak: {streak}"
    else:
        title = "🤔 Not quite"
        parts = [f"You wrote: _{guess}_", f"Better: **{target}**"]
        if note:
            parts.append(f"💡 {note}")
        body = "\n\n".join(parts)

    return {"cardsV2": [{
        "cardId": "translateIt",
        "card": {
            "header": {"title": title, "subtitle": "Translate it"},
            "sections": [{"widgets": [
                {"textParagraph": {"text": body}},
                {"buttonList": {"buttons": [
                    _btn("🆕 Next", "translation_next", game_id),
                    _btn("🛑 Finish", "translation_finish", game_id),
                ]}},
            ]}],
        },
    }]}


def _summary_card(state: dict) -> dict:
    """Итог сессии: счёт и лучшая серия."""
    total = state.get("total", 0)
    correct = state.get("correct", 0)
    best = state.get("best", 0)
    body = f"Session over!\n\nAnswered: {total}\nCorrect: {correct}\nBest streak: {best} 🔥"

    return {"cardsV2": [{
        "cardId": "translateIt",
        "card": {
            "header": {"title": "Translate it 🔤", "subtitle": "Session summary"},
            "sections": [{"widgets": [
                {"textParagraph": {"text": body}},
                {"buttonList": {"buttons": [
                    _btn("🔤 Play again", "menu_translation"),
                ]}},
            ]}],
        },
    }]}


async def start_translation(db: AsyncSession, space_name: str, profile: Profile) -> dict:
    """Создать партию: первая пара и карточка."""
    if await games.get_active_game(db, space_name) is not None:
        return {"text": "A game is already running — finish it or press «🛑 Finish»."}

    ru, en = random_translation_pair()
    state = _new_round_state(ru, en, random.choice(["ru_en", "en_ru"]), 0, 0, 0, 0)
    session = await games._start_session(db, space_name, "translation", "Translate it", state)
    return build_translation_card(state, session.id)


async def _active_session(db: AsyncSession, game_id: int) -> GameSession | None:
    """Активная translation-сессия по id, иначе None."""
    session = await db.get(GameSession, game_id)
    if session is None or session.game_type != "translation" or session.status != "active":
        return None
    return session


async def check(db: AsyncSession, game_id: int, profile: Profile, text: str) -> dict:
    """Проверить перевод: LLM-судья (фолбэк — точное совпадение), обновить серию."""
    session = await _active_session(db, game_id)
    if session is None:
        return {"text": "Game not found 🤷"}
    state = session.state or {}

    guess = (text or "").strip()
    if not guess:
        return {
            "text": "Type your translation 🙂",
            "cardsV2": build_translation_card(state, game_id),
        }

    verdict = await judge_translation(
        source=state.get("source", ""),
        source_lang=state.get("source_lang", "ru"),
        target_lang=state.get("target_lang", "en"),
        reference=state.get("target", ""),
        guess=guess,
    )
    if verdict is None:
        correct = _normalize(guess) == _normalize(state.get("target", ""))
        note = ""
    else:
        correct = bool(verdict.get("correct"))
        note = str(verdict.get("note") or "").strip()

    total = state.get("total", 0) + 1
    if correct:
        streak = state.get("streak", 0) + 1
        correct_count = state.get("correct", 0) + 1
    else:
        streak = 0
        correct_count = state.get("correct", 0)
    state["streak"] = streak
    state["best"] = max(state.get("best", 0), streak)
    state["correct"] = correct_count
    state["total"] = total
    session.state = state
    await db.commit()
    return _result_card(state, session.id, correct, guess, note)


async def next_round(db: AsyncSession, game_id: int, profile: Profile) -> dict:
    """Следующая пара (серия сохраняется)."""
    session = await _active_session(db, game_id)
    if session is None:
        return {"text": "Game not found 🤷"}
    state = session.state or {}

    ru, en = random_translation_pair()
    new_state = _new_round_state(
        ru, en, random.choice(["ru_en", "en_ru"]),
        streak=state.get("streak", 0), best=state.get("best", 0),
        correct=state.get("correct", 0), total=state.get("total", 0),
    )
    session.state = new_state
    await db.commit()
    return build_translation_card(new_state, session.id)


async def finish(db: AsyncSession, game_id: int, profile: Profile) -> dict:
    """Завершить партию и показать итог."""
    session = await db.get(GameSession, game_id)
    if session is None:
        return {"text": "Game not found 🤷"}
    state = session.state or {}
    session.status = "finished"
    await db.commit()
    return _summary_card(state)
