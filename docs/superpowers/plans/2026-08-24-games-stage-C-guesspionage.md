# Активности — Этап C: Guesspionage English — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Игра «угадай процент»: один вопрос за запуск, называющий пишет число в личку, бот оглашает его в группе, остальные голосуют «выше/ниже», бот открывает ответ и начисляет очки.

**Architecture:** `app/services/games/guesspionage.py` (вопросы, карточки, подсчёт, оркестрация). Вебхук `app/api/google_chat.py` добавляет ветки `submit_guesspionage_guess` и `guesspionage_higher_lower` и подключает `start_guesspionage` в диспетчер `_start_session_game`. Очки через `award_points` (Этап A).

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy 2 async, Google Chat add-on + classic webhook, pytest.

**Spec:** `docs/superpowers/specs/2026-08-24-games-stage-C-guesspionage-design.md`

## Global Constraints

- Вопросы+проценты захардкожены: `GUESS_QUESTIONS: list[tuple[str, int]]`.
- Один раунд за один `/guesspionage` (без ротации `question_index`).
- Называющий пишет процент в личку (карточка с `textInput`), остальные голосуют кнопками в группе.
- Бот оглашает число называющего группе ПЕРЕД голосованием — иначе «выше/ниже» сравнивать не с чем.
- Очки: называющий ±5% → 3, ±10% → 2, иначе 1; остальные +1 за верное «выше/ниже» (нулевые очки не пишем — в БД стоит `points != 0`).
- Подсчёт автоматически, когда проголосовали все, кроме называющего.
- Карточка-догадка (в личке) несёт в параметрах `space` (имя группы), чтобы по клику в личке найти сессию, завязанную на группу.
- Проактивная отправка в группу (оглашение догадки) идёт через `chat_sender.send_message`, обёрнута в try/except (в e2e падает молча — это ожидаемо).
- Комментарии в коде на русском, названия и строки в коде — на английском.

## File Structure

- Create `app/services/games/guesspionage.py` — `GUESS_QUESTIONS`, `score_round`, карточки, `start_guesspionage`/`submit_guess`/`vote`.
- Modify `app/api/google_chat.py` — `_normalize_params`, ветки сабмита/голосования, ветка guesspionage в `_start_session_game`.
- Test `tests/test_guesspionage_units.py` — юнит подсчёта и карточек.
- Test `tests/e2e/test_games_guesspionage.py` — e2e полного раунда.

---

### Task 1: Вопросы, подсчёт, карточки

**Files:**
- Create: `app/services/games/guesspionage.py`
- Test: `tests/test_guesspionage_units.py`

**Interfaces:**
- Consumes: `parse_form_inputs` (app/services/form_parsing.py), `send_message` (app/messaging.py), `MessagePayload` (app/schemas.py), `GameManager` (Этап A), `award_points` (Этап A), `get_or_create_profile` (app/services/onboarding.py).
- Produces:
  - `GUESS_QUESTIONS: list[tuple[str, int]]`
  - `score_round(true_pct: int, guess: int, higher: set[str], lower: set[str], guesser: str) -> dict[str, int]`
  - `build_guess_card(question: str, action_url: str, space_name: str) -> dict`
  - `build_higher_lower_card(question: str, guess: int, action_url: str) -> dict`

- [ ] **Step 1: Написать падающий тест**

`tests/test_guesspionage_units.py`:

```python
# tests/test_guesspionage_units.py
from app.services.games.guesspionage import (
    GUESS_QUESTIONS,
    build_guess_card,
    build_higher_lower_card,
    score_round,
)


def test_questions_non_empty_and_valid_percents():
    assert len(GUESS_QUESTIONS) >= 1
    for _, pct in GUESS_QUESTIONS:
        assert 0 <= pct <= 100


def test_score_round_close_guesser_and_higher_win():
    # true=70, guess=60 → |60-70|=10 → 2; higher угадал (60 < 70)
    assert score_round(70, 60, higher={"a"}, lower={"b"}, guesser="g") == {"g": 2, "a": 1}


def test_score_round_very_close_guesser_and_lower_win():
    # true=70, guess=75 → |75-70|=5 → 3; lower угадал (75 > 70)
    assert score_round(70, 75, higher={"a"}, lower={"b"}, guesser="g") == {"g": 3, "b": 1}


def test_score_round_far_guesser():
    # true=70, guess=20 → 1; higher угадал
    assert score_round(70, 20, higher={"a"}, lower={"b"}, guesser="g") == {"g": 1, "a": 1}


def test_score_round_exact_guess_no_direction_points():
    # guess == true → направление не угадывает никто
    assert score_round(70, 70, higher={"a"}, lower={"b"}, guesser="g") == {"g": 3}


def test_build_higher_lower_card_buttons_and_choices():
    card = build_higher_lower_card("Q?", 60, "https://x/hook")
    buttons = card["cardsV2"][0]["card"]["sections"][0]["widgets"][0]["buttonList"]["buttons"]
    assert [b["text"] for b in buttons] == ["Выше ⬆️", "Ниже ⬇️"]
    choices = [b["onClick"]["action"]["parameters"][1]["value"] for b in buttons]
    assert choices == ["higher", "lower"]


def test_build_guess_card_has_input_and_space_param():
    card = build_guess_card("Q?", "https://x/hook", "spaces/grp")
    input_widget = card["cardsV2"][0]["card"]["sections"][0]["widgets"][0]
    assert input_widget["textInput"]["name"] == "guess"
    button = card["cardsV2"][0]["card"]["sections"][1]["widgets"][0]["buttonList"]["buttons"][0]
    params = {p["key"]: p["value"] for p in button["onClick"]["action"]["parameters"]}
    assert params["method"] == "submit_guesspionage_guess"
    assert params["space"] == "spaces/grp"
```

- [ ] **Step 2: Запустить тест — должен упасть**

Run: `pytest tests/test_guesspionage_units.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.games.guesspionage'`.

- [ ] **Step 3: Реализовать модуль**

`app/services/games/guesspionage.py`:

```python
# app/services/games/guesspionage.py
"""Guesspionage: угадай процент. Вопрос → число называющего → «выше/ниже» → очки."""
import logging

from app.messaging import send_message as send_dm
from app.schemas import MessagePayload
from app.services.chat_sender import send_message as send_to_space
from app.services.form_parsing import parse_form_inputs
from app.services.games.scores import award_points
from app.services.games.session import GameManager
from app.services.onboarding import get_or_create_profile

logger = logging.getLogger(__name__)

GUESS_QUESTIONS: list[tuple[str, int]] = [
    ("What percentage of people have peed in a shower?", 70),
    ("What percentage of people wear socks when they sleep?", 16),
    ("What percentage of people have Googled themselves?", 65),
    ("What percentage of people prefer smooth peanut butter to crunchy?", 62),
    ("What percentage of people believe there are aliens?", 85),
]


def score_round(true_pct: int, guess: int, higher: set[str], lower: set[str], guesser: str) -> dict[str, int]:
    """Очки за раунд: {user_id: positive_points}.

    Называющий — по близости (≤5 → 3, ≤10 → 2, иначе 1); остальные +1 за верное направление.
    """
    result: dict[str, int] = {}
    diff = abs(guess - true_pct)
    result[guesser] = 3 if diff <= 5 else (2 if diff <= 10 else 1)
    for voter in higher:
        if guess < true_pct:
            result[voter] = 1
    for voter in lower:
        if guess > true_pct:
            result[voter] = 1
    return result


def build_guess_card(question: str, action_url: str, space_name: str) -> dict:
    """Карточка для называющего (в личку): поле процента + кнопка «Отправить».

    В параметрах кнопки — space_name группы, чтобы по клику в личке найти сессию.
    """
    return {
        "cardsV2": [
            {
                "cardId": "guesspionage_guess",
                "card": {
                    "header": {"title": "Твой процент", "subtitle": question},
                    "sections": [
                        {"widgets": [{"textInput": {"name": "guess", "label": "Твой процент (0–100)"}}]},
                        {
                            "widgets": [
                                {
                                    "buttonList": {
                                        "buttons": [
                                            {
                                                "text": "Отправить",
                                                "onClick": {
                                                    "action": {
                                                        "function": action_url,
                                                        "parameters": [
                                                            {"key": "method", "value": "submit_guesspionage_guess"},
                                                            {"key": "space", "value": space_name},
                                                        ],
                                                    }
                                                },
                                            }
                                        ]
                                    }
                                }
                            ]
                        },
                    ],
                },
            }
        ]
    }


def build_higher_lower_card(question: str, guess: int, action_url: str) -> dict:
    """Карточка «выше/ниже» для группы."""
    return {
        "cardsV2": [
            {
                "cardId": "guesspionage_vote",
                "card": {
                    "header": {
                        "title": question,
                        "subtitle": f"Называющий считает: {guess}%. Правда выше или ниже?",
                    },
                    "sections": [
                        {
                            "widgets": [
                                {
                                    "buttonList": {
                                        "buttons": [
                                            {
                                                "text": "Выше ⬆️",
                                                "onClick": {
                                                    "action": {
                                                        "function": action_url,
                                                        "parameters": [
                                                            {"key": "method", "value": "guesspionage_higher_lower"},
                                                            {"key": "choice", "value": "higher"},
                                                        ],
                                                    }
                                                },
                                            },
                                            {
                                                "text": "Ниже ⬇️",
                                                "onClick": {
                                                    "action": {
                                                        "function": action_url,
                                                        "parameters": [
                                                            {"key": "method", "value": "guesspionage_higher_lower"},
                                                            {"key": "choice", "value": "lower"},
                                                        ],
                                                    }
                                                },
                                            },
                                        ]
                                    }
                                }
                            ]
                        }
                    ],
                },
            }
        ]
    }


def start_guesspionage(session, space_name: str, action_url: str) -> dict:
    """Запустить раунд: взять первый вопрос, назначить называющего, отправить карточку в личку."""
    question, true_pct = GUESS_QUESTIONS[0]
    guesser = session.players[0]
    session.state.update(
        {
            "question": question,
            "true_pct": true_pct,
            "guesser": guesser,
            "guess": None,
            "higher": set(),
            "lower": set(),
        }
    )
    send_dm(
        guesser,
        MessagePayload(
            text="Твой ход — напиши процент 👇",
            card=build_guess_card(question, action_url, space_name),
        ),
    )
    return {"text": f"{question}\n\nНазывающий, напиши свой процент — карточка у тебя в личке 🤫"}


def submit_guess(session, user_id: str, form_inputs: dict, space_name: str, action_url: str) -> dict:
    """Принять число называющего и огласить его группе (карточка «выше/ниже»)."""
    values = parse_form_inputs(form_inputs).get("guess", [])
    if not values:
        return {"text": "Напиши число и нажми «Отправить»."}
    try:
        guess = int(values[0])
    except ValueError:
        return {"text": "Это не число — напиши процент цифрами (0–100)."}
    if not 0 <= guess <= 100:
        return {"text": "Процент должен быть от 0 до 100."}
    session.state["guess"] = guess
    card = build_higher_lower_card(session.state["question"], guess, action_url)
    try:
        send_to_space(space_name, text="Называющий написал свой процент. Голосуем!", cards_v2=card["cardsV2"])
    except Exception:
        logger.exception("guesspionage_reveal_failed")
    return {"text": "Принято! 🎯 Остальные уже голосуют «выше/ниже»."}


async def vote(db, session, user_id: str, choice: str, space_name: str) -> dict | None:
    """Записать голос; когда проголосовали все, кроме называющего, — подсчёт и очки."""
    state = session.state
    guesser = state["guesser"]
    if user_id == guesser:
        return {"text": "Называющий не голосует."}
    state["higher"].discard(user_id)
    state["lower"].discard(user_id)
    (state["higher"] if choice == "higher" else state["lower"]).add(user_id)
    voters = [p for p in session.players if p != guesser]
    if len(state["higher"]) + len(state["lower"]) < len(voters):
        return None  # ждём остальных

    score = score_round(state["true_pct"], state["guess"], state["higher"], state["lower"], guesser)
    for user, points in score.items():
        profile = await get_or_create_profile(db, workspace_user_id=user)
        await award_points(db, profile.id, points, "guesspionage")
    GameManager.end(space_name)
    lines = [f"{session.names.get(u, u)}: +{p}" for u, p in score.items()]
    return {"text": f"Правильный ответ: {state['true_pct']}%\n\n" + "\n".join(lines)}
```

- [ ] **Step 4: Запустить тест — должен пройти**

Run: `pytest tests/test_guesspionage_units.py -v`
Expected: PASS (7 тестов).

- [ ] **Step 5: Commit**

```bash
git add app/services/games/guesspionage.py tests/test_guesspionage_units.py
git commit -m "feat(games): add guesspionage questions, scoring and cards"
```

---

### Task 2: Вебхук сабмита и голосования

**Files:**
- Modify: `app/api/google_chat.py`
- Test: `tests/e2e/test_games_guesspionage.py`

**Interfaces:**
- Consumes: `GameManager`, `_addon_response`, `_extract_space_dict`, `_normalize_params` (ниже), `AsyncSessionLocal`.
- Produces: `_normalize_params(raw) -> dict[str, str]`, `_handle_guesspionage_submit_guess(user, form_inputs, params) -> JSONResponse`, `_handle_guesspionage_vote(user, space, params) -> JSONResponse` (async).

- [ ] **Step 1: Написать падающий e2e-тест**

`tests/e2e/test_games_guesspionage.py`:

```python
# tests/e2e/test_games_guesspionage.py
"""E2E полного раунда Guesspionage: старт → догадка → голос → очки в БД."""
import pytest
from sqlalchemy import select

from app.models import LeaderboardLedger, Profile

pytestmark = pytest.mark.e2e


def _message(user_id: str, text: str, space: str) -> dict:
    return {
        "type": "MESSAGE",
        "user": {"name": user_id, "displayName": "E2E"},
        "message": {"text": text},
        "space": {"name": space, "type": "ROOM"},
    }


def _card_click(user_id: str, method: str, space: str, params: list | None = None, form_inputs: dict | None = None) -> dict:
    action_params = [{"key": "method", "value": method}] + (params or [])
    return {
        "type": "CARD_CLICKED",
        "user": {"name": user_id, "displayName": "E2E"},
        "space": {"name": space},
        "action": {"function": "https://x/hook", "parameters": action_params},
        "common": {"formInputs": form_inputs or {}},
    }


def _resp_text(resp) -> str:
    return resp.json()["hostAppDataAction"]["chatDataAction"]["createMessageAction"]["message"].get("text", "")


async def test_guesspionage_full_round(client, db):
    space = "spaces/e2e_gp"
    guesser = "users/e2e_gp_guesser"
    voter = "users/e2e_gp_voter"

    # 1. старт
    resp = await client.post("/webhooks/google-chat", json=_message(guesser, "/guesspionage", space))
    assert "cardsV2" in resp.json()

    # 2. двое в деле
    await client.post("/webhooks/google-chat", json=_card_click(guesser, "join_game", space))
    await client.post("/webhooks/google-chat", json=_card_click(voter, "join_game", space))

    # 3. начать
    resp = await client.post("/webhooks/google-chat", json=_card_click(guesser, "start_game", space))
    assert "percentage" in _resp_text(resp)

    # 4. называющий шлёт 60 (в личке, параметр space = группа)
    guess_inputs = {"guess": {"stringInputs": {"value": ["60"]}}}
    resp = await client.post(
        "/webhooks/google-chat",
        json=_card_click(guesser, "submit_guesspionage_guess", space, params=[{"key": "space", "value": space}], form_inputs=guess_inputs),
    )
    assert "Принято" in _resp_text(resp)

    # 5. единственный не-называющий голосует «выше» → раунд завершается
    resp = await client.post(
        "/webhooks/google-chat",
        json=_card_click(voter, "guesspionage_higher_lower", space, params=[{"key": "choice", "value": "higher"}]),
    )
    assert "Правильный ответ: 70%" in _resp_text(resp)

    # 6. очки в БД: называющий +2 (|60-70|=10), голосовавший +1 (60 < 70, higher верно)
    rows = (
        await db.execute(
            select(LeaderboardLedger)
            .join(Profile, LeaderboardLedger.profile_id == Profile.id)
            .where(Profile.workspace_user_id.in_([guesser, voter]))
        )
    ).scalars().all()
    points_by_user = {r.profile_id: r.points for r in rows}
    assert sorted(points_by_user.values()) == [1, 2]
    assert all(r.event_type == "bonus" and r.reason == "guesspionage" for r in rows)
```

- [ ] **Step 2: Запустить тест — должен упасть**

Run (нужен поднятый бот и Postgres):
```bash
$env:SKIP_JWT_VALIDATION="true"; uvicorn app.main:app --port 8000
pytest -m e2e tests/e2e/test_games_guesspionage.py -v
```
Expected: FAIL — методы `submit_guesspionage_guess`/`guesspionage_higher_lower` не обрабатываются.

- [ ] **Step 3: Реализовать обработку в `google_chat.py`**

Добавить хелпер нормализации параметров (рядом с другими хелперами, например после `_game_command_response`):

```python
def _normalize_params(raw) -> dict[str, str]:
    """parameters из события в плоский {key: value} (понимает list[{key,value}] и dict)."""
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items() if k and k != "__action_method_name__"}
    if isinstance(raw, list):
        return {str(p.get("key")): str(p.get("value")) for p in raw if isinstance(p, dict) and p.get("key")}
    return {}
```

Добавить обработчики (после `_handle_start_game`):

```python
def _handle_guesspionage_submit_guess(user: dict, form_inputs: dict, params: dict) -> JSONResponse:
    """Называющий прислал число (из лички): принять и огласить группе."""
    from app.services.games.guesspionage import submit_guess

    space_name = params.get("space", "")
    session = GameManager.get(space_name)
    if session is None:
        return JSONResponse(content={})
    result = submit_guess(session, user.get("name", ""), form_inputs, space_name, settings.chat_app_audience)
    return _addon_response(result)


async def _handle_guesspionage_vote(user: dict, space: dict, params: dict) -> JSONResponse:
    """Голос «выше/ниже» из группы."""
    from app.services.games.guesspionage import vote as guesspionage_vote

    space_name = space.get("name", "")
    session = GameManager.get(space_name)
    if session is None:
        return JSONResponse(content={})
    choice = params.get("choice", "higher")
    async with AsyncSessionLocal() as db:
        result = await guesspionage_vote(db, session, user.get("name", ""), choice, space_name)
    if result is None:
        return JSONResponse(content={})
    return _addon_response(result)
```

Подключить игру в диспетчер `_start_session_game` (заменить тело функции):

```python
def _start_session_game(session, space_name: str, action_url: str) -> dict:
    if session.game == "guesspionage":
        from app.services.games.guesspionage import start_guesspionage

        return start_guesspionage(session, space_name, action_url)
    return {"text": "Механика игры ещё не подключена."}
```

Вставить ветки в **add-on** диспетчер кнопок (после `if method == "start_game":`, перед `logger.info(...)`):

```python
            if method == "submit_guesspionage_guess":
                return _handle_guesspionage_submit_guess(
                    chat_data.get("user", {}),
                    common.get("formInputs", {}),
                    _normalize_params(common.get("parameters")),
                )
            if method == "guesspionage_higher_lower":
                return await _handle_guesspionage_vote(
                    chat_data.get("user", {}),
                    _extract_space_dict(chat_data),
                    _normalize_params(common.get("parameters")),
                )
```

Вставить ветки в **classic** `CARD_CLICKED` (после `if method == "start_game":`, перед `logger.info(...)`):

```python
        if method == "submit_guesspionage_guess":
            form_inputs = event.get("common", {}).get("formInputs", {})
            return _handle_guesspionage_submit_guess(
                event.get("user", {}), form_inputs, _normalize_params(action.get("parameters"))
            )
        if method == "guesspionage_higher_lower":
            return await _handle_guesspionage_vote(
                event.get("user", {}), event.get("space", {}), _normalize_params(action.get("parameters"))
            )
```

- [ ] **Step 4: Запустить тест — должен пройти**

Run:
```bash
pytest -m e2e tests/e2e/test_games_guesspionage.py -v
```
Expected: PASS (1 тест). Плюс не должны сломаться юнит-тесты: `pytest tests/test_guesspionage_units.py -v`.

- [ ] **Step 5: Commit**

```bash
git add app/api/google_chat.py tests/e2e/test_games_guesspionage.py
git commit -m "feat(games): wire guesspionage submit and higher/lower voting"
```

---

## Self-Review

- **Spec coverage:** вопросы (Task 1), карточка-догадка в личку (Task 1), голос выше/ниже (Task 1 карточка + Task 2 ветка), подсчёт и очки (Task 1 `score_round` + Task 2 `vote`), оглашение догадки (Task 2 `submit_guess`). Ротация `question_index` из спеки выкинута (договорённость «один вопрос за запуск»).
- **Placeholder scan:** нет TBD/TODO; каждая функция имеет тело.
- **Type consistency:** `score_round(true_pct, guess, higher, lower, guesser)`, `build_guess_card(question, action_url, space_name)`, `submit_guess(session, user_id, form_inputs, space_name, action_url)`, `vote(db, session, user_id, choice, space_name)` — используются в Task 2 с теми же именами и порядком аргументов, что определены в Task 1. `space`-параметр в карточке догадки (Task 1) совпадает с чтением `params["space"]` в Task 2.
