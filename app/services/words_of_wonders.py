"""Игра «Words of Wonders» (типа Wordscapes) — соло в личке, БЕЗ общего рейтинга.

Бот даёт набор букв (перемешанное seed-слово) — как «колесо» в Words of Wonders.
Игрок набирает английские слова длины >= 3, которые можно сложить из этих букв.
Основные слова — курированный банк `words_of_wonders_bank` (рисуются квадратиками
⬜). Любое другое валидное слово проверяется LLM и идёт в бонус-счётчик ✨ (сбрасывается
при смене букв/карточки). Найдены все основные → победа; «Give up» показывает всё.

Состояние живёт в game_sessions.state, `game_type = 'words_of_wonders'`.

Вход:
- start  — создать партию (кнопка «Words of Wonders» из меню ДМ-игр).
- check  — проверить слово (поле «answer»).
- reveal — сдаться и показать все слова.
- new_game — взять новую головоломку.
"""
import logging
import random
from collections import Counter

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import GameSession, Profile
from app.services import party_games
from app.services.games_llm import is_real_word
from app.services.words_of_wonders_bank import random_puzzle

logger = logging.getLogger(__name__)

MIN_LEN = 3

# Неразрывные пробелы (U+00A0): рендер Google Chat их не схлопывает, в отличие от
# обычных пробелов, поэтому между квадратиками разных слов виден чёткий зазор.
_GAP = " " * 5


def _keycap(n: int) -> str:
    """Эмодзи-цифра (3️⃣…): по вертикали совпадает с квадратиками ⬜ (оба — эмодзи)."""
    return str(n) + "️⃣"


def _action_url() -> str:
    """URL эндпоинта — в add-on режиме кнопка доставляет клик только при function=URL."""
    return get_settings().chat_app_audience or "words_of_wonders"


def _btn(text: str, method: str, game_id: int | None = None) -> dict:
    parameters = [{"key": "method", "value": method}]
    if game_id is not None:
        parameters.append({"key": "game_id", "value": str(game_id)})
    return {
        "text": text,
        "onClick": {"action": {"function": _action_url(), "parameters": parameters}},
    }


def _can_make(word: str, letters: str) -> bool:
    """Можно ли собрать `word` из мультимножества букв `letters` (Counter-сравнение)."""
    return not (Counter(word) - Counter(letters))


def _new_state(puzzle: dict) -> dict:
    letters = "".join(sorted(puzzle["letters"]))
    display = list(puzzle["letters"].upper())
    random.shuffle(display)
    return {
        "game": "words_of_wonders",
        "seed": puzzle["letters"],
        "letters": letters,
        "display": display,
        "answers": list(puzzle["words"]),
        "found": [],
        "bonus_words": [],
        "min_len": MIN_LEN,
    }


def _remaining_by_len(state: dict) -> dict[int, list[str]]:
    """Оставшиеся (не найденные) основные слова, сгруппированные по длине."""
    found = set(state.get("found", []))
    remaining: dict[int, list[str]] = {}
    for w in state.get("answers", []):
        if w not in found:
            remaining.setdefault(len(w), []).append(w)
    return remaining


def _squares_hint(remaining: dict[int, list[str]]) -> str:
    """Квадратики: по одному ⬜ на букву, слова одной длины, не больше 3 в ряд.

    Ряд из трёх слов не переносится, поэтому слово не рвётся пополам при переносе.
    Длина подписывается эмодзи-цифрой (3️⃣), чтобы по вертикали совпадать с ⬜.
    """
    if not remaining:
        return "🏆 All words found!"
    lines = []
    for length in sorted(remaining):
        words = remaining[length]
        label = _keycap(length)
        for i in range(0, len(words), 3):
            chunk = words[i : i + 3]
            boxes = _GAP.join("⬜" * length for _ in chunk)
            prefix = f"{label}  " if i == 0 else "    "
            lines.append(prefix + boxes)
    return "\n".join(lines)


def build_card(state: dict, game_id: int) -> dict:
    """Карточка игры (cardId «wordsOfWonders») — буквы + квадратики + прогресс."""
    display = " ".join(state.get("display", []))
    total = len(state.get("answers", []))
    found = state.get("found", [])
    bonus = state.get("bonus_words", [])
    remaining = _remaining_by_len(state)
    n_left = sum(len(v) for v in remaining.values())

    progress = f"✅ Found {len(found)} / {total}   ·   ✨ Bonus words {len(bonus)}"

    parts = [
        f"**{display}**",
        "",
        _squares_hint(remaining),
        "",
        progress,
    ]

    if found:
        parts += ["", "✅ " + " · ".join(w.upper() for w in sorted(found, key=lambda w: (len(w), w)))]
    if bonus:
        parts += ["✨ " + " · ".join(w.upper() for w in sorted(bonus, key=lambda w: (len(w), w)))]

    body = "\n".join(parts)

    if len(found) >= total:
        subtitle = "All words found! 🏆"
        buttons = [_btn("🆕 New puzzle", "wow_new", game_id)]
    else:
        subtitle = f"{len(display.split())} letters · {n_left} words left"
        buttons = [
            _btn("✅ Check", "wow_check", game_id),
            _btn("💡 Give up", "wow_reveal", game_id),
        ]

    return {"cardsV2": [{
        "cardId": "wordsOfWonders",
        "card": {
            "header": {"title": "Words of Wonders 🔠", "subtitle": subtitle},
            "sections": [{"widgets": [
                {"textParagraph": {"text": body}},
                {
                    "textInput": {
                        "name": "answer",
                        "label": "Your word",
                        "type": "SINGLE_LINE",
                        "hintText": f"3+ letters from: {display}",
                    }
                },
                {"buttonList": {"buttons": buttons}},
            ]}],
        },
    }]}


def _reveal_card(state: dict, game_id: int) -> dict:
    """Итоговая карточка после сдачи/победы: все слова + бонусы."""
    answers = sorted(state.get("answers", []), key=lambda w: (len(w), w))
    bonus = sorted(state.get("bonus_words", []), key=lambda w: (len(w), w))
    total = len(answers)

    lines = []
    for length in sorted({len(w) for w in answers}):
        group = [w for w in answers if len(w) == length]
        lines.append(f"**{length} letters** ({len(group)}): " + ", ".join(group))
    body = "\n".join(lines)

    if len(state.get("found", [])) >= total:
        title = "🏆 Solved!"
        subtitle = f"All {total} words found"
    else:
        title = "🔍 Here they are"
        subtitle = f"You found {len(state.get('found', []))} of {total}"

    if bonus:
        body += f"\n\n✨ Bonus words: " + ", ".join(bonus)

    return {"cardsV2": [{
        "cardId": "wordsOfWonders",
        "card": {
            "header": {"title": title, "subtitle": subtitle},
            "sections": [{"widgets": [
                {"textParagraph": {"text": body}},
                {"buttonList": {"buttons": [
                    _btn("🆕 New puzzle", "wow_new", game_id),
                ]}},
            ]}],
        },
    }]}


async def start(db: AsyncSession, space_name: str, profile: Profile) -> dict:
    """Создать партию: головоломка из банка + карточка."""
    if await party_games.get_active_game(db, space_name) is not None:
        return {"text": "A game is already running — finish it or press «💡 Give up»."}

    state = _new_state(random_puzzle())
    session = await party_games._start_session(db, space_name, "words_of_wonders", "Words of Wonders", state)
    return build_card(state, session.id)


async def _active_session(db: AsyncSession, game_id: int) -> GameSession | None:
    """Активная words_of_wonders-сессия по id, иначе None."""
    session = await db.get(GameSession, game_id)
    if session is None or session.game_type != "words_of_wonders" or session.status != "active":
        return None
    return session


async def check(db: AsyncSession, game_id: int, profile: Profile, text: str) -> dict:
    """Проверить слово: основное (банк) или бонус (LLM), обновить счётчики."""
    session = await _active_session(db, game_id)
    if session is None:
        return {"text": "Game not found 🤷"}
    state = session.state or {}

    word = (text or "").strip().lower()
    if not word:
        return {"text": "Type a word 🙂", "cardsV2": build_card(state, game_id)}
    if not word.isalpha():
        return {"text": "Letters only (a–z) 🙃", "cardsV2": build_card(state, game_id)}
    if len(word) < MIN_LEN:
        return {"text": f"Words must be {MIN_LEN}+ letters", "cardsV2": build_card(state, game_id)}
    if not _can_make(word, state.get("letters", "")):
        return {"text": f"«{word}» can't be made from these letters 🙅", "cardsV2": build_card(state, game_id)}

    found = list(state.get("found", []))
    bonus = list(state.get("bonus_words", []))
    answers = state.get("answers", [])

    if word in found:
        return {"text": f"«{word}» already found 😉", "cardsV2": build_card(state, game_id)}
    if word in bonus:
        return {"text": f"«{word}» already found ✨", "cardsV2": build_card(state, game_id)}

    if word in answers:
        found.append(word)
        state["found"] = found
        msg = f"✅ {word.upper()}!"
    else:
        ok = await is_real_word(word)
        if ok is True:
            bonus.append(word)
            state["bonus_words"] = bonus
            msg = f"✨ {word.upper()} — bonus word!"
        elif ok is False:
            return {"text": f"«{word}» isn't a real word 🙃", "cardsV2": build_card(state, game_id)}
        else:
            return {"text": "Couldn't verify that word — try again 🤔", "cardsV2": build_card(state, game_id)}

    solved = len(found) >= len(answers)
    session.state = state
    if solved:
        session.status = "finished"
    await db.commit()

    if solved:
        return _reveal_card(state, session.id)
    return {"text": msg, "cardsV2": build_card(state, session.id)}


async def reveal(db: AsyncSession, game_id: int, profile: Profile) -> dict:
    """Сдаться: показать все оставшиеся слова и завершить партию."""
    session = await db.get(GameSession, game_id)
    if session is None:
        return {"text": "Game not found 🤷"}
    state = session.state or {}
    session.status = "finished"
    await db.commit()
    return _reveal_card(state, session.id)


async def new_game(db: AsyncSession, game_id: int, profile: Profile) -> dict:
    """Закрыть активную партию в space и взять новую головоломку."""
    session = await db.get(GameSession, game_id)
    space_name = session.space_name if session else ""
    if not space_name:
        return {"text": "Game not found 🤷"}

    active = await party_games.get_active_game(db, space_name)
    if active is not None:
        active.status = "cancelled"
        await db.commit()

    return await start(db, space_name, profile)
