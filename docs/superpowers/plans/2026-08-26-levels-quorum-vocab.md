# Levels, Quorum, Personalized Questions & Vocabulary — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a CEFR English level to onboarding (with an ability to change it via `/level`), raise weekly poll quorum to 4, make weekly questions match the user's level, and DM topic-specific vocabulary to attendees before the lesson.

**Architecture:** The `profiles.english_level` column already exists and the card engine already reads it for difficulty. We populate that field from onboarding/`/level`, then thread it into three places that don't use it yet: weekly-question LLM prompt, a new per-level vocabulary DM, and the quorum config (unrelated, one-line + migration).

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy async (PostgreSQL), Alembic, Google Chat cards (cardsV2 + formInputs), Azati LLM (`llm_games_model`) + OpenRouter (`llm_model`), pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-08-26-levels-quorum-vocab-design.md`

## Global Constraints

- Python 3.11+, PEP 8 + type hints; docstrings on functions; comments in Russian.
- Run tests with the venv python: `./venv/Scripts/python.exe -m pytest <path> -q` (Windows).
- e2e tests require a running PostgreSQL and are marked `-m e2e`.
- LLM keys come from `.env`; **never commit `.env` / `sa-key.json`** or their values.
- CEFR codes are exactly `A1 A2 B1 B2 C1 C2` (canonical dict lives in `app/services/levels.py`).
- Alembic has a known "multiple heads" quirk (duplicate 0005) — always upgrade by specific revision: `alembic upgrade 0012`.
- Git branch is `games-kirill`; commit after each task.
- `.env`/`sa-key.json` are gitignored — do not stage them.

---

### Task 1: `levels.py` — CEFR constants + level card

**Files:**
- Create: `app/services/levels.py`
- Test: `tests/test_levels_units.py`

**Interfaces:**
- Produces (used by Tasks 3–7): `CEFR_LEVELS: dict[str, str]`, `CEFR_ORDER: dict[str, int]`, `normalize_level(value: str) -> str | None`, `level_choice_items() -> list[dict]`, `levels_description() -> str`, `build_level_card(current_level: str | None, action_url: str) -> dict`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_levels_units.py`:

```python
# tests/test_levels_units.py
from app.services.levels import (
    CEFR_LEVELS,
    CEFR_ORDER,
    build_level_card,
    level_choice_items,
    normalize_level,
)


def test_normalize_level_accepts_cefr_code():
    assert normalize_level("A1") == "A1"
    assert normalize_level("  c2 ") == "C2"


def test_normalize_level_rejects_unknown():
    assert normalize_level("X9") is None
    assert normalize_level("") is None


def test_level_choice_items_covers_all_cefr():
    codes = [item["value"] for item in level_choice_items()]
    assert codes == list(CEFR_LEVELS.keys())


def test_build_level_card_contains_current_level():
    card = build_level_card("B1", "aud")
    assert "Current level: B1" in str(card)
    assert "set_level" in str(card)


def test_build_level_card_without_level():
    card = build_level_card(None, "aud")
    assert "Current level:" not in str(card)


def test_cefr_order_is_monotonic():
    assert CEFR_ORDER["A1"] < CEFR_ORDER["C2"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe -m pytest tests/test_levels_units.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.levels'`.

- [ ] **Step 3: Write minimal implementation**

Create `app/services/levels.py`:

```python
# app/services/levels.py
"""Уровни английского (CEFR): константы, валидация и карточка выбора уровня.

Единый источник описаний уровней для онбординга, команды /level и backfill.
Не импортирует ничего из app — чистый модуль, чтобы не плодить циклические импорты.
"""
CEFR_LEVELS: dict[str, str] = {
    "A1": "Beginner — I know a few words and simple phrases.",
    "A2": "Elementary — I can talk about everyday things in simple sentences.",
    "B1": "Intermediate — I can hold a conversation on familiar topics.",
    "B2": "Upper-Intermediate — I speak fairly fluently, with some mistakes.",
    "C1": "Advanced — I speak fluently on complex topics.",
    "C2": "Proficient — I speak nearly like a native speaker.",
}

CEFR_ORDER: dict[str, int] = {code: i for i, code in enumerate(CEFR_LEVELS)}


def normalize_level(value: str) -> str | None:
    """Канонизировать значение уровня из формы. 'A1'/'a1' → 'A1'; мусор → None."""
    code = (value or "").strip().upper()
    return code if code in CEFR_LEVELS else None


def level_choice_items() -> list[dict]:
    """Опции radio для карточки уровня: text = 'A1 — Beginner', value = 'A1'."""
    return [
        {"text": f"{code} — {CEFR_LEVELS[code].split(' — ')[0]}", "value": code, "selected": False}
        for code in CEFR_LEVELS
    ]


def levels_description() -> str:
    """Расшифровка уровней одним текстом для пояснительного блока."""
    return "\n".join(f"{code} · {desc}" for code, desc in CEFR_LEVELS.items())


def build_level_card(current_level: str | None, action_url: str) -> dict:
    """Карточка выбора уровня (radio + Save). current_level — для строки «Current level»."""
    sections: list[dict] = [
        {
            "widgets": [
                {
                    "textParagraph": {
                        "text": (
                            "We'll use your level to send you questions and vocabulary "
                            "that fit you. This is the only reason we ask."
                        )
                    }
                },
                {"divider": {}},
            ]
        }
    ]
    if current_level:
        sections.append({
            "widgets": [{"textParagraph": {"text": f"Current level: {current_level}"}}]
        })
    sections.append({
        "header": "Pick your level",
        "widgets": [
            {
                "selectionInput": {
                    "name": "q_level",
                    "label": "CEFR level",
                    "type": "RADIO_BUTTON",
                    "items": level_choice_items(),
                }
            },
            {"textParagraph": {"text": levels_description()}},
        ],
    })
    sections.append({
        "widgets": [{
            "buttonList": {"buttons": [{
                "text": "Save",
                "onClick": {"action": {
                    "function": action_url or "set_level",
                    "parameters": [{"key": "method", "value": "set_level"}],
                }},
            }]}
        }]
    })
    return {
        "cardsV2": [{
            "cardId": "levelCard",
            "card": {"header": {"title": "Your English level"}, "sections": sections},
        }]
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./venv/Scripts/python.exe -m pytest tests/test_levels_units.py -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add app/services/levels.py tests/test_levels_units.py
git commit -m "feat(levels): CEFR constants, validation and level-pick card"
```

---

### Task 2: Raise weekly poll quorum 3 → 4

**Files:**
- Modify: `app/services/weekly_poll.py:330`
- Create: `alembic/versions/0012_quorum_level.py`
- Modify: `tests/e2e/test_jobs.py:44-72`

**Interfaces:**
- Consumes: none.
- Produces: quorum threshold is 4 (both code default and stored `config.quorum_threshold`).

- [ ] **Step 1: Update the e2e boundary tests to the new quorum (this is the failing test)**

Edit `tests/e2e/test_jobs.py`:

Replace `test_finalize_creates_meeting_on_quorum` (lines 44-59):

```python
async def test_finalize_creates_meeting_on_quorum(db, today_poll):
    for i in range(4):  # кворум по умолчанию = 4
        p = await get_or_create_profile(db, f"users/e2e_fin_{i}")
        await submit_poll(db, p, FORM_1500)

    result = await finalize_day(db, today_poll, 0)
    assert result is not None
    _, time_str = result
    assert time_str == "15:00"

    meetings = (
        await db.execute(select(MeetingInstance).where(MeetingInstance.poll_id == today_poll.id))
    ).scalars().all()
    assert len(meetings) == 1
    m = meetings[0]
    assert m.scheduled_end - m.scheduled_start == timedelta(minutes=60)
```

Replace `test_finalize_cancels_without_quorum` (lines 62-72):

```python
async def test_finalize_cancels_without_quorum(db, today_poll):
    for i in range(3):  # 3 голоса < кворума 4
        p = await get_or_create_profile(db, f"users/e2e_cancel_{i}")
        await submit_poll(db, p, FORM_1500)

    result = await finalize_day(db, today_poll, 0)
    assert result is None

    meetings = (
        await db.execute(select(MeetingInstance).where(MeetingInstance.poll_id == today_poll.id))
    ).scalars().all()
    assert len(meetings) == 0
```

- [ ] **Step 2: Run the two tests to verify they fail**

Run: `./venv/Scripts/python.exe -m pytest tests/e2e/test_jobs.py::test_finalize_creates_meeting_on_quorum tests/e2e/test_jobs.py::test_finalize_cancels_without_quorum -m e2e -q`
Expected: `test_finalize_creates_meeting_on_quorum` FAILS (3 votes no longer reach quorum 4) — wait, with 4 votes against a still-3 quorum it would actually PASS and the cancels test would FAIL (3 votes >= 3). The real failure is in `test_finalize_cancels_without_quorum`: 3 votes currently PASS the quorum-3 check and would create a meeting. So expect `test_finalize_cancels_without_quorum` FAIL.

- [ ] **Step 3: Change the code default**

In `app/services/weekly_poll.py:330`, change:

```python
    quorum = int((await get_or_create_config(db, "quorum_threshold", 3)).value or 3)
```

to:

```python
    quorum = int((await get_or_create_config(db, "quorum_threshold", 4)).value or 4)
```

- [ ] **Step 4: Add the migration for the stored value**

Create `alembic/versions/0012_quorum_level.py`:

```python
# alembic/versions/0012_quorum_level.py
"""Кворум недельного опроса 3 -> 4: обновить засиженное значение config.

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-26
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0012"
down_revision: Union[str, Sequence[str], None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE config SET value = '4'::jsonb WHERE key = 'quorum_threshold'")


def downgrade() -> None:
    op.execute("UPDATE config SET value = '3'::jsonb WHERE key = 'quorum_threshold'")
```

- [ ] **Step 5: Apply the migration**

Run: `alembic upgrade 0012`
Expected: `config.quorum_threshold` becomes 4.

- [ ] **Step 6: Run the two tests to verify they pass**

Run: `./venv/Scripts/python.exe -m pytest tests/e2e/test_jobs.py::test_finalize_creates_meeting_on_quorum tests/e2e/test_jobs.py::test_finalize_cancels_without_quorum -m e2e -q`
Expected: PASS (2 passed).

- [ ] **Step 7: Commit**

```bash
git add app/services/weekly_poll.py alembic/versions/0012_quorum_level.py tests/e2e/test_jobs.py
git commit -m "feat(poll): raise weekly quorum threshold 3 -> 4"
```

---

### Task 3: Onboarding asks for English level (q8)

**Files:**
- Modify: `app/services/onboarding_answers.py` (add `q8`, persist `english_level`)
- Modify: `app/api/google_chat.py` (`_onboarding_card`, ~line 1607)
- Test: `tests/test_onboarding_level_units.py`

**Interfaces:**
- Consumes: `normalize_level` from Task 1; `level_choice_items`, `levels_description` from Task 1.
- Produces: `profile.english_level` is set from the onboarding form.

- [ ] **Step 1: Write the failing test**

Create `tests/test_onboarding_level_units.py`:

```python
# tests/test_onboarding_level_units.py
from app.models import Profile
from app.services.onboarding_answers import (
    parse_onboarding_form,
    update_profile_from_onboarding,
)


def _form_with_level(level: str) -> dict:
    return {"q8": {"stringInputs": {"value": [level]}}}


def test_parse_onboarding_form_reads_q8():
    parsed = parse_onboarding_form(_form_with_level("B1"))
    q8 = next(item for item in parsed if item["question"].startswith("8."))
    assert q8["choice"] == "B1"


def test_update_profile_sets_english_level():
    profile = Profile(workspace_user_id="users/x", user_email="x@example.com")
    parsed = parse_onboarding_form(_form_with_level("C1"))
    update_profile_from_onboarding(None, profile, parsed)
    assert profile.english_level == "C1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe -m pytest tests/test_onboarding_level_units.py -q`
Expected: FAIL — `parse_onboarding_form` has no `8.` question, so `next(...)` raises `StopIteration`.

- [ ] **Step 3: Add q8 to the QUESTIONS map + persist the level**

In `app/services/onboarding_answers.py`:

Add the import at the top:

```python
from app.services.levels import normalize_level
```

Add `q8` to the `QUESTIONS` dict (after `q7`):

```python
    "q7": "7. What communication style is more comfortable for you?",
    "q8": "8. What's your English level?",
```

In `update_profile_from_onboarding`, after the q6 consent block (before the `onboarding_answers` assignment):

```python
    # q8 -> english_level
    q8_value = by_question.get(QUESTIONS["q8"], {}).get("choice", "")
    level = normalize_level(q8_value)
    if level:
        profile.english_level = level
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./venv/Scripts/python.exe -m pytest tests/test_onboarding_level_units.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Add q8 to the onboarding card**

In `app/api/google_chat.py`, add the import near the top (with the other `app.services` imports):

```python
from app.services.levels import level_choice_items, levels_description
```

In `_onboarding_card`, insert a q8 section between the q7 section (ends ~line 1607) and the submit-button section (~line 1608):

```python
                        {
                            "header": "8. What's your English level?",
                            "widgets": [
                                {
                                    "textParagraph": {
                                        "text": (
                                            "We'll use it to send you questions and vocabulary "
                                            "that fit you.\n" + levels_description()
                                        )
                                    }
                                },
                                {
                                    "selectionInput": {
                                        "name": "q8",
                                        "label": "Pick your level",
                                        "type": "RADIO_BUTTON",
                                        "items": level_choice_items(),
                                    }
                                },
                            ],
                        },
```

- [ ] **Step 6: Commit**

```bash
git add app/services/onboarding_answers.py app/api/google_chat.py tests/test_onboarding_level_units.py
git commit -m "feat(onboarding): ask for CEFR level (q8) and persist it"
```

---

### Task 4: `/level` command + `set_level` handler

**Files:**
- Modify: `app/api/google_chat.py` (matcher, routing add-on + classic, `_level_payload`, `_set_level`)
- Test: `tests/test_google_chat_level.py`

**Interfaces:**
- Consumes: `build_level_card`, `normalize_level` from Task 1; existing `_space_is_dm`, `_extract_space_dict`, `_dm_space_name`, `_addon_response`, `_onboarding_action_method`, `_action_method`, `AsyncSessionLocal`, `get_or_create_profile`.
- Produces: `_is_level_command(raw_text) -> bool`, `_level_payload(chat_data) -> dict`, `_set_level(chat_data, common) -> JSONResponse`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_google_chat_level.py`:

```python
# tests/test_google_chat_level.py
from app.api.google_chat import _is_level_command


def test_is_level_command_matches_variants():
    assert _is_level_command("/level")
    assert _is_level_command("!level")
    assert _is_level_command("level")
    assert _is_level_command("уровень")


def test_is_level_command_ignores_other_text():
    assert not _is_level_command("hello")
    assert not _is_level_command("leveling up")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe -m pytest tests/test_google_chat_level.py -q`
Expected: FAIL with `ImportError: cannot import name '_is_level_command'`.

- [ ] **Step 3: Add the matcher**

In `app/api/google_chat.py`, add near the other `_is_*_command` matchers (~line 205):

```python
def _is_level_command(raw_text: str) -> bool:
    """Пользователь просит показать/поменять свой уровень (команда /level).

    Google Chat перехватывает '/...' как нативную слэш-команду, поэтому в живой
    переписке реальный триггер — '!level'; '/level' остаётся для тестов.
    """
    text = raw_text.lower().strip()
    for prefix in ("/", "!"):
        if text.startswith(prefix):
            text = text[1:].strip()
            break
    return any(text == t or text.startswith(t + " ") for t in ("level", "уровень", "lvl"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./venv/Scripts/python.exe -m pytest tests/test_google_chat_level.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Add `_level_payload` and `_set_level` handlers**

Add the imports at the top of `app/api/google_chat.py`:

```python
from app.services.form_parsing import parse_form_inputs
from app.services.levels import build_level_card, normalize_level
```

Add the handlers near `_submit_onboarding` (~line 846):

```python
async def _level_payload(chat_data: dict) -> dict:
    """Payload для /level: карточка выбора уровня в личке (с текущим уровнем), текст в группе."""
    space = _extract_space_dict(chat_data)
    if not _space_is_dm(space):
        return {"text": "DM me to change your English level 🙌"}
    user = chat_data.get("user", {})
    workspace_user_id = user.get("name", "")
    current = None
    if workspace_user_id:
        try:
            async with AsyncSessionLocal() as db:
                profile = await get_or_create_profile(
                    db, workspace_user_id=workspace_user_id,
                    email=user.get("email"), display_name=user.get("displayName"),
                    chat_space_id=_dm_space_name(space),
                )
                current = profile.english_level
        except Exception:
            logger.exception("level_command_profile_failed")
    return build_level_card(current, settings.chat_app_audience)


async def _set_level(chat_data: dict, common: dict) -> JSONResponse:
    """Сохранение выбранного уровня из карточки /level (или backfill)."""
    form_inputs = common.get("formInputs", {}) or {}
    values = parse_form_inputs(form_inputs).get("q_level", [])
    level = normalize_level(values[0]) if values else None
    user = chat_data.get("user", {})
    workspace_user_id = user.get("name", "")
    if workspace_user_id and level:
        try:
            space = _extract_space_dict(chat_data)
            async with AsyncSessionLocal() as db:
                profile = await get_or_create_profile(
                    db, workspace_user_id=workspace_user_id,
                    email=user.get("email"), display_name=user.get("displayName"),
                    chat_space_id=_dm_space_name(space),
                )
                profile.english_level = level
                await db.commit()
        except Exception:
            logger.exception("set_level_failed")
            return _addon_response({"text": "Couldn't save your level. Try again 🤞"})
        return _addon_response(
            {"text": f"Got it — your level is now {level}. Questions and vocabulary will match it 🎯"}
        )
    return _addon_response({"text": "Something went wrong. Try again."})
```

- [ ] **Step 6: Route `/level` in both message dispatchers**

Add-on MESSAGE branch — after the `_is_games_command` block (~line 1983), insert:

```python
            if _is_level_command(raw_text):
                return _addon_response(await _level_payload(chat_data))
```

Classic MESSAGE branch — after the `_is_games_command` block (~line 2129), insert:

```python
        if _is_level_command(raw_text):
            return JSONResponse(content=await _level_payload(event))
```

- [ ] **Step 7: Route the `set_level` card submit in both CARD_CLICKED dispatchers**

Add-on `buttonClickedPayload` branch — after `if method == "submit_weekly_question"` (~line 1860), insert:

```python
            if method == "set_level":
                return await _set_level(chat_data, common)
```

Classic CARD_CLICKED branch — after the `submit_weekly_poll` block (~line 2213), insert:

```python
        if function_name == "set_level" or method == "set_level":
            user = event.get("user", {})
            space = event.get("space", {})
            form_inputs = event.get("common", {}).get("formInputs", {})
            return await _set_level({"user": user, "space": space}, {"formInputs": form_inputs})
```

- [ ] **Step 8: Smoke-check imports parse**

Run: `./venv/Scripts/python.exe -c "import app.api.google_chat"`
Expected: no output / exit 0 (no `ImportError`/`SyntaxError`).

- [ ] **Step 9: Commit**

```bash
git add app/api/google_chat.py tests/test_google_chat_level.py
git commit -m "feat(level): /level command and set_level card handler"
```

---

### Task 5: Weekly questions by level + self-heal backfill

**Files:**
- Modify: `app/services/llm_questions.py` (level-aware prompt)
- Modify: `app/services/weekly_questions.py` (pass level + self-heal for NULL)
- Create: `scripts/backfill_levels.py`
- Test: `tests/test_llm_questions_level.py`

**Interfaces:**
- Consumes: `build_level_card` from Task 1.
- Produces: `generate_personal_question(interests, *, level="A2", ...)`; `questions_for_profile(interests, week_start, level, avoid=None)`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_llm_questions_level.py`:

```python
# tests/test_llm_questions_level.py
import json
from unittest.mock import patch

from app.services.llm_questions import _system_prompt, generate_personal_question


def test_system_prompt_includes_level_hint():
    a1 = _system_prompt("A1")
    c2 = _system_prompt("C2")
    assert "A1" in a1 and "simple" in a1
    assert "C2" in c2 and "idiomatic" in c2


def test_generate_personal_question_uses_level_prompt(monkeypatch):
    captured = {}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": json.dumps({"question_text": "Q?"})}}]}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["payload"] = json
        return _Resp()

    monkeypatch.setattr("app.services.llm_questions.requests.post", fake_post)

    q = generate_personal_question(["food"], level="C1", api_key="k", model="m")
    assert q == "Q?"
    system = captured["payload"]["messages"][0]["content"]
    assert "C1" in system


def test_questions_for_profile_passes_level(monkeypatch):
    from app.services import weekly_questions as wq

    captured = {}

    def fake_generate(interests, level="A2", avoid=None):
        captured["level"] = level
        return "personal?"

    monkeypatch.setattr(wq, "generate_personal_question", fake_generate)

    personal, _bank = wq.questions_for_profile(["food"], wq.current_week_start(), "C1", avoid=[])
    assert personal == "personal?"
    assert captured["level"] == "C1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe -m pytest tests/test_llm_questions_level.py -q`
Expected: FAIL with `AttributeError: module 'app.services.llm_questions' has no attribute '_system_prompt'`.

- [ ] **Step 3: Add the level-aware prompt**

In `app/services/llm_questions.py`, replace the `_SYSTEM_PROMPT` constant (lines 17-24) with a level-aware function:

```python
_LEVEL_HINTS = {
    "A1": "Use very simple words and short sentences. Ask about concrete everyday things (food, weather, family, hobbies).",
    "A2": "Use simple everyday language. Ask about concrete personal experience.",
    "B1": "Use everyday language; invite opinions and reasons (\"why\").",
    "B2": "Use natural conversational English; invite opinions, comparisons and hypotheticals.",
    "C1": "Use sophisticated English; invite nuanced opinions and abstract ideas.",
    "C2": "Use idiomatic, near-native English; invite complex, abstract discussion.",
}


def _system_prompt(level: str) -> str:
    """Системный промпт генератора вопроса, адаптированный под уровень."""
    hint = _LEVEL_HINTS.get(level, _LEVEL_HINTS["B1"])
    return (
        "You generate ONE short conversational question in English for English practice "
        "at the weekly colleagues' meetup. The question is lively, about everyday life "
        "(food, movies, travel, hobbies, funny moments). Invites a short 1-2 minute story. "
        "The person's interests are just one possible guide, don't fixate on them. "
        f"Level: {level}. {hint} "
        'Return strict JSON of the form {"question_text": "question text"}. No comments or markup.'
    )
```

In `generate_personal_question`, add the `level` param and use `_system_prompt(level)`:

```python
def generate_personal_question(
    interests: list[str],
    *,
    api_key: str | None = None,
    model: str | None = None,
    timeout: float = 10.0,
    avoid: list[str] | None = None,
    level: str = "A2",
) -> str | None:
```

…and in the payload, change `"system": _SYSTEM_PROMPT,` (line 89) to `"system": _system_prompt(level),`.

- [ ] **Step 4: Run test to verify it passes**

Run: `./venv/Scripts/python.exe -m pytest tests/test_llm_questions_level.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Thread level through `questions_for_profile` and self-heal in `send_weekly_questions`**

In `app/services/weekly_questions.py`, add the import at the top:

```python
from app.services.levels import build_level_card
```

Change `questions_for_profile` signature and the LLM call:

```python
def questions_for_profile(
    interests: list[str] | None, week_start: date, level: str, avoid: list[str] | None = None
) -> tuple[str, str]:
    """Два вопроса недели: (персональный LLM по уровню, общий из банка)."""
    bank = bank_questions_for(week_start)
    personal = generate_personal_question(interests or [], level=level, avoid=avoid)
    if personal is None:
        personal = bank[1]
    return personal, bank[0]
```

In `send_weekly_questions`, inside the `for p in profiles:` loop, insert the self-heal right after the `if answered: continue` check (before `past = ...`):

```python
        if not p.english_level:
            # Ещё не указан уровень — сначала спрашиваем его, а не вопрос недели.
            send_message(
                p.workspace_user_id,
                MessagePayload(
                    text="Quick question about your English level 🙂",
                    card=build_level_card(None, get_settings().chat_app_audience),
                ),
            )
            sent += 1
            continue
```

And change the `questions_for_profile` call in the loop:

```python
        personal_q, bank_q = await asyncio.to_thread(
            questions_for_profile, p.interests, week_start, p.english_level or "A2", past
        )
```

- [ ] **Step 6: Create the one-off backfill script**

Create `scripts/backfill_levels.py`:

```python
# scripts/backfill_levels.py
"""Разовый переспрос уровня у активных профилей с english_level IS NULL.

Запуск: ./venv/Scripts/python -m scripts.backfill_levels
"""
import asyncio

from sqlalchemy import select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import Profile
from app.services.chat_sender import send_message
from app.services.levels import build_level_card


async def main() -> None:
    audience = get_settings().chat_app_audience
    async with AsyncSessionLocal() as db:
        profiles = (
            await db.execute(
                select(Profile).where(
                    Profile.is_active.is_(True),
                    Profile.chat_space_id.isnot(None),
                    Profile.english_level.is_(None),
                )
            )
        ).scalars().all()

    sent = 0
    for p in profiles:
        if not p.workspace_user_id:
            continue
        card = build_level_card(None, audience)
        send_message(
            p.workspace_user_id,
            text="Quick question about your English level 🙂",
            cards_v2=card["cardsV2"],
        )
        sent += 1
    print(f"level prompts sent: {sent}")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 7: Commit**

```bash
git add app/services/llm_questions.py app/services/weekly_questions.py scripts/backfill_levels.py tests/test_llm_questions_level.py
git commit -m "feat(questions): level-aware weekly questions + NULL-level self-heal"
```

---

### Task 6: Vocabulary module (per-level, topic-specific)

**Files:**
- Create: `app/services/vocab.py`
- Test: `tests/test_vocab_units.py`

**Interfaces:**
- Consumes: `_call_llm`, `_parse_json` from `app.cards.generator.llm`; `CEFR_LEVELS` from Task 1; `chat_sender.send_message`.
- Produces: `generate_vocab(level: str, topic: str) -> list[dict]`, `build_vocab_card(topic: str, phrases: list[dict]) -> dict`, `send_vocab_dms(db, meeting, topic, profiles) -> int`, `_group_level(profiles) -> dict[str, list[Profile]]`, `_fallback(level) -> list[dict]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_vocab_units.py`:

```python
# tests/test_vocab_units.py
import asyncio

from app.models import Profile
from app.services.vocab import _fallback, _group_level, build_vocab_card, generate_vocab


def _profile(uid, level):
    return Profile(workspace_user_id=uid, user_email=f"{uid}@x.com", english_level=level)


def test_fallback_returns_phrases():
    phrases = _fallback("A1")
    assert len(phrases) >= 3
    assert all("phrase" in p and "example" in p for p in phrases)


def test_group_level_defaults_null_to_a2():
    groups = _group_level([
        _profile("users/a", None),
        _profile("users/b", "B1"),
        _profile("users/c", "A2"),
    ])
    assert set(groups) == {"A2", "B1"}
    assert len(groups["A2"]) == 2


def test_build_vocab_card_has_topic_and_phrases():
    card = build_vocab_card("Travel", [{"phrase": "Hi", "example": "Hi there"}])
    s = str(card)
    assert "Travel" in s
    assert "Hi" in s


def test_generate_vocab_no_key_returns_fallback(monkeypatch):
    empty = type("S", (), {"llm_api_key": "", "llm_games_model": ""})()
    monkeypatch.setattr("app.services.vocab.get_settings", lambda: empty)
    phrases = asyncio.run(generate_vocab("A1", "Food"))
    assert phrases == _fallback("A1")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe -m pytest tests/test_vocab_units.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.vocab'`.

- [ ] **Step 3: Write the vocabulary module**

Create `app/services/vocab.py`:

```python
# app/services/vocab.py
"""Персональная лексика к занятию: генерация по уровню и рассылка в личку."""
import asyncio
import logging
from collections import defaultdict

from sqlalchemy.ext.asyncio import AsyncSession

from app.cards.generator.llm import _call_llm, _parse_json
from app.config import get_settings
from app.models import MeetingInstance, Profile
from app.services.chat_sender import send_message
from app.services.levels import CEFR_LEVELS

logger = logging.getLogger(__name__)

DEFAULT_LEVEL = "A2"

# Fallback-фразы по уровню (на случай сбоя LLM или пустого ключа).
_FALLBACK_VOCAB: dict[str, list[dict]] = {
    "A1": [
        {"phrase": "How are you?", "example": "How are you today?"},
        {"phrase": "I like ...", "example": "I like coffee."},
        {"phrase": "I think ...", "example": "I think it is good."},
    ],
    "A2": [
        {"phrase": "In my opinion, ...", "example": "In my opinion, this is a great idea."},
        {"phrase": "I agree / I disagree", "example": "I disagree with that."},
        {"phrase": "What do you think?", "example": "What do you think about it?"},
    ],
    "B1": [
        {"phrase": "It depends on ...", "example": "It depends on the situation."},
        {"phrase": "I'd rather ...", "example": "I'd rather talk about travel."},
        {"phrase": "To be honest, ...", "example": "To be honest, I'm not sure."},
    ],
    "B2": [
        {"phrase": "On the one hand ... on the other hand ...", "example": "On the one hand it's exciting, on the other hand it's risky."},
        {"phrase": "It's worth noting that ...", "example": "It's worth noting that opinions differ."},
        {"phrase": "From my perspective, ...", "example": "From my perspective, it's a good trade-off."},
    ],
    "C1": [
        {"phrase": "That raises the question of ...", "example": "That raises the question of what 'success' means."},
        {"phrase": "It goes without saying that ...", "example": "It goes without saying that context matters."},
        {"phrase": "Arguably, ...", "example": "Arguably, this is the most important factor."},
    ],
    "C2": [
        {"phrase": "To paint with a broad brush, ...", "example": "To paint with a broad brush, culture shapes how we argue."},
        {"phrase": "That's a nuanced point.", "example": "That's a nuanced point — it depends heavily on context."},
        {"phrase": "Let's not conflate A with B.", "example": "Let's not conflate correlation with causation."},
    ],
}


def _fallback(level: str) -> list[dict]:
    return _FALLBACK_VOCAB.get(level, _FALLBACK_VOCAB[DEFAULT_LEVEL])


async def generate_vocab(level: str, topic: str) -> list[dict]:
    """5–7 фраз по теме под уровень (LLM). Сбой/пустой ключ → fallback."""
    settings = get_settings()
    if not settings.llm_api_key or not settings.llm_games_model:
        return _fallback(level)
    payload = {
        "model": settings.llm_games_model,
        "max_tokens": 1024,
        "system": (
            "You prepare a short vocabulary list for an English learner before a "
            "conversation meetup. All content is strictly in English. Answer ONLY "
            "with valid JSON, no comments or markdown."
        ),
        "messages": [{
            "role": "user",
            "content": (
                f"Level: {level}. Topic: {topic}. "
                "Return strict JSON of the form {\"phrases\": [{\"phrase\": \"...\", \"example\": \"...\"}]} "
                "with 5-7 useful phrases for discussing this topic at this level. "
                "Examples are short, natural sentences in English."
            ),
        }],
    }
    content = await _call_llm(payload, timeout=60.0)
    if not content:
        return _fallback(level)
    data = _parse_json(content)
    phrases = [
        {"phrase": str(p.get("phrase") or "").strip(), "example": str(p.get("example") or "").strip()}
        for p in (data.get("phrases") or [])
        if isinstance(p, dict) and str(p.get("phrase") or "").strip()
    ]
    return phrases or _fallback(level)


def build_vocab_card(topic: str, phrases: list[dict]) -> dict:
    """DM-карточка «Vocabulary for today» со списком фраз."""
    widgets = [
        {"decoratedText": {"topLabel": p["phrase"], "text": p["example"], "wrapText": True}}
        for p in phrases
    ]
    widgets.append({"textParagraph": {"text": "Too easy or too hard? Send /level to adjust 🎯"}})
    return {
        "cardsV2": [{
            "cardId": "vocabCard",
            "card": {
                "header": {"title": f"📚 Vocabulary for today: {topic}"},
                "sections": [{"header": "Useful phrases", "widgets": widgets}],
            },
        }]
    }


def _group_level(profiles: list[Profile]) -> dict[str, list[Profile]]:
    """Сгруппировать профили по уровню; NULL → DEFAULT_LEVEL."""
    groups: dict[str, list[Profile]] = defaultdict(list)
    for p in profiles:
        level = p.english_level if p.english_level in CEFR_LEVELS else DEFAULT_LEVEL
        groups[level].append(p)
    return dict(groups)


async def send_vocab_dms(
    db: AsyncSession,
    meeting: MeetingInstance,
    topic: str,
    profiles: list[Profile],
) -> int:
    """Рассылка лексики участникам в личку (одна генерация на уровень)."""
    sent = 0
    for level, group in _group_level(profiles).items():
        phrases = await generate_vocab(level, topic)
        card = build_vocab_card(topic, phrases)
        for p in group:
            if not p.workspace_user_id:
                continue
            try:
                await asyncio.to_thread(
                    send_message, p.workspace_user_id,
                    text=f"📚 Vocabulary for today: {topic}",
                    cards_v2=card["cardsV2"],
                )
                sent += 1
            except Exception:
                logger.exception("vocab_dm_failed profile=%s", p.id)
    logger.info("vocab_sent meeting=%s count=%s", meeting.id, sent)
    return sent
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./venv/Scripts/python.exe -m pytest tests/test_vocab_units.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add app/services/vocab.py tests/test_vocab_units.py
git commit -m "feat(vocab): per-level topic vocabulary generation and DM card"
```

---

### Task 7: Hook vocabulary into `send_card` + idempotency guard

**Files:**
- Modify: `app/cards/service.py` (`send_card`)
- Test: `tests/e2e/test_vocab_e2e.py`

**Interfaces:**
- Consumes: `send_vocab_dms` from Task 6; `Card` model; `_attendee_profiles` (existing).
- Produces: `send_card` is idempotent (guard by `Card.meeting_id`) and sends per-level vocab DMs after the group card.

- [ ] **Step 1: Write the failing e2e test**

Create `tests/e2e/test_vocab_e2e.py`:

```python
# tests/e2e/test_vocab_e2e.py
"""E2E: карточка + персональная лексика в личку, идемпотентность send_card."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.cards.seed import ensure_seeded
from app.cards.service import send_card
from app.models import Config, MeetingInstance, PollSlot, PollVote
from app.services.onboarding import get_or_create_profile
from app.services.weekly_poll import submit_poll

pytestmark = pytest.mark.e2e

FORM_1500 = {"day": {"stringInputs": {"value": ["0"]}}, "time": {"stringInputs": {"value": ["15:00"]}}}


async def test_send_card_is_idempotent_and_sends_vocab(db, today_poll, monkeypatch):
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "app.services.chat_sender.send_message",
        lambda space, text="", cards_v2=None, cards=None: sent.append((space, text)),
    )

    p = await get_or_create_profile(db, "users/e2e_vocab", email="v@x.com", chat_space_id="spaces/dm-v")
    p.english_level = "B1"
    await submit_poll(db, p, FORM_1500)

    voted_slot = (
        await db.execute(
            select(PollSlot)
            .join(PollVote, PollVote.poll_slot_id == PollSlot.id)
            .where(PollVote.profile_id == p.id)
        )
    ).scalar_one()

    meeting = MeetingInstance(
        poll_id=today_poll.id,
        selected_slot_id=voted_slot.id,
        scheduled_start=datetime.now(timezone.utc) + timedelta(hours=2),
        scheduled_end=datetime.now(timezone.utc) + timedelta(hours=3),
        location="Online (Meet)",
        status="scheduled",
    )
    db.add(meeting)
    await db.flush()
    await db.refresh(meeting)

    db.add(Config(key="space_id", value="spaces/group"))
    await ensure_seeded(db)
    await db.commit()

    # Первый вызов: карточка в группу + лексика в личку.
    await send_card(str(meeting.id))
    group = [s for s in sent if s[0] == "spaces/group"]
    dm = [s for s in sent if s[0] == "users/e2e_vocab"]
    assert len(group) == 1
    assert len(dm) == 1

    # Второй вызов: guard по Card.meeting_id — ничего не шлём.
    sent.clear()
    await send_card(str(meeting.id))
    assert sent == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe -m pytest tests/e2e/test_vocab_e2e.py -m e2e -q`
Expected: FAIL — second `send_card` still sends a group card (no idempotency guard yet), so `assert sent == []` fails (there is 1 group send).

- [ ] **Step 3: Add the idempotency guard + vocab hook**

In `app/cards/service.py`, in `send_card`, add the guard after the status check and before reading `space_id`:

```python
        existing = (
            await db.execute(select(Card).where(Card.meeting_id == meeting.id))
        ).scalars().first()
        if existing is not None:
            logger.info("card_skip_exists instance=%s", instance_id)
            return
```

And after the group card is sent (`logger.info("card_sent instance=%s type=%s", ...)`), append the vocab dispatch:

```python
        # Персональная лексика в личку участникам (по уровню).
        from app.services.vocab import send_vocab_dms

        profiles = await _attendee_profiles(db, meeting)
        topic = str((content.get("main_content") or {}).get("topic") or "today's topic")
        await send_vocab_dms(db, meeting, topic, profiles)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./venv/Scripts/python.exe -m pytest tests/e2e/test_vocab_e2e.py -m e2e -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add app/cards/service.py tests/e2e/test_vocab_e2e.py
git commit -m "feat(cards): send per-level vocab DMs + make send_card idempotent"
```

---

## Final verification

- [ ] Run the full unit suite (no DB): `./venv/Scripts/python.exe -m pytest tests -m "not e2e" -q`
- [ ] Run the full e2e suite (DB required): `./venv/Scripts/python.exe -m pytest tests/e2e -m e2e -q`
- [ ] Manually smoke-test the live flow: `/level` in DM → pick level → `scripts/backfill_levels.py` → `send_questions_now` → poll → `finalize_day_now` → `send_card_now` (verify both the group card and the vocab DM).
