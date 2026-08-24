# Активности — Этап D: Шпион — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Игра «шпион»: рандомная тема + слово, тайный шпион, раздача слова в личку, голосование «кто шпион», очки.

**Architecture:** `app/services/games/spy.py` (банк слов, роли, карточки голосования, подсчёт, оркестрация). Вебхук `app/api/google_chat.py` добавляет ветки `spy_start_vote` и `spy_vote` и подключает `start_spy` в диспетчер `_start_session_game`. Очки через `award_points` (Этап A).

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy 2 async, Google Chat add-on + classic webhook, pytest.

**Spec:** `docs/superpowers/specs/2026-08-24-games-stage-D-spy-design.md`

## Global Constraints

- Слова захардкожены по темам: `WORD_BANK: dict[str, list[str]]`.
- Роли рандомны: `assign_roles` принимает опциональный `rng` для детерминированных тестов.
- Не-шпионам в личку — слово; шпиону — «Ты шпион 🤫» + тема.
- Голосование «кто шпион» — кнопки с именами (`method=spy_vote`, `target=<user_id>`).
- Очки: команда угадала шпиона (строго больше голосов, чем у любого другого) → каждый мирный +1; иначе шпион +3. Путь «шпион угадал слово» из спеки ВЫКИНУТ (договорённость).
- Подсчёт автоматически, когда проголосовали все игроки.
- Проактивная отправка ТОЛЬКО в личку (`messaging.send_message`, стаб-безопасно); сообщения в группу идут как ответ на клик (`_addon_response`).
- Комментарии в коде на русском, названия и строки в коде — на английском.

## File Structure

- Create `app/services/games/spy.py` — `WORD_BANK`, `assign_roles`, `score_spy`, карточки, `start_spy`/`vote`.
- Modify `app/api/google_chat.py` — ветки `spy_start_vote`/`spy_vote`, ветка spy в `_start_session_game`.
- Test `tests/test_spy_units.py` — юнит ролей/подсчёта/карточек.
- Test `tests/e2e/test_games_spy.py` — e2e полного раунда.

---

### Task 1: Банк слов, роли, подсчёт, карточки

**Files:**
- Create: `app/services/games/spy.py`
- Test: `tests/test_spy_units.py`

**Interfaces:**
- Consumes: `send_message` (app/messaging.py), `MessagePayload` (app/schemas.py), `GameManager` (Этап A), `award_points` (Этап A), `get_or_create_profile` (app/services/onboarding.py).
- Produces:
  - `WORD_BANK: dict[str, list[str]]`
  - `assign_roles(players: list[str], rng: random.Random | None = None) -> dict` (ключи `topic`, `word`, `spy`)
  - `score_spy(spy: str, votes: dict[str, str], players: list[str]) -> dict[str, int]`
  - `build_spy_vote_card(names: dict[str, str], players: list[str], action_url: str) -> dict`
  - `build_start_vote_card(topic: str, action_url: str) -> dict`

- [ ] **Step 1: Написать падающий тест**

`tests/test_spy_units.py`:

```python
# tests/test_spy_units.py
import random

from app.services.games.spy import (
    WORD_BANK,
    assign_roles,
    build_spy_vote_card,
    build_start_vote_card,
    score_spy,
)


def test_word_bank_non_empty():
    assert len(WORD_BANK) >= 1
    for topic, words in WORD_BANK.items():
        assert len(words) >= 1


def test_assign_roles_picks_valid_topic_word_and_spy():
    players = ["users/a", "users/b", "users/c"]
    roles = assign_roles(players, rng=random.Random(0))
    assert roles["topic"] in WORD_BANK
    assert roles["word"] in WORD_BANK[roles["topic"]]
    assert roles["spy"] in players


def test_score_spy_caught_gives_civilians_point():
    # шпион "s" набрал 2 голоса, у "x" — 1 → пойман
    votes = {"a": "s", "b": "s", "c": "x"}
    assert score_spy("s", votes, ["a", "b", "c", "s"]) == {"a": 1, "b": 1, "c": 1}


def test_score_spy_not_caught_gives_spy_points():
    votes = {"a": "x", "b": "x", "c": "y"}
    assert score_spy("s", votes, ["a", "b", "c", "s"]) == {"s": 3}


def test_score_spy_tie_not_caught():
    # шпион "s" и "x" делят голоса → ничья, шпион не пойман
    votes = {"a": "s", "b": "x"}
    assert score_spy("s", votes, ["a", "b", "s", "x"]) == {"s": 3}


def test_build_spy_vote_card_has_button_per_player():
    names = {"users/a": "Alice", "users/b": "Bob"}
    card = build_spy_vote_card(names, ["users/a", "users/b"], "https://x/hook")
    buttons = card["cardsV2"][0]["card"]["sections"][0]["widgets"][0]["buttonList"]["buttons"]
    assert [b["text"] for b in buttons] == ["Alice", "Bob"]
    targets = [b["onClick"]["action"]["parameters"][1]["value"] for b in buttons]
    assert targets == ["users/a", "users/b"]


def test_build_start_vote_card_has_topic_and_button():
    card = build_start_vote_card("food", "https://x/hook")
    assert "food" in card["cardsV2"][0]["card"]["header"]["title"]
    button = card["cardsV2"][0]["card"]["sections"][0]["widgets"][0]["buttonList"]["buttons"][0]
    assert button["onClick"]["action"]["parameters"][0]["value"] == "spy_start_vote"
```

- [ ] **Step 2: Запустить тест — должен упасть**

Run: `pytest tests/test_spy_units.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.games.spy'`.

- [ ] **Step 3: Реализовать модуль**

`app/services/games/spy.py`:

```python
# app/services/games/spy.py
"""Шпион: рандомная тема+слово, тайный шпион, голосование, очки."""
import logging
import random

from app.messaging import send_message as send_dm
from app.schemas import MessagePayload
from app.services.games.scores import award_points
from app.services.games.session import GameManager
from app.services.onboarding import get_or_create_profile

logger = logging.getLogger(__name__)

WORD_BANK: dict[str, list[str]] = {
    "food": ["pizza", "sushi", "pancake", "popcorn", "sandwich"],
    "animals": ["penguin", "kangaroo", "octopus", "hamster", "flamingo"],
    "objects": ["umbrella", "backpack", "toothbrush", "microwave", "scooter"],
    "places": ["airport", "beach", "library", "gym", "cinema"],
}


def assign_roles(players: list[str], rng: random.Random | None = None) -> dict:
    """Выбрать тему, слово и шпиона. rng — для детерминированных тестов."""
    rng = rng or random
    topic = rng.choice(list(WORD_BANK.keys()))
    word = rng.choice(WORD_BANK[topic])
    spy = rng.choice(players)
    return {"topic": topic, "word": word, "spy": spy}


def score_spy(spy: str, votes: dict[str, str], players: list[str]) -> dict[str, int]:
    """Очки за раунд: {user_id: positive_points}.

    Шпион пойман, только если у него строго больше голосов, чем у любого другого.
    """
    tally: dict[str, int] = {}
    for target in votes.values():
        tally[target] = tally.get(target, 0) + 1
    spy_votes = tally.get(spy, 0)
    others_max = max((c for t, c in tally.items() if t != spy), default=0)
    caught = spy_votes > 0 and spy_votes > others_max
    if caught:
        return {p: 1 for p in players if p != spy}
    return {spy: 3}


def build_spy_vote_card(names: dict[str, str], players: list[str], action_url: str) -> dict:
    """Карточка «Кто шпион?» с кнопкой-именем на каждого игрока."""
    buttons = [
        {
            "text": names.get(p, p),
            "onClick": {
                "action": {
                    "function": action_url,
                    "parameters": [{"key": "method", "value": "spy_vote"}, {"key": "target", "value": p}],
                }
            },
        }
        for p in players
    ]
    return {
        "cardsV2": [
            {
                "cardId": "spy_vote",
                "card": {
                    "header": {"title": "Кто шпион? 🕵️", "subtitle": "Голосуй за подозреваемого"},
                    "sections": [{"widgets": [{"buttonList": {"buttons": buttons}}]}],
                },
            }
        ]
    }


def build_start_vote_card(topic: str, action_url: str) -> dict:
    """Карточка после раздачи: тема + кнопка «Начать голосование»."""
    return {
        "cardsV2": [
            {
                "cardId": "spy_start_vote",
                "card": {
                    "header": {"title": f"Тема: {topic}", "subtitle": "Обсуждайте слово! Когда готовы — голосуем."},
                    "sections": [
                        {
                            "widgets": [
                                {
                                    "buttonList": {
                                        "buttons": [
                                            {
                                                "text": "Начать голосование",
                                                "onClick": {
                                                    "action": {
                                                        "function": action_url,
                                                        "parameters": [{"key": "method", "value": "spy_start_vote"}],
                                                    }
                                                },
                                            }
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


def start_spy(session, action_url: str) -> dict:
    """Раздать роли: не-шпионам слово, шпиону — «ты шпион». Вернуть карточку с темой."""
    roles = assign_roles(session.players)
    topic, word, spy = roles["topic"], roles["word"], roles["spy"]
    session.state.update({"topic": topic, "word": word, "spy": spy, "votes": {}})
    for player in session.players:
        text = f"Ты шпион 🤫. Тема: {topic}" if player == spy else f"Твоё слово: {word}"
        send_dm(player, MessagePayload(text=text))
    return build_start_vote_card(topic, action_url)


async def vote(db, session, user_id: str, target: str, space_name: str) -> dict | None:
    """Записать голос «кто шпион»; когда проголосовали все — подсчёт и очки."""
    state = session.state
    votes = state["votes"]
    votes[user_id] = target
    if len(votes) < len(session.players):
        return None  # ждём остальных

    score = score_spy(state["spy"], votes, session.players)
    for user, points in score.items():
        profile = await get_or_create_profile(db, workspace_user_id=user)
        await award_points(db, profile.id, points, "spy")
    GameManager.end(space_name)
    spy_name = session.names.get(state["spy"], state["spy"])
    lines = [f"{session.names.get(u, u)}: +{p}" for u, p in score.items()]
    return {"text": f"Шпионом был {spy_name}! Слово: {state['word']}\n\n" + "\n".join(lines)}
```

- [ ] **Step 4: Запустить тест — должен пройти**

Run: `pytest tests/test_spy_units.py -v`
Expected: PASS (7 тестов).

- [ ] **Step 5: Commit**

```bash
git add app/services/games/spy.py tests/test_spy_units.py
git commit -m "feat(games): add spy word bank, roles, scoring and cards"
```

---

### Task 2: Вебхук запуска голосования и голосов

**Files:**
- Modify: `app/api/google_chat.py`
- Test: `tests/e2e/test_games_spy.py`

**Interfaces:**
- Consumes: `GameManager`, `_addon_response`, `_extract_space_dict`, `_normalize_params` (Этап C), `AsyncSessionLocal`.
- Produces: `_handle_spy_start_vote(space) -> JSONResponse`, `_handle_spy_vote(user, space, params) -> JSONResponse` (async).

- [ ] **Step 1: Написать падающий e2e-тест**

`tests/e2e/test_games_spy.py`:

```python
# tests/e2e/test_games_spy.py
"""E2E полного раунда Шпиона: старт → раздача → голосование → очки в БД."""
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


def _card_click(user_id: str, method: str, space: str, params: list | None = None) -> dict:
    action_params = [{"key": "method", "value": method}] + (params or [])
    return {
        "type": "CARD_CLICKED",
        "user": {"name": user_id, "displayName": "E2E"},
        "space": {"name": space},
        "action": {"function": "https://x/hook", "parameters": action_params},
        "common": {"formInputs": {}},
    }


def _resp_text(resp) -> str:
    return resp.json()["hostAppDataAction"]["chatDataAction"]["createMessageAction"]["message"].get("text", "")


async def test_spy_full_round(client, db):
    space = "spaces/e2e_spy"
    players = ["users/e2e_spy_a", "users/e2e_spy_b", "users/e2e_spy_c"]

    resp = await client.post("/webhooks/google-chat", json=_message(players[0], "/spy", space))
    assert "cardsV2" in resp.json()

    for p in players:
        await client.post("/webhooks/google-chat", json=_card_click(p, "join_game", space))

    resp = await client.post("/webhooks/google-chat", json=_card_click(players[0], "start_game", space))
    card = resp.json()["hostAppDataAction"]["chatDataAction"]["createMessageAction"]["message"]["cardsV2"][0]["card"]
    assert card["header"]["title"].startswith("Тема:")

    resp = await client.post("/webhooks/google-chat", json=_card_click(players[0], "spy_start_vote", space))
    buttons = resp.json()["hostAppDataAction"]["chatDataAction"]["createMessageAction"]["message"]["cardsV2"][0]["card"]["sections"][0]["widgets"][0]["buttonList"]["buttons"]
    assert len(buttons) == 3

    # все голосуют за первого игрока (кто шпион — рандомно, тест не зависит от этого)
    for p in players:
        resp = await client.post(
            "/webhooks/google-chat",
            json=_card_click(p, "spy_vote", space, params=[{"key": "target", "value": players[0]}]),
        )
    text = _resp_text(resp)  # последний голос завершает раунд
    assert "Шпионом был" in text and "Слово:" in text

    rows = (
        await db.execute(
            select(LeaderboardLedger)
            .join(Profile, LeaderboardLedger.profile_id == Profile.id)
            .where(Profile.workspace_user_id.in_(players))
        )
    ).scalars().all()
    # либо шпион +3 (1 строка), либо двое мирных +1+1 (2 строки)
    assert len(rows) in (1, 2)
    assert all(r.event_type == "bonus" and r.reason == "spy" for r in rows)
    assert sum(r.points for r in rows) in (2, 3)
```

- [ ] **Step 2: Запустить тест — должен упасть**

Run (нужен поднятый бот и Postgres):
```bash
$env:SKIP_JWT_VALIDATION="true"; uvicorn app.main:app --port 8000
pytest -m e2e tests/e2e/test_games_spy.py -v
```
Expected: FAIL — методы `spy_start_vote`/`spy_vote` не обрабатываются.

- [ ] **Step 3: Реализовать обработку в `google_chat.py`**

Добавить обработчики (после `_handle_guesspionage_vote`):

```python
def _handle_spy_start_vote(space: dict) -> JSONResponse:
    """Кнопка «Начать голосование»: показать карточку «Кто шпион?»."""
    from app.services.games.spy import build_spy_vote_card

    session = GameManager.get(space.get("name", ""))
    if session is None:
        return JSONResponse(content={})
    return _addon_response(build_spy_vote_card(session.names, session.players, settings.chat_app_audience))


async def _handle_spy_vote(user: dict, space: dict, params: dict) -> JSONResponse:
    """Голос «кто шпион»."""
    from app.services.games.spy import vote as spy_vote

    space_name = space.get("name", "")
    session = GameManager.get(space_name)
    if session is None:
        return JSONResponse(content={})
    target = params.get("target", "")
    async with AsyncSessionLocal() as db:
        result = await spy_vote(db, session, user.get("name", ""), target, space_name)
    if result is None:
        return JSONResponse(content={})
    return _addon_response(result)
```

Подключить игру в диспетчер `_start_session_game` (добавить ветку spy):

```python
def _start_session_game(session, space_name: str, action_url: str) -> dict:
    if session.game == "guesspionage":
        from app.services.games.guesspionage import start_guesspionage

        return start_guesspionage(session, space_name, action_url)
    if session.game == "spy":
        from app.services.games.spy import start_spy

        return start_spy(session, action_url)
    return {"text": "Механика игры ещё не подключена."}
```

Вставить ветки в **add-on** диспетчер кнопок (после `if method == "guesspionage_higher_lower":`, перед `logger.info(...)`):

```python
            if method == "spy_start_vote":
                return _handle_spy_start_vote(_extract_space_dict(chat_data))
            if method == "spy_vote":
                return await _handle_spy_vote(
                    chat_data.get("user", {}),
                    _extract_space_dict(chat_data),
                    _normalize_params(common.get("parameters")),
                )
```

Вставить ветки в **classic** `CARD_CLICKED` (после `if method == "guesspionage_higher_lower":`, перед `logger.info(...)`):

```python
        if method == "spy_start_vote":
            return _handle_spy_start_vote(event.get("space", {}))
        if method == "spy_vote":
            return await _handle_spy_vote(
                event.get("user", {}), event.get("space", {}), _normalize_params(action.get("parameters"))
            )
```

- [ ] **Step 4: Запустить тест — должен пройти**

Run:
```bash
pytest -m e2e tests/e2e/test_games_spy.py -v
```
Expected: PASS (1 тест). Плюс не должны сломаться юнит-тесты: `pytest tests/test_spy_units.py -v`.

- [ ] **Step 5: Commit**

```bash
git add app/api/google_chat.py tests/e2e/test_games_spy.py
git commit -m "feat(games): wire spy start-vote and voting"
```

---

## Self-Review

- **Spec coverage:** банк слов (Task 1), назначение ролей (Task 1 `assign_roles`), раздача в личку (Task 1 `start_spy`), голосование кнопками с именами (Task 1 `build_spy_vote_card` + Task 2), подсчёт (Task 1 `score_spy` + Task 2 `vote`). Путь «шпион угадал слово» из спеки выкинут (договорённость) — подсчёт только «пойман / не пойман».
- **Placeholder scan:** нет TBD/TODO.
- **Type consistency:** `assign_roles(players, rng)`, `score_spy(spy, votes, players)`, `build_spy_vote_card(names, players, action_url)`, `start_spy(session, action_url)`, `vote(db, session, user_id, target, space_name)` — используются в Task 2 с теми же именами и порядком аргументов. `target` в карточке (Task 1) совпадает с чтением `params["target"]` в Task 2.
