"""Раздел «English by level» (обучение английскому по уровням A/B/C) в личке.

Параллельный хаб рядом с курсом «Survival English for Calls» (callready). Три уровня
CEFR (A/B/C), под каждым — темы (смесь общего + рабочего английского). Тема = учебная
карточка (заметка + лексика) + тест (5 вопросов: 3 словарных + 2 грамматических).

Контент берётся из leveled_bank (статический). Прогресс живёт в leveled_progress.state
(JSONB, одна строка на профиль). Навигация по кнопкам без состояния в сессии: каждый
клик несёт нужные параметры (level/theme/q/answer/score).

Баллы (leaderboard_ledger, event_type 'learning'):
  - +1 за изученную тему (первый раз);
  - +1 за пройденный тест темы (первый раз, порог ≥ 4/5).
Начисление идемпотентно по состоянию (themes_studied / tests_passed), а не по журналу.

Переиспользуем чистые хелперы callready (без правки callready): _btn, _card, _md,
_OPTION_LETTERS, _pick_even. Карточки теста — свои (cardId «leveled», чтобы карточка
обновлялась на месте с тем же id, что и у нажатой кнопки).
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LeveledProgress, Profile
from app.services import leveled_bank as bank
from app.services import leaderboard
from app.services.callready import _btn, _card, _md, _OPTION_LETTERS, _pick_even

logger = logging.getLogger(__name__)

THEME_STUDY_POINTS = 1   # изучена тема
THEME_TEST_POINTS = 1     # пройден тест темы

# Порог прохождения теста темы.
THEME_TEST_PASS = 4       # из 5 (3 словарных + 2 грамматических)

# Единый cardId для всех карточек раздела.
CARD = "leveled"


def _fresh_state() -> dict:
    return {
        "themes_studied": [],   # изученные темы
        "tests_passed": [],     # пройденные тесты тем
    }


def _state_of(row: LeveledProgress) -> dict:
    return row.state if isinstance(row.state, dict) else _fresh_state()


def section_points(state: dict) -> int:
    """Баллы из состояния: +1 тема, +1 тест темы."""
    return (
        len(state.get("themes_studied", [])) * THEME_STUDY_POINTS
        + len(state.get("tests_passed", [])) * THEME_TEST_POINTS
    )


def progress_summary(state: dict) -> str:
    """Текстовый отчёт о прогрессе раздела."""
    studied = set(state.get("themes_studied", []))
    passed = set(state.get("tests_passed", []))
    lines = []
    for lvl in bank.LEVELS:
        themes = bank.themes_for_level(lvl["id"])
        s = sum(1 for th in themes if th["id"] in studied)
        p = sum(1 for th in themes if th["id"] in passed)
        lines.append(
            f"{lvl['icon']} Level {lvl['label']}: studied {s}/{len(themes)} · tests {p}/{len(themes)}"
        )
    total = len(bank.THEMES)
    return (
        f"Themes studied: **{len(studied)}/{total}** · tests passed **{len(passed)}/{total}**\n\n"
        + "\n".join(lines)
        + f"\n\nPoints earned: **{section_points(state)}**"
    )


# ---------------------------------------------------------------------------
# Построители вопросов теста (детерминированные — без БД и без random)
# ---------------------------------------------------------------------------

def _unique_ru(level_id: str) -> list[str]:
    """Уникальные русские значения терминов уровня (пул дистракторов)."""
    seen: set[str] = set()
    out: list[str] = []
    for th in bank.themes_for_level(level_id):
        for t in th["terms"]:
            if t[1] not in seen:
                seen.add(t[1])
                out.append(t[1])
    return out


def _vocab_question(term: list, gi: int, ru_pool: list[str]) -> dict:
    """Словарный вопрос «What does X mean?»: 4 варианта, детерминированно."""
    correct = term[1]
    n = len(ru_pool)
    distractors: list[str] = []
    for k in range(1, 4):
        ru = ru_pool[(gi * 3 + k * 7) % n]
        if ru != correct and ru not in distractors:
            distractors.append(ru)
    for ru in ru_pool:
        if len(distractors) >= 3:
            break
        if ru != correct and ru not in distractors:
            distractors.append(ru)
    options = [correct] + distractors
    correct_idx = gi % 4
    if correct_idx != 0:
        options[0], options[correct_idx] = options[correct_idx], options[0]
    return {
        "prompt": f"What does “{term[0]}” mean?",
        "options": options,
        "correct": correct_idx,
        "explain": term[2],
    }


def _grammar_question(task: list) -> dict:
    """Грамматическое/употребительское задание банка → словарь вопроса теста."""
    return {"prompt": task[0], "options": task[1], "correct": task[2], "explain": task[3]}


def theme_test_questions(theme_id: str) -> list[dict]:
    """Тест темы: 3 словарных вопроса (по terms) + 2 грамматических (из quiz)."""
    th = bank.theme_by_id(theme_id)
    if th is None:
        return []
    ru_pool = _unique_ru(th["level"])
    terms = th["terms"]
    n = len(terms)
    idxs = [int(i * (n - 1) / 2) for i in range(3)]  # 0, середина, последний
    vocab = [_vocab_question(terms[i], i, ru_pool) for i in idxs]
    grammar = _pick_even(th["quiz"], 2)
    return vocab + [_grammar_question(task) for task in grammar]


# ---------------------------------------------------------------------------
# Карточки
# ---------------------------------------------------------------------------

def build_level_menu_card() -> dict:
    """Карточка выбора уровня (cardId leveled)."""
    buttons = [
        _btn(f"{lvl['icon']} Level {lvl['label']} — {lvl['name']} ({lvl['sub']})", "leveled_themes", level=lvl["id"])
        for lvl in bank.LEVELS
    ]
    widgets = [
        {"textParagraph": {"text": (
            "Learn English step by step — general and work topics.\n\n"
            "🟢 **A** — Beginner (A1–A2)\n"
            "🔵 **B** — Intermediate (B1–B2)\n"
            "🟣 **C** — Advanced (C1–C2)"
        )}},
        {"buttonList": {"buttons": buttons}},
        {"buttonList": {"buttons": [_btn("📈 My progress", "leveled_progress")]}},
    ]
    return _card(CARD, "English by level 🌍", "Pick your level", widgets)


def build_themes_card(level_id: str, state: dict) -> dict:
    """Карточка списка тем уровня (cardId leveled)."""
    lvl = bank.level_by_id(level_id)
    if lvl is None:
        return build_level_menu_card()
    studied = set(state.get("themes_studied", []))
    passed = set(state.get("tests_passed", []))
    buttons = []
    for th in bank.themes_for_level(level_id):
        mark = "✅" if th["id"] in passed else ("📖" if th["id"] in studied else "▫️")
        buttons.append(_btn(f"{mark} {th['icon']} {th['title']}", "leveled_theme", theme=th["id"]))
    widgets = [
        {"textParagraph": {"text": (
            f"**Level {lvl['label']} — {lvl['name']} ({lvl['sub']})**\n\n"
            "Pick a topic. ✅ = test passed · 📖 = studied."
        )}},
        {"buttonList": {"buttons": buttons}},
        {"buttonList": {"buttons": [_btn("↩ Levels", "leveled_menu")]}},
    ]
    return _card(CARD, f"{lvl['icon']} Level {lvl['label']} — topics", f"{len(bank.themes_for_level(level_id))} topics", widgets)


def build_theme_card(theme: dict, state: dict) -> dict:
    """Учебная карточка темы: заметка + лексика (cardId leveled)."""
    studied = theme["id"] in set(state.get("themes_studied", []))
    passed = theme["id"] in set(state.get("tests_passed", []))
    status = "✅ test passed" if passed else ("📖 studied" if studied else "new")
    terms_text = "\n\n".join(f"**{en}** — {ru}\n_{ex}_" for en, ru, ex in theme["terms"])
    widgets = [
        {"textParagraph": {"text": _md(theme["notes"])}},
        {"textParagraph": {"text": "**Useful phrases**\n\n" + terms_text}},
        {"buttonList": {"buttons": [
            _btn("📝 Take the test", "leveled_test", theme=theme["id"], q=0, score=0),
            _btn("↩ Topics", "leveled_themes", level=theme["level"]),
        ]}},
        {"buttonList": {"buttons": [
            _btn("🏠 Levels", "leveled_menu"),
            _btn("📈 Progress", "leveled_progress"),
        ]}},
    ]
    return _card(CARD, f"{theme['icon']} {theme['title']}", f"{theme['sub']} · {status}", widgets)


def build_progress_card(state: dict) -> dict:
    """Карточка прогресса раздела (cardId leveled)."""
    widgets = [
        {"textParagraph": {"text": progress_summary(state)}},
        {"buttonList": {"buttons": [_btn("🏠 Levels", "leveled_menu")]}},
    ]
    return _card(CARD, "Your progress 📈", "English by level", widgets)


def _test_question_card(
    title: str, q_idx: int, total: int, question: dict, score: int,
    answer_method: str, scope: dict,
) -> dict:
    """Карточка вопроса теста: вопрос + кнопки вариантов ответа."""
    buttons = [
        _btn(f"{_OPTION_LETTERS[i]}. {opt}", answer_method, **scope, q=q_idx, score=score, answer=i)
        for i, opt in enumerate(question["options"])
    ]
    widgets = [
        {"textParagraph": {"text": f"**Question {q_idx + 1}/{total}**\n\n{question['prompt']}"}},
        {"buttonList": {"buttons": buttons}},
        {"textParagraph": {"text": f"Score so far: **{score}/{q_idx}**"}},
    ]
    return _card(CARD, title, f"Question {q_idx + 1}/{total}", widgets)


def _test_feedback_card(
    title: str, q_idx: int, total: int, question: dict, correct: bool,
    new_score: int, next_method: str, scope: dict,
) -> dict:
    """Карточка результата ответа в тесте + кнопка «Next question →»."""
    if correct:
        head = "✅ Correct!"
    else:
        head = f"❌ Not quite — correct answer: **{question['options'][question['correct']]}**"
    body = f"{head}\n\n💡 {_md(question['explain'])}\n\nScore: **{new_score}/{q_idx + 1}**"
    widgets = [{"textParagraph": {"text": body}}]
    widgets.append({"buttonList": {"buttons": [
        _btn("Next question →", next_method, **scope, q=q_idx + 1, score=new_score),
    ]}})
    widgets.append({"buttonList": {"buttons": [_btn("🏠 Levels", "leveled_menu")]}})
    return _card(CARD, title, f"Question {q_idx + 1}/{total}", widgets)


def _test_result_card(
    title: str, passed: bool, score: int, total: int, threshold: int,
    awarded: int, back_method: str | None, back_label: str | None, scope: dict,
) -> dict:
    """Итоговая карточка теста: пройден/не пройден + куда дальше."""
    if passed:
        head = f"🏁 **Test passed!** +{awarded} pts"
    else:
        head = f"↻ **Not passed yet** — {score}/{total} correct"
    body = (
        f"{head}\n\n"
        f"Final score: **{score}/{total}**\n"
        f"To pass: **{threshold}/{total}** correct."
    )
    widgets = [{"textParagraph": {"text": body}}]
    buttons = []
    if back_method and back_label:
        buttons.append(_btn(back_label, back_method, **scope))
    buttons.append(_btn("🏠 Levels", "leveled_menu"))
    widgets.append({"buttonList": {"buttons": buttons}})
    return _card(CARD, title, "Test result", widgets)


# ---------------------------------------------------------------------------
# Работа с БД
# ---------------------------------------------------------------------------

async def _get_or_create_progress(db: AsyncSession, profile_id: int) -> LeveledProgress:
    row = (
        await db.execute(select(LeveledProgress).where(LeveledProgress.profile_id == profile_id))
    ).scalar_one_or_none()
    if row is None:
        row = LeveledProgress(profile_id=profile_id, state=_fresh_state())
        db.add(row)
        await db.flush()
    elif not isinstance(row.state, dict):
        row.state = _fresh_state()
    return row


async def _award(db: AsyncSession, profile_id: int, points: int, reason: str, metadata: dict) -> None:
    """Начислить баллы в leaderboard_ledger (event_type 'learning').

    Не глотаем исключения: начисление идёт в той же транзакции, что и состояние,
    поэтому сбой откатит и то и другое — юзер сможет повторить.
    """
    await leaderboard.award_points(
        db, profile_id, "learning", points, reason=reason, metadata=metadata,
    )


async def level_menu(db: AsyncSession, profile: Profile) -> dict:
    """Карточка выбора уровня (команда «level» / кнопка меню)."""
    await _get_or_create_progress(db, profile.id)
    await db.commit()
    return build_level_menu_card()


async def show_themes(db: AsyncSession, profile: Profile, level_id: str) -> dict:
    """Карточка списка тем уровня."""
    if bank.level_by_id(level_id) is None:
        return build_level_menu_card()
    row = await _get_or_create_progress(db, profile.id)
    state = _state_of(row)
    await db.commit()
    return build_themes_card(level_id, state)


async def show_theme(db: AsyncSession, profile: Profile, theme_id: str) -> dict:
    """Учебная карточка темы: +1 балл за изучение (первый раз)."""
    theme = bank.theme_by_id(theme_id)
    if theme is None:
        return build_level_menu_card()
    row = await _get_or_create_progress(db, profile.id)
    state = _state_of(row)
    studied = list(state.get("themes_studied", []))
    new_study = theme_id not in studied
    if new_study:
        studied.append(theme_id)
    state["themes_studied"] = studied
    row.state = state
    if new_study:
        await _award(db, profile.id, THEME_STUDY_POINTS, f"leveled studied theme {theme_id}", {"theme": theme_id})
    await db.commit()
    return build_theme_card(theme, state)


async def show_test(
    db: AsyncSession, profile: Profile, theme_id: str, q_idx: int, score: int,
) -> dict:
    """Показать вопрос теста темы."""
    theme = bank.theme_by_id(theme_id)
    questions = theme_test_questions(theme_id)
    if theme is None or not questions:
        return build_level_menu_card()
    if not (0 <= q_idx < len(questions)):
        q_idx = 0
    title = f"📝 {theme['icon']} {theme['title']} — test"
    return _test_question_card(
        title, q_idx, len(questions), questions[q_idx], score,
        "leveled_test_answer", {"theme": theme_id},
    )


async def answer_test(
    db: AsyncSession, profile: Profile, theme_id: str, q_idx: int, answer_idx: int, score: int,
) -> dict:
    """Оценить ответ в тесте темы; на последнем вопросе — итог и +1 балл."""
    theme = bank.theme_by_id(theme_id)
    questions = theme_test_questions(theme_id)
    if theme is None or not questions or not (0 <= q_idx < len(questions)):
        return build_level_menu_card()
    question = questions[q_idx]
    correct = answer_idx == question["correct"]
    new_score = score + (1 if correct else 0)
    title = f"📝 {theme['icon']} {theme['title']} — test"

    if q_idx + 1 < len(questions):
        return _test_feedback_card(
            title, q_idx, len(questions), question, correct, new_score,
            "leveled_test", {"theme": theme_id},
        )

    passed = new_score >= THEME_TEST_PASS
    row = await _get_or_create_progress(db, profile.id)
    state = _state_of(row)
    awarded = 0
    if passed:
        passed_list = list(state.get("tests_passed", []))
        if theme_id not in passed_list:
            passed_list.append(theme_id)
            state["tests_passed"] = passed_list
            awarded = THEME_TEST_POINTS
    row.state = state
    if awarded:
        await _award(db, profile.id, awarded, f"leveled theme test {theme_id}", {"theme": theme_id})
    await db.commit()
    return _test_result_card(
        title, passed, new_score, len(questions), THEME_TEST_PASS, awarded,
        "leveled_themes", f"↩ Level {theme['level'].upper()}", {"level": theme["level"]},
    )


async def show_progress(db: AsyncSession, profile: Profile) -> dict:
    """Карточка прогресса раздела."""
    row = await _get_or_create_progress(db, profile.id)
    state = _state_of(row)
    await db.commit()
    return build_progress_card(state)
