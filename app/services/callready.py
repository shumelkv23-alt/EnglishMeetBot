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

MODULE_POINTS = 10
GRAMMAR_POINTS = 1

# Единый cardId для всех карточек курса: навигация обновляет карточку НА МЕСТЕ
# (messages.patch / updateMessageAction), как у одиночных ДМ-игр.
CARD = "callready"

_OPTION_LETTERS = ("A", "B", "C")


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
        "done": [],
        "grammar": {},
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
    """Баллы из состояния: 10 за модуль + 1 за верный грамматический ответ."""
    done = len(state.get("done", []))
    grammar = len(state.get("grammar", {}))
    return done * MODULE_POINTS + grammar * GRAMMAR_POINTS


def progress_summary(state: dict) -> str:
    """Текстовый отчёт о прогрессе для карточки «📈 My progress»."""
    done = set(state.get("done", []))
    grammar = state.get("grammar", {})
    phrasebook = state.get("phrasebook_seen", [])

    block_lines = []
    for b in bank.BLOCKS:
        n = sum(1 for m in b["modules"] if m in done)
        block_lines.append(f"{b['title']}: {n}/{len(b['modules'])}")
    correct = sum(1 for v in grammar.values() if v)
    total_tasks = len(bank.GRAMMAR_TASKS)
    pct = round(100 * correct / total_tasks) if total_tasks else 0

    return (
        f"Modules completed: **{len(done)}/{len(bank.MODULES)}**\n"
        + "\n".join(block_lines)
        + f"\n\nGrammar: **{correct}/{total_tasks}** correct ({pct}%)\n"
        + f"Phrasebook: **{len(phrasebook)}/{len(bank.BACKUP)}** sections seen\n\n"
        + f"Points earned: **{module_points(state)}**"
    )


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
    """Карточка маршрута (cardId callreadyRoute): 3 блока с прогрессом."""
    done = set(state.get("done", []))
    widgets = []
    for b in bank.BLOCKS:
        lines = []
        for m_id in b["modules"]:
            m = bank.module_by_id(m_id)
            mark = "✅" if m_id in done else "▫️"
            lines.append(f"{mark} {m['icon']} {m['title']}" if m else f"{mark} {m_id}")
        widgets.append({"textParagraph": {"text": f"**{b['title']}**\n" + "\n".join(lines)}})
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


def build_feedback_card(topic_idx: int, pos: int, correct: bool, task: list, points: int) -> dict:
    """Карточка результата ответа: верно/неверно + пояснение + «дальше»."""
    topic = bank.GRAMMAR_TOPICS[topic_idx]
    task_ids = topic["tasks"]
    task_id = task_ids[pos]
    question, options, correct_idx = task[0], task[1], task[2]

    if correct:
        head = f"✅ Correct! (+{points} point{'s' if points != 1 else ''})"
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
    """Завершить модуль (+10, первый раз) и показать следующий (или финал)."""
    module = _resolve_module(module_id)
    if module is None:
        return {"text": "Module not found 🤷"}
    row = await _get_or_create_progress(db, profile.id)
    state = _state_of(row)
    done = list(state.get("done", []))

    awarded = 0
    if module_id not in done:
        done.append(module_id)
        awarded = MODULE_POINTS
    state["done"] = done

    idx = bank.module_index(module_id)
    if idx + 1 < len(bank.MODULES):
        nxt = bank.MODULES[idx + 1]
        state["current_module"] = nxt["id"]
        row.state = state
        await db.commit()
        if awarded:
            await _award(db, profile.id, awarded, f"callready module {module_id}", {"module": module_id})
            await db.commit()
        return build_module_card(nxt, state)

    # Последний модуль — карточка завершения.
    state["current_module"] = module_id
    row.state = state
    await db.commit()
    if awarded:
        await _award(db, profile.id, awarded, f"callready module {module_id}", {"module": module_id})
        await db.commit()

    widgets = [
        {"textParagraph": {"text": (
            "🎉 **Course complete!**\n\n"
            "You finished all 12 modules of Survival English for Calls.\n\n"
            + progress_summary(state)
        )}},
        {"buttonList": {"buttons": [
            _btn("🧠 Grammar practice", "callready_practice"),
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
    """Ответ на задание: +1 за первый верный ответ, показать результат."""
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

    awarded = 0
    if correct and not grammar.get(str(task_id)):
        grammar[str(task_id)] = True
        awarded = GRAMMAR_POINTS
    state["grammar"] = grammar
    row.state = state
    await db.commit()
    if awarded:
        await _award(db, profile.id, awarded, f"callready grammar task {task_id}", {"task_id": task_id})
        await db.commit()

    return build_feedback_card(topic_idx, pos, correct, task, awarded)


async def show_progress(db: AsyncSession, profile: Profile) -> dict:
    """Карточка прогресса."""
    row = await _get_or_create_progress(db, profile.id)
    state = _state_of(row)
    await db.commit()
    return build_progress_card(state)
