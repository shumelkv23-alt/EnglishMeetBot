"""Режим обучения «Survival English for Calls» в личке (порт приложения CallReady).

Самодостаточный движок ДМ-курса: карточки (меню / модуль / маршрут / грамматика /
фразбук / прогресс) + обработчики кнопок + начисление баллов в общий лидерборд.

Контент берётся из callready_bank (статический, 1:1 с CallReady). Прогресс живёт
в callready_progress.state (JSONB, одна строка на профиль), поэтому переживает
рестарты. Навигация по кнопкам без состояния в сессии: каждый клик несёт нужные
параметры (module/topic/pos/answer/cat).

Баллы (leaderboard_ledger, event_type 'learning'):
  - +10 за завершённый модуль (первый раз);
  - +1  за верный грамматический ответ (первый раз).
Начисление идемпотентно по состоянию (done / grammar), а не по журналу.
"""
from __future__ import annotations

import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import CallreadyProgress, Profile
from app.services import callready_bank as bank
from app.services import leaderboard

logger = logging.getLogger(__name__)

READ_MODULE_POINTS = 1    # прочитан модуль
READ_BLOCK_POINTS = 3     # прочитан блок (все 4 модуля)
MODULE_TEST_POINTS = 1    # пройден тест по модулю
BLOCK_TEST_POINTS = 2     # пройден тест по блоку

# Пороги прохождения тестов.
MODULE_TEST_PASS = 6      # из 7 (6 словарь + 1 грамматика)
BLOCK_TEST_PASS = 8       # из 10 (6 словарь + 4 грамматика)

# Единый cardId для всех карточек курса: навигация обновляет карточку НА МЕСТЕ
# (messages.patch / updateMessageAction), как у одиночных ДМ-игр.
CARD = "callready"

_OPTION_LETTERS = ("A", "B", "C", "D")


def _action_url() -> str:
    """URL эндпоинта — в add-on режиме кнопка доставляет клик только при function=URL."""
    return get_settings().chat_app_audience or "callready"


def _btn(text: str, method: str, **params) -> dict:
    """Кнопка курса: method + доп. параметры (module/topic/pos/answer/cat)."""
    parameters = [{"key": "method", "value": method}]
    for key, value in params.items():
        parameters.append({"key": key, "value": str(value)})
    return {
        "text": text,
        "onClick": {"action": {"function": _action_url(), "parameters": parameters}},
    }


def _md(html: str) -> str:
    """Лёгкий HTML (b/i/s/h3/p/br) из банка → markdown карточки Google Chat."""
    s = re.sub(r"<h3>(.*?)</h3>", r"**\1**\n\n", html, flags=re.S)
    s = re.sub(r"<b>(.*?)</b>", r"**\1**", s, flags=re.S)
    s = re.sub(r"<i>(.*?)</i>", r"*\1*", s, flags=re.S)
    s = re.sub(r"<s>(.*?)</s>", r"~\1~", s, flags=re.S)
    s = re.sub(r"<p>", "", s)
    s = re.sub(r"</p>", "\n\n", s)
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _card(card_id: str, title: str, subtitle: str, widgets: list[dict]) -> dict:
    """Обычная карточка с одним разделом."""
    return {"cardsV2": [{
        "cardId": card_id,
        "card": {
            "header": {"title": title, "subtitle": subtitle},
            "sections": [{"widgets": widgets}],
        },
    }]}


def _fresh_state() -> dict:
    return {
        "current_module": bank.MODULES[0]["id"],
        "done": [],           # прочитанные модули
        "blocks_read": [],    # полностью прочитанные блоки (все 4 модуля)
        "modules_tested": [], # пройденные тесты модулей
        "blocks_tested": [],  # пройденные тесты блоков
        "grammar": {},        # верные ответы в секции grammar practice (без баллов)
        "phrasebook_seen": [],
    }


def _state_of(row: CallreadyProgress) -> dict:
    return row.state if isinstance(row.state, dict) else _fresh_state()


def _terms_text(module: dict) -> str:
    """Полезные фразы модуля: english — перевод + пример."""
    lines = []
    for en, ru, ex in module["terms"]:
        lines.append(f"**{en}** — {ru}\n_{ex}_")
    return "\n\n".join(lines)


def _module_header(module: dict, state: dict) -> tuple[str, str]:
    """(title, subtitle) карточки модуля с позицией в маршруте."""
    pos = bank.module_index(module["id"]) + 1
    total = len(bank.MODULES)
    block = bank.block_for_module(module["id"])
    block_label = block["title"].split("·")[-1].strip() if block else ""
    return (
        f"{module['icon']} {module['title']}",
        f"Module {pos}/{total} · {block_label}",
    )


# ---------------------------------------------------------------------------
# Чистые хелперы (без БД) — для тестов
# ---------------------------------------------------------------------------

def module_points(state: dict) -> int:
    """Баллы из состояния: +1 модуль, +3 блок, +1 тест модуля, +2 тест блока."""
    done = len(state.get("done", []))
    blocks_read = len(state.get("blocks_read", []))
    modules_tested = len(state.get("modules_tested", []))
    blocks_tested = len(state.get("blocks_tested", []))
    return (
        done * READ_MODULE_POINTS
        + blocks_read * READ_BLOCK_POINTS
        + modules_tested * MODULE_TEST_POINTS
        + blocks_tested * BLOCK_TEST_POINTS
    )


def progress_summary(state: dict) -> str:
    """Текстовый отчёт о прогрессе для карточки «📈 My progress»."""
    done = set(state.get("done", []))
    modules_tested = set(state.get("modules_tested", []))
    blocks_read = set(state.get("blocks_read", []))
    blocks_tested = set(state.get("blocks_tested", []))
    grammar = state.get("grammar", {})
    phrasebook = state.get("phrasebook_seen", [])

    block_lines = []
    for b in bank.BLOCKS:
        read = sum(1 for m in b["modules"] if m in done)
        tested = sum(1 for m in b["modules"] if m in modules_tested)
        mark = "✅" if b["id"] in blocks_tested else "▫️"
        block_lines.append(f"{b['title']}: read {read}/4 · tests {tested}/4 {mark}")

    correct = sum(1 for v in grammar.values() if v)

    return (
        f"Modules read: **{len(done)}/{len(bank.MODULES)}** · tests **{len(modules_tested)}/{len(bank.MODULES)}**\n"
        f"Blocks read: **{len(blocks_read)}/{len(bank.BLOCKS)}** · tests **{len(blocks_tested)}/{len(bank.BLOCKS)}**\n\n"
        + "\n".join(block_lines)
        + f"\n\nGrammar practice: **{correct}/{len(bank.GRAMMAR_TASKS)}** correct\n"
        + f"Phrasebook: **{len(phrasebook)}/{len(bank.BACKUP)}** sections seen\n\n"
        + f"Points earned: **{module_points(state)}**"
    )


# ---------------------------------------------------------------------------
# Тесты модуля и блока (чистые, детерминированные — без БД и без random)
# ---------------------------------------------------------------------------

def _unique_ru() -> list[str]:
    """Уникальные русские значения всех терминов (пул дистракторов)."""
    seen: set[str] = set()
    out: list[str] = []
    for m in bank.MODULES:
        for t in m["terms"]:
            if t[1] not in seen:
                seen.add(t[1])
                out.append(t[1])
    return out


def _pick_even(items: list, k: int) -> list:
    """Выбрать k элементов, равномерно распределённых по списку."""
    n = len(items)
    if n <= k:
        return list(items)
    idxs = [int(i * (n - 1) / (k - 1)) for i in range(k)]
    return [items[i] for i in idxs]


def _vocab_question(term: list, gi: int) -> dict:
    """Словарный вопрос «What does X mean?»: 4 варианта, детерминированно.

    Положение верного ответа и дистракторы зависят только от глобального индекса
    термина gi — стабильно между кликами (карточки обновляются на месте).
    """
    correct = term[1]
    all_ru = _unique_ru()
    n = len(all_ru)
    distractors: list[str] = []
    for k in range(1, 4):
        ru = all_ru[(gi * 3 + k * 7) % n]
        if ru != correct and ru not in distractors:
            distractors.append(ru)
    for ru in all_ru:  # добираем при коллизиях/дублях
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
    """Грамматическое задание банка → словарь вопроса теста."""
    return {"prompt": task[0], "options": task[1], "correct": task[2], "explain": task[3]}


def module_test_questions(module_id: str) -> list[dict]:
    """Тест модуля: 6 словарных вопросов (по terms) + 1 грамматический."""
    m = bank.module_by_id(module_id)
    if m is None or module_id not in bank.MODULE_QUIZ:
        return []
    qs: list[dict] = []
    gi = 0
    for mod in bank.MODULES:
        if mod["id"] == module_id:
            for t in mod["terms"]:
                qs.append(_vocab_question(t, gi))
                gi += 1
            break
        gi += len(mod["terms"])
    qs.append(_grammar_question(bank.MODULE_QUIZ[module_id]))
    return qs


def block_test_questions(block_id: str) -> list[dict]:
    """Тест блока (порт checkpoint): 6 словарных + 4 грамматических вопроса."""
    b = bank.block_by_id(block_id)
    if b is None:
        return []
    terms: list[tuple[list, int]] = []
    gi = 0
    for mod in bank.MODULES:
        if mod["id"] in b["modules"]:
            for t in mod["terms"]:
                terms.append((t, gi))
                gi += 1
        else:
            gi += len(mod["terms"])
    vocab = _pick_even(terms, 6)
    task_ids: list[int] = []
    for ti in b["grammar"]:
        for tid in bank.GRAMMAR_TOPICS[ti]["tasks"]:
            if tid not in task_ids:
                task_ids.append(tid)
    grammar = _pick_even(task_ids, 4)
    qs = [_vocab_question(t, gi) for t, gi in vocab]
    qs += [_grammar_question(bank.GRAMMAR_TASKS[tid]) for tid in grammar]
    return qs


# ---------------------------------------------------------------------------
# Карточки
# ---------------------------------------------------------------------------

def build_menu_card() -> dict:
    """Карточка-меню курса (cardId callreadyMenu)."""
    widgets = [
        {"textParagraph": {"text": (
            "Learn to speak confidently on work calls 📞\n"
            "12 modules across 3 blocks — chunks, grammar and practice."
        )}},
        {"buttonList": {"buttons": [
            _btn("📚 Start / continue", "callready_continue"),
            _btn("🗺 My route", "callready_route"),
            _btn("🧠 Grammar practice", "callready_practice"),
            _btn("📖 Backup phrasebook", "callready_phrasebook"),
            _btn("📈 My progress", "callready_progress"),
        ]}},
    ]
    return _card(CARD, "Survival English for Calls 🎓", "Learn in your DM", widgets)


def build_module_card(module: dict, state: dict) -> dict:
    """Карточка одного модуля (cardId callreadyModule)."""
    title, subtitle = _module_header(module, state)
    widgets = [
        {"textParagraph": {"text": (
            f"**{module['grammar']}**\n\n"
            f"{_md(module['rule'])}\n\n"
            f"{_md(module['ru_rule'])}"
        )}},
        {"textParagraph": {"text": "**Useful chunks**\n\n" + _terms_text(module)}},
        {"buttonList": {"buttons": [
            _btn("Next module →", "callready_next_module", module=module["id"]),
            _btn("📝 Module test", "callready_mtest", module=module["id"], q=0, score=0),
            _btn("↩ Back", "callready_prev_module", module=module["id"]),
        ]}},
        {"buttonList": {"buttons": [
            _btn("🧠 Grammar practice", "callready_practice"),
            _btn("📖 Phrasebook", "callready_phrasebook"),
            _btn("📈 Progress", "callready_progress"),
            _btn("🏠 Menu", "callready_menu"),
        ]}},
    ]
    return _card(CARD, title, subtitle, widgets)


def build_route_card(state: dict) -> dict:
    """Карточка маршрута (cardId callreadyRoute): 3 блока с прогрессом + блок-тесты."""
    done = set(state.get("done", []))
    modules_tested = set(state.get("modules_tested", []))
    blocks_tested = set(state.get("blocks_tested", []))
    widgets = []
    for b in bank.BLOCKS:
        lines = []
        for m_id in b["modules"]:
            m = bank.module_by_id(m_id)
            mark = "✅" if m_id in done else "▫️"
            tmark = " 🧪" if m_id in modules_tested else ""
            lines.append(f"{mark} {m['icon']} {m['title']}{tmark}" if m else f"{mark} {m_id}")
        widgets.append({"textParagraph": {"text": f"**{b['title']}**\n" + "\n".join(lines)}})
        bmark = "✅ " if b["id"] in blocks_tested else ""
        widgets.append({"buttonList": {"buttons": [
            _btn(f"{bmark}🏁 Block test", "callready_btest", block=b["id"], q=0, score=0),
        ]}})
    widgets.append({"buttonList": {"buttons": [
        _btn("📚 Continue", "callready_continue"),
        _btn("🧠 Grammar practice", "callready_practice"),
        _btn("📖 Phrasebook", "callready_phrasebook"),
        _btn("📈 Progress", "callready_progress"),
        _btn("🏠 Menu", "callready_menu"),
    ]}})
    return _card(CARD, "Your route 🗺", "3 blocks · 12 modules", widgets)


def build_phrasebook_menu_card() -> dict:
    """Карточка категорий фразбука (cardId callreadyPhrasebook)."""
    buttons = [_btn(cat, "callready_phrasebook_cat", cat=cat) for cat in bank.BACKUP]
    widgets = [
        {"textParagraph": {"text": "Your «panic button» phrases for tricky call moments."}},
        {"buttonList": {"buttons": buttons}},
        {"buttonList": {"buttons": [_btn("🏠 Menu", "callready_menu")]}},
    ]
    return _card(CARD, "Backup phrasebook 📖", "Pick a situation", widgets)


def build_phrasebook_cat_card(cat: str) -> dict:
    """Карточка фраз одной категории (cardId callreadyPhrasebook)."""
    phrases = bank.BACKUP.get(cat, [])
    lines = "\n".join(f"• {p}" for p in phrases) if phrases else "Nothing here 🤷"
    widgets = [
        {"textParagraph": {"text": lines}},
        {"buttonList": {"buttons": [
            _btn("↩ All situations", "callready_phrasebook"),
            _btn("🏠 Menu", "callready_menu"),
        ]}},
    ]
    return _card(CARD, f"📖 {cat}", "Backup phrasebook", widgets)


def build_practice_menu_card() -> dict:
    """Карточка выбора грамматической темы (cardId callreadyGrammar)."""
    buttons = [
        _btn(f"{t['title']}", "callready_practice_topic", topic=i)
        for i, t in enumerate(bank.GRAMMAR_TOPICS)
    ]
    widgets = [
        {"textParagraph": {"text": "Pick a grammar topic and drill the tasks."}},
        {"buttonList": {"buttons": buttons}},
        {"buttonList": {"buttons": [_btn("🏠 Menu", "callready_menu")]}},
    ]
    return _card(CARD, "Grammar practice 🧠", "8 topics · 40 tasks", widgets)


def build_topic_card(topic_idx: int) -> dict:
    """Карточка темы: справочник + кнопка «начать практику» (cardId callreadyGrammar)."""
    topic = bank.GRAMMAR_TOPICS[topic_idx]
    guide = bank.GRAMMAR_GUIDES[topic_idx]
    widgets = [
        {"textParagraph": {"text": (
            f"**{topic['rule']}**\n\n{_md(guide)}"
        )}},
        {"buttonList": {"buttons": [
            _btn("▶️ Start practice", "callready_next_task", topic=topic_idx, pos=0),
            _btn("🧠 All topics", "callready_practice"),
        ]}},
    ]
    return _card(CARD, f"🧠 {topic['title']}", topic["ru"], widgets)


def build_task_card(topic_idx: int, pos: int) -> dict:
    """Карточка одного грамматического задания (cardId callreadyGrammar)."""
    topic = bank.GRAMMAR_TOPICS[topic_idx]
    task_ids = topic["tasks"]
    task_id = task_ids[pos]
    task = bank.GRAMMAR_TASKS[task_id]
    question, options = task[0], task[1]

    answer_buttons = [
        _btn(f"{_OPTION_LETTERS[i]}. {opt}", "callready_answer", topic=topic_idx, pos=pos, answer=i)
        for i, opt in enumerate(options)
    ]
    widgets = [
        {"textParagraph": {"text": f"**Question {pos + 1}/{len(task_ids)}**\n\n{question}"}},
        {"buttonList": {"buttons": answer_buttons}},
        {"buttonList": {"buttons": [_btn("🧠 All topics", "callready_practice")]}},
    ]
    return _card(CARD, f"🧠 {topic['title']}", f"Question {pos + 1}/{len(task_ids)}", widgets)


def build_feedback_card(topic_idx: int, pos: int, correct: bool, task: list) -> dict:
    """Карточка результата ответа в grammar practice: верно/неверно + пояснение."""
    topic = bank.GRAMMAR_TOPICS[topic_idx]
    task_ids = topic["tasks"]
    task_id = task_ids[pos]
    question, options, correct_idx = task[0], task[1], task[2]

    if correct:
        head = "✅ Correct!"
    else:
        head = f"❌ Not quite — correct answer: **{options[correct_idx]}**"
    body = f"{head}\n\n**{question}**\n\n💡 {_md(task[3])}"

    widgets = [{"textParagraph": {"text": body}}]
    if pos + 1 < len(task_ids):
        widgets.append({"buttonList": {"buttons": [
            _btn("Next question →", "callready_next_task", topic=topic_idx, pos=pos + 1),
        ]}})
    else:
        widgets.append({"textParagraph": {"text": "🎉 You finished this topic!"}})
    widgets.append({"buttonList": {"buttons": [_btn("🧠 All topics", "callready_practice")]}})
    return _card(CARD, f"🧠 {topic['title']}", f"Question {pos + 1}/{len(task_ids)}", widgets)


def build_progress_card(state: dict) -> dict:
    """Карточка прогресса (cardId callreadyProgress)."""
    widgets = [
        {"textParagraph": {"text": progress_summary(state)}},
        {"buttonList": {"buttons": [
            _btn("📚 Continue", "callready_continue"),
            _btn("🗺 My route", "callready_route"),
            _btn("🏠 Menu", "callready_menu"),
        ]}},
    ]
    return _card(CARD, "Your progress 📈", "Survival English for Calls", widgets)


# ---------------------------------------------------------------------------
# Карточки тестов модуля и блока
# ---------------------------------------------------------------------------

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
    widgets.append({"buttonList": {"buttons": [_btn("🏠 Menu", "callready_menu")]}})
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
    buttons.append(_btn("🏠 Menu", "callready_menu"))
    widgets.append({"buttonList": {"buttons": buttons}})
    return _card(CARD, title, "Test result", widgets)


# ---------------------------------------------------------------------------
# Работа с БД
# ---------------------------------------------------------------------------

async def _get_or_create_progress(db: AsyncSession, profile_id: int) -> CallreadyProgress:
    row = (
        await db.execute(select(CallreadyProgress).where(CallreadyProgress.profile_id == profile_id))
    ).scalar_one_or_none()
    if row is None:
        row = CallreadyProgress(profile_id=profile_id, state=_fresh_state())
        db.add(row)
        await db.flush()
    elif not isinstance(row.state, dict):
        row.state = _fresh_state()
    return row


async def _award(db: AsyncSession, profile_id: int, points: int, reason: str, metadata: dict) -> None:
    """Начислить баллы в leaderboard_ledger (event_type 'learning')."""
    try:
        await leaderboard.award_points(
            db, profile_id, "learning", points, reason=reason, metadata=metadata,
        )
    except Exception:
        logger.exception("callready_award_failed profile=%s reason=%s", profile_id, reason)


def _resolve_module(module_id: str) -> dict | None:
    return bank.module_by_id(module_id)


async def learn_menu(db: AsyncSession, profile: Profile) -> dict:
    """Команда «learn»: карточка-меню курса."""
    await _get_or_create_progress(db, profile.id)
    await db.commit()
    return build_menu_card()


async def continue_learning(db: AsyncSession, profile: Profile) -> dict:
    """«Продолжить»: показать последний открытый (или первый) модуль."""
    row = await _get_or_create_progress(db, profile.id)
    state = _state_of(row)
    module = _resolve_module(state.get("current_module", "")) or bank.MODULES[0]
    state["current_module"] = module["id"]
    row.state = state
    await db.commit()
    return build_module_card(module, state)


async def show_module(db: AsyncSession, profile: Profile, module_id: str) -> dict:
    """Показать конкретный модуль (по кнопке маршрута)."""
    module = _resolve_module(module_id)
    if module is None:
        return {"text": "Module not found 🤷"}
    row = await _get_or_create_progress(db, profile.id)
    state = _state_of(row)
    state["current_module"] = module_id
    row.state = state
    await db.commit()
    return build_module_card(module, state)


async def next_module(db: AsyncSession, profile: Profile, module_id: str) -> dict:
    """Завершить модуль: +1 за прочтение модуля, +3 за прочтение блока (впервые)."""
    module = _resolve_module(module_id)
    if module is None:
        return {"text": "Module not found 🤷"}
    row = await _get_or_create_progress(db, profile.id)
    state = _state_of(row)
    done = list(state.get("done", []))
    blocks_read = list(state.get("blocks_read", []))

    new_module = module_id not in done
    if new_module:
        done.append(module_id)
    state["done"] = done

    new_block = False
    block = bank.block_for_module(module_id)
    if (
        block is not None
        and block["id"] not in blocks_read
        and all(m in done for m in block["modules"])
    ):
        blocks_read.append(block["id"])
        new_block = True
    state["blocks_read"] = blocks_read

    idx = bank.module_index(module_id)
    if idx + 1 < len(bank.MODULES):
        state["current_module"] = bank.MODULES[idx + 1]["id"]
        row.state = state
        await db.commit()
        if new_module:
            await _award(db, profile.id, READ_MODULE_POINTS, f"callready read module {module_id}", {"module": module_id})
        if new_block:
            await _award(db, profile.id, READ_BLOCK_POINTS, f"callready read block {block['id']}", {"block": block["id"]})
        if new_module or new_block:
            await db.commit()
        return build_module_card(bank.MODULES[idx + 1], state)

    # Последний модуль — карточка завершения.
    state["current_module"] = module_id
    row.state = state
    await db.commit()
    if new_module:
        await _award(db, profile.id, READ_MODULE_POINTS, f"callready read module {module_id}", {"module": module_id})
    if new_block:
        await _award(db, profile.id, READ_BLOCK_POINTS, f"callready read block {block['id']}", {"block": block["id"]})
    if new_module or new_block:
        await db.commit()

    widgets = [
        {"textParagraph": {"text": (
            "🎉 **Course complete!**\n\n"
            "You finished all 12 modules of Survival English for Calls.\n\n"
            + progress_summary(state)
        )}},
        {"buttonList": {"buttons": [
            _btn("🗺 My route", "callready_route"),
            _btn("📈 Progress", "callready_progress"),
            _btn("🏠 Menu", "callready_menu"),
        ]}},
    ]
    return _card(CARD, "Course complete 🏆", "Survival English for Calls", widgets)


async def prev_module(db: AsyncSession, profile: Profile, module_id: str) -> dict:
    """Показать предыдущий модуль (без начисления баллов)."""
    idx = bank.module_index(module_id)
    if idx <= 0:
        return {"text": "This is the first module 😊"}
    prev = bank.MODULES[idx - 1]
    row = await _get_or_create_progress(db, profile.id)
    state = _state_of(row)
    state["current_module"] = prev["id"]
    row.state = state
    await db.commit()
    return build_module_card(prev, state)


async def show_route(db: AsyncSession, profile: Profile) -> dict:
    """Карточка маршрута (3 блока с прогрессом)."""
    row = await _get_or_create_progress(db, profile.id)
    state = _state_of(row)
    await db.commit()
    return build_route_card(state)


async def show_phrasebook(db: AsyncSession, profile: Profile) -> dict:
    """Карточка категорий фразбука."""
    await _get_or_create_progress(db, profile.id)
    await db.commit()
    return build_phrasebook_menu_card()


async def show_phrasebook_cat(db: AsyncSession, profile: Profile, cat: str) -> dict:
    """Карточка фраз одной категории (отмечаем просмотр)."""
    if cat not in bank.BACKUP:
        return {"text": "Category not found 🤷"}
    row = await _get_or_create_progress(db, profile.id)
    state = _state_of(row)
    seen = list(state.get("phrasebook_seen", []))
    if cat not in seen:
        seen.append(cat)
    state["phrasebook_seen"] = seen
    row.state = state
    await db.commit()
    return build_phrasebook_cat_card(cat)


async def show_practice(db: AsyncSession, profile: Profile) -> dict:
    """Карточка выбора грамматической темы."""
    await _get_or_create_progress(db, profile.id)
    await db.commit()
    return build_practice_menu_card()


async def show_topic(db: AsyncSession, profile: Profile, topic_idx: int) -> dict:
    """Карточка темы: справочник + «начать практику». """
    if not (0 <= topic_idx < len(bank.GRAMMAR_TOPICS)):
        return {"text": "Topic not found 🤷"}
    await _get_or_create_progress(db, profile.id)
    await db.commit()
    return build_topic_card(topic_idx)


async def show_task(db: AsyncSession, profile: Profile, topic_idx: int, pos: int) -> dict:
    """Карточка одного задания темы."""
    if not (0 <= topic_idx < len(bank.GRAMMAR_TOPICS)):
        return {"text": "Topic not found 🤷"}
    task_ids = bank.GRAMMAR_TOPICS[topic_idx]["tasks"]
    if not (0 <= pos < len(task_ids)):
        return build_practice_menu_card()
    await _get_or_create_progress(db, profile.id)
    await db.commit()
    return build_task_card(topic_idx, pos)


async def answer(db: AsyncSession, profile: Profile, topic_idx: int, pos: int, answer_idx: int) -> dict:
    """Ответ на задание grammar practice (без баллов — это только учёба)."""
    if not (0 <= topic_idx < len(bank.GRAMMAR_TOPICS)):
        return {"text": "Topic not found 🤷"}
    task_ids = bank.GRAMMAR_TOPICS[topic_idx]["tasks"]
    if not (0 <= pos < len(task_ids)):
        return build_practice_menu_card()

    task_id = task_ids[pos]
    task = bank.GRAMMAR_TASKS[task_id]
    correct = answer_idx == task[2]

    row = await _get_or_create_progress(db, profile.id)
    state = _state_of(row)
    grammar = dict(state.get("grammar", {}))
    if correct and not grammar.get(str(task_id)):
        grammar[str(task_id)] = True
    state["grammar"] = grammar
    row.state = state
    await db.commit()

    return build_feedback_card(topic_idx, pos, correct, task)


async def show_mtest(
    db: AsyncSession, profile: Profile, module_id: str, q_idx: int, score: int,
) -> dict:
    """Показать вопрос теста модуля (словарь + грамматика)."""
    questions = module_test_questions(module_id)
    if not questions:
        return {"text": "Module not found 🤷"}
    if not (0 <= q_idx < len(questions)):
        q_idx = 0
    m = bank.module_by_id(module_id)
    title = f"📝 {m['icon']} {m['title']} — test"
    return _test_question_card(
        title, q_idx, len(questions), questions[q_idx], score,
        "callready_mtest_answer", {"module": module_id},
    )


async def answer_mtest(
    db: AsyncSession, profile: Profile, module_id: str, q_idx: int, answer_idx: int, score: int,
) -> dict:
    """Оценить ответ в тесте модуля; на последнем вопросе — итог и +1 балл."""
    questions = module_test_questions(module_id)
    if not questions or not (0 <= q_idx < len(questions)):
        return {"text": "Module not found 🤷"}
    question = questions[q_idx]
    correct = answer_idx == question["correct"]
    new_score = score + (1 if correct else 0)
    m = bank.module_by_id(module_id)
    title = f"📝 {m['icon']} {m['title']} — test"

    if q_idx + 1 < len(questions):
        return _test_feedback_card(
            title, q_idx, len(questions), question, correct, new_score,
            "callready_mtest", {"module": module_id},
        )

    passed = new_score >= MODULE_TEST_PASS
    row = await _get_or_create_progress(db, profile.id)
    state = _state_of(row)
    awarded = 0
    if passed:
        tested = list(state.get("modules_tested", []))
        if module_id not in tested:
            tested.append(module_id)
            state["modules_tested"] = tested
            awarded = MODULE_TEST_POINTS
    row.state = state
    await db.commit()
    if awarded:
        await _award(db, profile.id, awarded, f"callready module test {module_id}", {"module": module_id})
        await db.commit()
    return _test_result_card(
        title, passed, new_score, len(questions), MODULE_TEST_PASS, awarded,
        "callready_module", f"↩ {m['icon']} Module", {"module": module_id},
    )


async def show_btest(
    db: AsyncSession, profile: Profile, block_id: str, q_idx: int, score: int,
) -> dict:
    """Показать вопрос теста блока (6 словарь + 4 грамматика)."""
    questions = block_test_questions(block_id)
    if not questions:
        return {"text": "Block not found 🤷"}
    if not (0 <= q_idx < len(questions)):
        q_idx = 0
    b = bank.block_by_id(block_id)
    title = f"🏁 {b['title']} — test"
    return _test_question_card(
        title, q_idx, len(questions), questions[q_idx], score,
        "callready_btest_answer", {"block": block_id},
    )


async def answer_btest(
    db: AsyncSession, profile: Profile, block_id: str, q_idx: int, answer_idx: int, score: int,
) -> dict:
    """Оценить ответ в тесте блока; на последнем вопросе — итог и +2 балла."""
    questions = block_test_questions(block_id)
    if not questions or not (0 <= q_idx < len(questions)):
        return {"text": "Block not found 🤷"}
    question = questions[q_idx]
    correct = answer_idx == question["correct"]
    new_score = score + (1 if correct else 0)
    b = bank.block_by_id(block_id)
    title = f"🏁 {b['title']} — test"

    if q_idx + 1 < len(questions):
        return _test_feedback_card(
            title, q_idx, len(questions), question, correct, new_score,
            "callready_btest", {"block": block_id},
        )

    passed = new_score >= BLOCK_TEST_PASS
    row = await _get_or_create_progress(db, profile.id)
    state = _state_of(row)
    awarded = 0
    if passed:
        tested = list(state.get("blocks_tested", []))
        if block_id not in tested:
            tested.append(block_id)
            state["blocks_tested"] = tested
            awarded = BLOCK_TEST_POINTS
    row.state = state
    await db.commit()
    if awarded:
        await _award(db, profile.id, awarded, f"callready block test {block_id}", {"block": block_id})
        await db.commit()
    return _test_result_card(
        title, passed, new_score, len(questions), BLOCK_TEST_PASS, awarded,
        "callready_route", "🗺 My route", {},
    )


async def show_progress(db: AsyncSession, profile: Profile) -> dict:
    """Карточка прогресса."""
    row = await _get_or_create_progress(db, profile.id)
    state = _state_of(row)
    await db.commit()
    return build_progress_card(state)
