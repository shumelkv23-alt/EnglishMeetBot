# Week Theme, Questions, Past-Day Block, Card Plan — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an automatic weekly theme that drives both the weekly questions and the lesson card; make weekly questions non-repeating and theme-based; forbid voting for past days; and render the card as a fixed 4-phase lesson plan.

**Architecture:** A deterministic `week_theme(week_start)` (no storage) is the shared spine — computed by the Sunday questions and again later by the card, so they agree. The personal question gains a `theme` input; the common question rotates through an expanded bank. The poll rejects past days in both `submit_poll` and `build_weekly_poll_card`. The card content gains a filled `stretch_challenge` and the renderer lays out 4 phases with time hints.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy async (PostgreSQL), Google Chat cardsV2, OpenRouter (`llm_model`) for weekly questions, Azati (`llm_games_model`) for card content, pytest.

**Spec:** `docs/superpowers/specs/2026-08-26-week-theme-questions-poll-cardplan-design.md`

## Global Constraints

- Python 3.11+, PEP 8 + type hints; docstrings; comments in Russian.
- Run tests with `./venv/Scripts/python.exe -m pytest <path> -q` (Windows).
- e2e tests need PostgreSQL + `-m e2e`.
- LLM keys from `.env`; never commit `.env` / `sa-key.json` or their values.
- CEFR codes `A1..C2` (from `app/services/levels.py`).
- Deterministic logic keyed by `week_start` (ISO week) — no new DB columns/migrations.
- Branch `games-kirill`; commit after each task.

---

### Task 1: `week_theme.py` — deterministic weekly theme

**Files:**
- Create: `app/services/week_theme.py`
- Test: `tests/test_week_theme_units.py`

**Interfaces:**
- Produces: `THEME_BANK: list[str]`, `week_theme(week_start: date) -> str`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_week_theme_units.py`:

```python
# tests/test_week_theme_units.py
from datetime import date, timedelta

from app.services.week_theme import THEME_BANK, week_theme


def test_week_theme_returns_bank_entry():
    assert week_theme(date(2026, 8, 24)) in THEME_BANK


def test_week_theme_is_deterministic():
    assert week_theme(date(2026, 8, 24)) == week_theme(date(2026, 8, 24))


def test_week_theme_no_repeat_within_bank():
    # 24 последовательные недели -> 24 разных темы
    monday = date(2026, 1, 5)  # понедельник
    seen = [week_theme(monday + timedelta(weeks=w)) for w in range(len(THEME_BANK))]
    assert len(set(seen)) == len(THEME_BANK)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe -m pytest tests/test_week_theme_units.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.week_theme'`.

- [ ] **Step 3: Write minimal implementation**

Create `app/services/week_theme.py`:

```python
# app/services/week_theme.py
"""Недельная тема: детерминированная ротация курируемых тем.

Единый источник темы недели для вопросов (воскресенье) и карточки занятия
(позже в ту же неделю). Детерминирована по понедельнику недели — без хранения,
без повтора в пределах банка.
"""
from datetime import date

THEME_BANK: list[str] = [
    "Travel and places", "Food and cooking", "Work and career",
    "Technology and AI", "Movies and TV", "Books and reading",
    "Music and concerts", "Hobbies and free time", "Sports and fitness",
    "Friends and relationships", "Family and traditions", "Money and habits",
    "Health and routines", "Learning and education", "Nature and the outdoors",
    "Cities and home", "Dreams and ambitions", "Holidays and festivals",
    "Shopping and brands", "Social media and screens", "Languages and culture",
    "Time and productivity", "Seasons and weather", "Food vs. home cooking",
]


def week_theme(week_start: date) -> str:
    """Тема недели: банк по ISO-номеру недели (без повтора в пределах банка)."""
    return THEME_BANK[week_start.isocalendar().week % len(THEME_BANK)]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./venv/Scripts/python.exe -m pytest tests/test_week_theme_units.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add app/services/week_theme.py tests/test_week_theme_units.py
git commit -m "feat(theme): deterministic weekly theme rotation"
```

---

### Task 2: Weekly questions by theme + non-repeating common

**Files:**
- Modify: `app/services/llm_questions.py` (add `theme` param)
- Modify: `app/services/question_bank.py` (expand `BANK`)
- Modify: `app/services/weekly_questions.py` (thread theme)
- Test: `tests/test_weekly_questions_theme.py`

**Interfaces:**
- Consumes: `week_theme` (Task 1).
- Produces: `generate_personal_question(interests, *, level="A2", avoid=None, theme=None)`; `questions_for_profile(interests, week_start, level, avoid=None, theme=None)`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_weekly_questions_theme.py`:

```python
# tests/test_weekly_questions_theme.py
import json

from app.services.llm_questions import generate_personal_question
from app.services.week_theme import week_theme
from app.services.weekly_questions import questions_for_profile


def test_generate_personal_question_sends_theme(monkeypatch):
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
    generate_personal_question(["food"], level="B1", theme="Travel and places", api_key="k", model="m")
    user_prompt = captured["payload"]["messages"][1]["content"]
    assert "Travel and places" in user_prompt


def test_questions_for_profile_passes_theme(monkeypatch):
    from app.services import weekly_questions as wq

    captured = {}

    def fake_generate(interests, level="A2", avoid=None, theme=None):
        captured["theme"] = theme
        return "personal?"

    monkeypatch.setattr(wq, "generate_personal_question", fake_generate)
    wq.questions_for_profile(["food"], wq.current_week_start(), "B1", avoid=[], theme="Travel")
    assert captured["theme"] == "Travel"


def test_bank_is_large_enough_for_nonrepeat():
    from app.services.question_bank import BANK

    assert len(BANK) >= 40
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe -m pytest tests/test_weekly_questions_theme.py -q`
Expected: FAIL — `test_generate_personal_question_sends_theme` (theme not in prompt) and `test_bank_is_large_enough` (bank still 20).

- [ ] **Step 3: Add `theme` to the LLM prompt**

In `app/services/llm_questions.py`, add `theme: str | None = None` to `generate_personal_question` signature (after `level`), and build the user prompt with the theme:

```python
    user_prompt = (
        f"The person's interests: {interests_text}. "
    )
    if theme:
        user_prompt += f"This week's meetup theme: {theme}. "
    user_prompt += (
        "DON'T fixate on interests — ask an easy question on ANY lively everyday topic "
        "(food, travel, habits, music, funny moments, hobbies), only occasionally touching on interests or the theme. "
        "Pick a new topic each time."
    )
```

(Replace the existing `user_prompt = (...)` block in `generate_personal_question`.)

- [ ] **Step 4: Expand the common question bank**

In `app/services/question_bank.py`, append 20+ questions to `BANK` (to total ≥40). Add after the existing 20 entries:

```python
    "What's a small thing that always improves your day?",
    "Which app do you use the most and why?",
    "What's something you changed your mind about recently?",
    "Name a food you disliked as a kid but like now.",
    "What's a place you go to clear your head?",
    "If you could instantly learn one skill, which and why?",
    "What's the best purchase you made this year?",
    "Name a tradition from your family you'd like to keep.",
    "What's a film you can rewatch many times?",
    "What would your ideal Sunday look like?",
    "What's something you're looking forward to?",
    "Name a habit you want to build or break.",
    "What's the most useful advice you ever got?",
    "If you could visit one country next month, which?",
    "What's a song that instantly lifts your mood?",
    "Name a small risk that paid off for you.",
    "What's something people often misunderstand about you?",
    "What's a topic you could give a short talk on?",
    "Name a season you love and why.",
    "What's something you'd like to try but haven't yet?",
    "What's a compliment you still remember?",
    "If your day had 25 hours, what would you do with the extra hour?",
    "What's a game you're good at or enjoy?",
    "Name a skill that helped you most at work.",
```

- [ ] **Step 5: Thread theme through `questions_for_profile`**

In `app/services/weekly_questions.py`, change `questions_for_profile` to accept and pass `theme`:

```python
def questions_for_profile(
    interests: list[str] | None, week_start: date, level: str,
    avoid: list[str] | None = None, theme: str | None = None,
) -> tuple[str, str]:
    bank = bank_questions_for(week_start)
    personal = generate_personal_question(interests or [], level=level, avoid=avoid, theme=theme)
    if personal is None:
        personal = bank[1]
    return personal, bank[0]
```

In `send_weekly_questions`, compute the theme and pass it (add after `week_start = current_week_start()`):

```python
    from app.services.week_theme import week_theme

    theme = week_theme(week_start)
```

and change the call:

```python
        personal_q, bank_q = await asyncio.to_thread(
            questions_for_profile, p.interests, week_start, p.english_level or "A2", past, theme
        )
```

- [ ] **Step 5b: Update existing `tests/test_weekly_questions_units.py` lambdas**

The `generate_personal_question` monkeypatch lambdas in `tests/test_weekly_questions_units.py` now need `theme=None`:

Replace `lambda interests, level="A2", avoid=None: "Твой персональный вопрос"` → `lambda interests, level="A2", avoid=None, theme=None: "Твой персональный вопрос"`

Replace `lambda interests, level="A2", avoid=None: None` → `lambda interests, level="A2", avoid=None, theme=None: None`

- [ ] **Step 6: Run tests to verify they pass**

Run: `./venv/Scripts/python.exe -m pytest tests/test_weekly_questions_theme.py tests/test_weekly_questions_units.py tests/test_llm_questions_level.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/services/llm_questions.py app/services/question_bank.py app/services/weekly_questions.py tests/test_weekly_questions_theme.py
git commit -m "feat(questions): theme-based personal question + non-repeating bank"
```

---

### Task 3: Forbid voting for past days

**Files:**
- Modify: `app/services/weekly_poll.py` (`submit_poll`, `build_weekly_poll_card`)
- Test: `tests/test_weekly_poll_past_day.py`

**Interfaces:**
- Consumes: `get_settings().app_timezone`.
- Produces: `build_weekly_poll_card(days, times, action_url, counts=None, today_dow=None)`; `submit_poll` rejects `past_day`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_weekly_poll_past_day.py`:

```python
# tests/test_weekly_poll_past_day.py
from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.weekly_poll import build_weekly_poll_card


def test_build_card_hides_buttons_for_past_days():
    # сегодня — среда (2); Пн/Вт (0,1) — прошедшие
    card = build_weekly_poll_card([0, 1, 2, 3], ["15:00"], "aud", counts={}, today_dow=2)
    sections = card["cardsV2"][0]["card"]["sections"]
    # прошедшие дни без кнопок
    assert not sections[0].get("widgets")[0].get("buttonList", {}).get("buttons")
    assert not sections[1].get("widgets")[0].get("buttonList", {}).get("buttons")
    # среда и далее — с кнопками
    assert sections[2]["widgets"][0]["buttonList"]["buttons"]


def test_build_card_today_defaults_to_app_timezone():
    today = datetime.now(ZoneInfo("Europe/Minsk")).weekday()
    card = build_weekly_poll_card([0, 1, 2, 3, 4, 5, 6], ["15:00"], "aud")
    sections = card["cardsV2"][0]["card"]["sections"]
    for i, s in enumerate(sections):
        buttons = s["widgets"][0].get("buttonList", {}).get("buttons")
        if i < today:
            assert not buttons  # прошедшие — без кнопок
        else:
            assert buttons
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe -m pytest tests/test_weekly_poll_past_day.py -q`
Expected: FAIL — `build_weekly_poll_card` doesn't accept `today_dow` / doesn't hide buttons.

- [ ] **Step 3: Update `build_weekly_poll_card`**

In `app/services/weekly_poll.py`, add `today_dow` param and skip buttons for past days:

```python
def build_weekly_poll_card(
    days: list[int], times: list[str], action_url: str,
    counts: dict[tuple[int, str], int] | None = None, today_dow: int | None = None,
) -> dict:
    counts = counts or {}
    if today_dow is None:
        today_dow = datetime.now(ZoneInfo(get_settings().app_timezone)).weekday()
    sections = []
    for day in days:
        day_name = DAYS[day]
        total = sum(counts.get((day, t), 0) for t in times)
        if day < today_dow:
            sections.append({
                "header": f"{day_name} · passed",
                "widgets": [{"textParagraph": {"text": "This day has passed"}}],
            })
            continue
        buttons = []
        for t in times:
            c = counts.get((day, t), 0)
            buttons.append({
                "text": f"{t} ({c})",
                "onClick": {"action": {
                    "function": action_url or "submit_daily_poll",
                    "parameters": [
                        {"key": "method", "value": "submit_daily_poll"},
                        {"key": "day", "value": str(day)},
                        {"key": "time", "value": t},
                    ],
                }},
            })
        sections.append({
            "header": f"{day_name} · {total} voted",
            "widgets": [{"buttonList": {"buttons": buttons}}],
        })
    return {
        "cardsV2": [{
            "cardId": "weeklyPoll",
            "card": {
                "header": {"title": "When can you meet this week? 🗓️",
                           "subtitle": "Pick ONE day and time"},
                "sections": sections,
            },
        }]
    }
```

- [ ] **Step 4: Reject past day in `submit_poll`**

In `app/services/weekly_poll.py`, in `submit_poll`, after `day, choice = _normalize_submit(form_inputs)`:

```python
    today_dow = datetime.now(ZoneInfo(get_settings().app_timezone)).weekday()
    if day < today_dow:
        return {"ok": False, "reason": "past_day"}
```

(place before the existing `if day < 0 or not _is_valid_submit_time(choice):` check).

- [ ] **Step 5: Run tests to verify they pass**

Run: `./venv/Scripts/python.exe -m pytest tests/test_weekly_poll_past_day.py -q`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add app/services/weekly_poll.py tests/test_weekly_poll_past_day.py
git commit -m "feat(poll): block voting for past days"
```

---

### Task 4: Card as a 4-phase lesson plan (fill stretch_challenge)

**Files:**
- Modify: `app/cards/generator/template.py` (stretch + theme fallback)
- Modify: `app/cards/generator/llm.py` (stretch + theme)
- Modify: `app/cards/service.py` (`_assemble_card`, `build_card_message`, `generate_card_content`)
- Modify: `app/cards/validator.py` (`_gather_text` covers stretch)
- Test: `tests/test_cards_plan_units.py`

**Interfaces:**
- Consumes: `week_theme` (Task 1).
- Produces: `content["stretch_challenge"]` filled; `build_card_message` renders Warm-up/Main/Stretch/Wrap-up with time hints.

- [ ] **Step 1: Write the failing test**

Create `tests/test_cards_plan_units.py`:

```python
# tests/test_cards_plan_units.py
from app.cards.generator.template import build_template_content
from app.cards.service import build_card_message


def test_template_fills_stretch_challenge_for_all_types():
    from app.cards.catalog import CARD_TYPES

    for t in CARD_TYPES:
        content = build_template_content(t["name"], {}, "B1")
        assert content.get("stretch_challenge"), f"stretch missing for {t['name']}"


def test_build_card_message_renders_four_phases():
    content = build_template_content("topic", {}, "B1")
    content["stretch_challenge"] = "A harder question"
    card = build_card_message(content)
    s = str(card)
    assert "Warm-up" in s
    assert "Stretch" in s
    assert "Wrap-up" in s
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe -m pytest tests/test_cards_plan_units.py -q`
Expected: FAIL — `stretch_challenge` is missing (template doesn't set it).

- [ ] **Step 3: Fill `stretch_challenge` in the template**

In `app/cards/generator/template.py`, add a stretch-by-type map and use it in `build_template_content`:

```python
_STRETCH_BY_TYPE = {
    "topic": "Go deeper: argue the opposite side of your own answer for a minute.",
    "debate": "Switch sides and defend the position you disagree with.",
    "storytelling": "Add an unexpected plot twist to the story.",
    "would_you_rather": "Argue for the option you did NOT choose.",
    "roleplay": "Swap roles and replay the scene.",
    "culture": "Teach a phrase from your own language that has no English equivalent.",
    "hot_seat": "Ask the person in the hot seat one personal follow-up question.",
    "game_day": "Invent a quick rule variation for the game you just played.",
    "two_truths": "Invent a convincing lie about yourself and make the group guess.",
    "mystery": "Speculate on the weirdest possible answer to today's topic.",
    "news_reaction": "Predict how this news might look in ten years.",
    "time_capsule": "Write a one-sentence message your future self would understand.",
}
```

In `build_template_content`, add `"stretch_challenge"` to the returned dict:

```python
    return {
        "difficulty_level": difficulty,
        "warm_up": {"question": random.choice(_WARM_UP_POOL), "based_on_profile_field": None},
        "main_content": main,
        "vocab_box": _vocab_box(card_type_name, payload),
        "stretch_challenge": _STRETCH_BY_TYPE.get(card_type_name, _STRETCH_BY_TYPE["topic"]),
        "wrap_up_question": random.choice(_WRAP_UP_POOL),
    }
```

- [ ] **Step 4: Generate stretch + use theme in the LLM path**

In `app/cards/generator/llm.py`, add `theme: str | None = None` to `generate_llm_content`, include it in the user prompt, ask for `stretch_challenge`, and parse it:

- In the user content, after `Group level: {difficulty}.`, add (if theme): `This week's theme: {theme}. `
- In the "Return strict JSON" instruction, extend the shape to include `"stretch_challenge": "..."`.
- In parsing, add:

```python
    stretch = str(data.get("stretch_challenge") or "").strip()
```
- In the return dict, add `"stretch_challenge": stretch`.

- [ ] **Step 5: Assemble + render the 4-phase plan**

In `app/cards/service.py`:

1. `_assemble_card` — replace `"stretch_challenge": None` with `"stretch_challenge": content.get("stretch_challenge")`.
2. In `generate_card_content`, compute the theme and pass it:

```python
    from app.services.weekly_poll import week_monday
    from app.services.week_theme import week_theme

    theme = week_theme(week_monday(meeting.scheduled_start.date()))
```

then pass `theme=theme` to both `generate_llm_content` and (via fallback) `build_template_content`. After the LLM call, copy `stretch_challenge`:

```python
        if llm:
            content["main_content"]["topic"] = llm["topic"]
            content["main_content"]["sub_questions"] = llm["sub_questions"]
            content["vocab_box"] = llm["vocab_box"]
            content["stretch_challenge"] = llm.get("stretch_challenge") or content["stretch_challenge"]
            content["wrap_up_question"] = llm["wrap_up_question"]
            generated_by = "llm"
```

3. `build_card_message` — render the 4 phases. Add a `Stretch` section before `Wrap-up` (using the same decoratedText style as `warm_up`):

```python
    stretch = content.get("stretch_challenge")
    if stretch:
        sections.append({
            "header": "🚀 Stretch (~10 min)",
            "widgets": [{"decoratedText": {"text": stretch, "wrapText": True}}],
        })
```

and update existing section headers to carry time hints: `"🔥 Warm-up (~5 min)"`, and `"🧭 Wrap-up (~5 min)"`. (Main content sections stay as-is — their time is implied by the activity.)

- [ ] **Step 6: Cover stretch in the validator**

In `app/cards/validator.py`, in `_gather_text`, add:

```python
    parts.append(str(content.get("stretch_challenge") or ""))
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `./venv/Scripts/python.exe -m pytest tests/test_cards_plan_units.py tests/test_cards_units.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add app/cards/generator/template.py app/cards/generator/llm.py app/cards/service.py app/cards/validator.py tests/test_cards_plan_units.py
git commit -m "feat(cards): 4-phase lesson plan + theme-driven topic + stretch challenge"
```

---

## Final verification

- [ ] Unit suite: `./venv/Scripts/python.exe -m pytest tests -m "not e2e" -q`
- [ ] e2e suite (DB required): `./venv/Scripts/python.exe -m pytest tests/e2e -m e2e -q`
- [ ] Live smoke: run `send_questions_now` (questions reference the theme), `send_poll_now` (past days hidden), `send_card_now` (4-phase card with the week's theme).
