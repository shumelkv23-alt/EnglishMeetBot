# Активности — Этап A: каркас — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Общий каркас игр: in-memory сессия, слеш-команды `/guesspionage` и `/spy`, регистрация участников карточкой «Кто играет?», начисление очков в `leaderboard_ledger`.

**Architecture:** Новый пакет `app/services/games/` (`session.py` — сессия и карточка, `scores.py` — очки). Вебхук `app/api/google_chat.py` распознаёт слеш-команды и кнопки `join_game`/`start_game`. Конкретная механика игр подключается в этапах C (guesspionage) и D (spy) — в этом этапе `start_game` только валидирует и помечает сессию запущенной.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy 2 async, Google Chat add-on + classic webhook, pytest.

**Spec:** `docs/superpowers/specs/2026-08-24-games-stage-A-framework-design.md`

## Global Constraints

- Слеш-команда — это обычное `MESSAGE`, текст начинается с `/` (нативные slash-команды Google вне скоупа).
- Сессия — in-memory словарь `{space_name: GameSession}` внутри синглтона `GameManager`. Рестарт бота во время игры не переживаем.
- Очки — строка `LeaderboardLedger` с `event_type="bonus"`, `meeting_instance_id=None`, `reason=<игра>`, `points != 0`, `event_date` проставляется вручную (server_default у поля нет).
- Регистрация — карточка «Кто играет?» с кнопками `method=join_game` и `method=start_game`.
- Ответ на клик по кнопке всегда в add-on формате (`_addon_response`); ответ на `MESSAGE` — в формате пришедшего события (add-on → `_addon_response`, classic → голый `JSONResponse`).
- Все `send_message` в личку идут через `app/messaging.send_message(user_id, MessagePayload(...))` — он сам ловит исключения и падает в стаб.
- Комментарии в коде на русском, названия и строки в коде — на английском.

## File Structure

- Create `app/services/games/__init__.py` — пакет (пустой docstring).
- Create `app/services/games/session.py` — `GameSession`, `GameManager`, `build_join_card`.
- Create `app/services/games/scores.py` — `award_points`.
- Modify `app/api/google_chat.py` — `_is_slash_command`, обработка `/...`, `join_game`, `start_game`.
- Test `tests/test_games_session_units.py` — юнит сессии и карточки.
- Test `tests/e2e/test_games_framework.py` — e2e слеш-команды, регистрации и начисления очков.

---

### Task 1: GameSession + GameManager + build_join_card

**Files:**
- Create: `app/services/games/__init__.py`
- Create: `app/services/games/session.py`
- Test: `tests/test_games_session_units.py`

**Interfaces:**
- Produces (используется в Task 3 и этапах C/D):
  - `GameSession(game)` — dataclass с полями `game: str`, `players: list[str]`, `names: dict[str, str]`, `state: dict`, `started: bool`.
  - `GameManager.get(space_id: str) -> GameSession | None`
  - `GameManager.start(game: str, space_id: str) -> GameSession`
  - `GameManager.join(space_id: str, user_id: str, name: str = "") -> GameSession | None` (None, если сессии нет или уже началась)
  - `GameManager.end(space_id: str) -> None`
  - `GameManager.reset() -> None` (для тестов)
  - `build_join_card(action_url: str, title: str) -> dict`

- [ ] **Step 1: Написать падающий тест**

`tests/test_games_session_units.py`:

```python
# tests/test_games_session_units.py
import pytest

from app.services.games.session import GameManager, build_join_card


@pytest.fixture(autouse=True)
def _clean_sessions():
    GameManager.reset()
    yield
    GameManager.reset()


def test_start_creates_and_get_returns_session():
    session = GameManager.start("guesspionage", "spaces/1")
    assert session.game == "guesspionage"
    assert GameManager.get("spaces/1") is session


def test_join_adds_player_and_name():
    GameManager.start("spy", "spaces/1")
    session = GameManager.join("spaces/1", "users/a", "Alice")
    assert session is not None
    assert session.players == ["users/a"]
    assert session.names == {"users/a": "Alice"}


def test_join_deduplicates_players():
    GameManager.start("spy", "spaces/1")
    GameManager.join("spaces/1", "users/a")
    GameManager.join("spaces/1", "users/a")
    assert len(GameManager.get("spaces/1").players) == 1


def test_join_returns_none_when_no_session_or_started():
    assert GameManager.join("spaces/1", "users/a") is None
    GameManager.start("spy", "spaces/1")
    GameManager.get("spaces/1").started = True
    assert GameManager.join("spaces/1", "users/a") is None


def test_end_removes_session():
    GameManager.start("spy", "spaces/1")
    GameManager.end("spaces/1")
    assert GameManager.get("spaces/1") is None


def test_build_join_card_has_two_buttons():
    card = build_join_card("https://x/hook", "Шпион")
    buttons = card["cardsV2"][0]["card"]["sections"][1]["widgets"][0]["buttonList"]["buttons"]
    assert [b["text"] for b in buttons] == ["Я в деле", "Начать"]
    methods = [b["onClick"]["action"]["parameters"][0]["value"] for b in buttons]
    assert methods == ["join_game", "start_game"]
```

- [ ] **Step 2: Запустить тест — должен упасть**

Run: `pytest tests/test_games_session_units.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.games'`.

- [ ] **Step 3: Реализовать модуль**

`app/services/games/__init__.py`:

```python
# app/services/games/__init__.py
"""Мини-игры-активности (Guesspionage, Шпион) поверх каркаса Stage A."""
```

`app/services/games/session.py`:

```python
# app/services/games/session.py
"""Каркас игр: in-memory сессия и карточка «Кто играет?»."""
from dataclasses import dataclass, field


@dataclass
class GameSession:
    """Одна игра в одном пространстве (in-memory: рестарт бота сбрасывает всё)."""

    game: str
    players: list[str] = field(default_factory=list)      # workspace_user_id по порядку
    names: dict[str, str] = field(default_factory=dict)   # workspace_user_id -> display_name
    state: dict = field(default_factory=dict)             # игра-специфичное состояние
    started: bool = False


class GameManager:
    """Синглтон-реестр активных игр: {space_name: GameSession}."""

    _sessions: dict[str, GameSession] = {}

    @classmethod
    def get(cls, space_id: str) -> GameSession | None:
        return cls._sessions.get(space_id)

    @classmethod
    def start(cls, game: str, space_id: str) -> GameSession:
        session = GameSession(game=game)
        cls._sessions[space_id] = session
        return session

    @classmethod
    def join(cls, space_id: str, user_id: str, name: str = "") -> GameSession | None:
        session = cls.get(space_id)
        if session is None or session.started:
            return None
        if user_id not in session.players:
            session.players.append(user_id)
        if name:
            session.names[user_id] = name
        return session

    @classmethod
    def end(cls, space_id: str) -> None:
        cls._sessions.pop(space_id, None)

    @classmethod
    def reset(cls) -> None:
        cls._sessions.clear()


def build_join_card(action_url: str, title: str) -> dict:
    """Карточка «Кто играет?» с кнопками «Я в деле» (join_game) и «Начать» (start_game)."""
    return {
        "cardsV2": [
            {
                "cardId": "game_lobby",
                "card": {
                    "header": {"title": title, "subtitle": "Кто играет?"},
                    "sections": [
                        {
                            "widgets": [
                                {
                                    "textParagraph": {
                                        "text": "Нажми «Я в деле», чтобы присоединиться. Когда все готовы — «Начать»."
                                    }
                                }
                            ]
                        },
                        {
                            "widgets": [
                                {
                                    "buttonList": {
                                        "buttons": [
                                            {
                                                "text": "Я в деле",
                                                "onClick": {
                                                    "action": {
                                                        "function": action_url,
                                                        "parameters": [{"key": "method", "value": "join_game"}],
                                                    }
                                                },
                                            },
                                            {
                                                "text": "Начать",
                                                "onClick": {
                                                    "action": {
                                                        "function": action_url,
                                                        "parameters": [{"key": "method", "value": "start_game"}],
                                                    }
                                                },
                                            },
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
```

- [ ] **Step 4: Запустить тест — должен пройти**

Run: `pytest tests/test_games_session_units.py -v`
Expected: PASS (6 тестов).

- [ ] **Step 5: Commit**

```bash
git add app/services/games/__init__.py app/services/games/session.py tests/test_games_session_units.py
git commit -m "feat(games): add in-memory GameSession/GameManager and join card"
```

---

### Task 2: award_points

**Files:**
- Create: `app/services/games/scores.py`
- Test: `tests/e2e/test_games_framework.py` (тест начисления — в Task 3, e2e нужен поднятый Postgres)

**Interfaces:**
- Produces (используется в этапах C/D):
  - `award_points(db: AsyncSession, profile_id: int, points: int, reason: str) -> None` (async)

- [ ] **Step 1: Реализовать модуль**

`app/services/games/scores.py`:

```python
# app/services/games/scores.py
"""Начисление очков в leaderboard_ledger (event_type='bonus')."""
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LeaderboardLedger


async def award_points(db: AsyncSession, profile_id: int, points: int, reason: str) -> None:
    """Записать начисление баллов. profile_id — int-ид профиля из БД, не workspace_user_id.

    meeting_instance_id=None: игры не привязаны к встрече, а UNIQUE-ограничение
    (profile_id, meeting_instance_id, event_type) с NULL не блокирует повторы.
    """
    db.add(
        LeaderboardLedger(
            profile_id=profile_id,
            meeting_instance_id=None,
            event_type="bonus",
            points=points,
            reason=reason,
            event_date=datetime.now(timezone.utc),
        )
    )\
    await db.commit()
```

- [ ] **Step 2: Commit**

```bash
git add app/services/games/scores.py
git commit -m "feat(games): add award_points writing to leaderboard_ledger"
```

---

### Task 3: Слеш-команда + join_game + start_game в вебхуке

**Files:**
- Modify: `app/api/google_chat.py`
- Test: `tests/e2e/test_games_framework.py`

**Interfaces:**
- Consumes: `GameManager`, `build_join_card` (Task 1), `award_points` (Task 2).
- Produces:
  - `_is_slash_command(raw_text: str) -> str | None` (возвращает `"guesspionage"`/`"spy"`/`None`)
  - `_game_command_response(game: str, space_name: str) -> dict`
  - `_handle_join_game(user: dict, space: dict) -> JSONResponse`
  - `_handle_start_game(space: dict) -> JSONResponse` (async)

- [ ] **Step 1: Написать падающий e2e-тест**

`tests/e2e/test_games_framework.py`:

```python
# tests/e2e/test_games_framework.py
"""E2E каркаса игр: слеш-команда, регистрация, начисление очков."""
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


def _card_click(user_id: str, method: str, space: str) -> dict:
    return {
        "type": "CARD_CLICKED",
        "user": {"name": user_id, "displayName": "E2E"},
        "space": {"name": space},
        "action": {"function": "https://x/hook", "parameters": [{"key": "method", "value": method}]},
        "common": {"formInputs": {}},
    }


async def test_slash_command_creates_lobby(client):
    resp = await client.post("/webhooks/google-chat", json=_message("users/e2e_g1", "/guesspionage", "spaces/e2e_g1"))
    assert resp.status_code == 200
    assert "cardsV2" in resp.json()


async def test_join_and_start_flow(client):
    space = "spaces/e2e_g2"
    await client.post("/webhooks/google-chat", json=_message("users/e2e_g2", "/spy", space))
    await client.post("/webhooks/google-chat", json=_card_click("users/e2e_g2a", "join_game", space))
    await client.post("/webhooks/google-chat", json=_card_click("users/e2e_g2b", "join_game", space))
    # всего 2 игрока — для шпиона нужно 3, старт не должен пройти
    resp = await client.post("/webhooks/google-chat", json=_card_click("users/e2e_g2", "start_game", space))
    assert "минимум 3" in resp.json()["hostAppDataAction"]["chatDataAction"]["createMessageAction"]["message"]["text"]


async def test_award_points_writes_ledger(db):
    from app.services.games.scores import award_points

    profile = Profile(workspace_user_id="users/e2e_award", user_email="e2e_award@example.com")
    db.add(profile)
    await db.commit()
    await db.refresh(profile)

    await award_points(db, profile.id, 3, "guesspionage")

    rows = (await db.execute(select(LeaderboardLedger).where(LeaderboardLedger.profile_id == profile.id))).scalars().all()
    assert len(rows) == 1
    assert rows[0].points == 3
    assert rows[0].event_type == "bonus"
    assert rows[0].reason == "guesspionage"
    assert rows[0].meeting_instance_id is None
```

- [ ] **Step 2: Запустить тест — должен упасть**

Run (нужен поднятый бот и Postgres, см. `tests/e2e/conftest.py`):
```bash
$env:SKIP_JWT_VALIDATION="true"; uvicorn app.main:app --port 8000
pytest -m e2e tests/e2e/test_games_framework.py -v
```
Expected: FAIL — `/guesspionage` не распознаётся, карточки нет.

- [ ] **Step 3: Реализовать обработку в `google_chat.py`**

Добавить импорты в начало файла (после `from app.config import get_settings`):

```python
from app.services.games.session import GameManager, build_join_card
```

Добавить константы и хелперы (после `settings = get_settings()`, рядом с другими хелперами `_space_is_dm` и т.п.):

```python
GAME_COMMANDS = ("guesspionage", "spy")
GAME_TITLES = {"guesspionage": "Guesspionage English", "spy": "Шпион"}
MIN_PLAYERS = {"guesspionage": 2, "spy": 3}


def _is_slash_command(raw_text: str) -> str | None:
    """Извлечь имя игры из текста вида '/game'. Возвращает 'guesspionage'/'spy'/None."""
    text = raw_text.strip().lower()
    if not text.startswith("/"):
        return None
    name = text[1:].split()[0] if text[1:].strip() else ""
    return name if name in GAME_COMMANDS else None


def _game_command_response(game: str, space_name: str) -> dict:
    """Создать сессию (если ещё нет) и вернуть карточку «Кто играет?»."""
    if GameManager.get(space_name) is not None:
        return {"text": "Игра в этом чате уже идёт — дождитесь конца раунда."}
    GameManager.start(game, space_name)
    return build_join_card(settings.chat_app_audience, GAME_TITLES[game])


def _handle_join_game(user: dict, space: dict) -> JSONResponse:
    """Кнопка «Я в деле»: добавить игрока в сессию."""
    space_name = space.get("name", "")
    user_id = user.get("name", "")
    session = GameManager.join(space_name, user_id, user.get("displayName", ""))
    if session is None:
        return JSONResponse(content={})
    name = user.get("displayName") or "Игрок"
    return _addon_response({"text": f"{name} в деле! ({len(session.players)} в игре)"})


def _start_session_game(session, space_name: str, action_url: str) -> dict:
    """Запустить конкретную игру. Механика подключается в этапах C (guesspionage) и D (spy)."""
    return {"text": "Механика игры ещё не подключена."}


def _handle_start_game(space: dict) -> JSONResponse:
    """Кнопка «Начать»: валидация по числу игроков и запуск."""
    space_name = space.get("name", "")
    session = GameManager.get(space_name)
    if session is None or session.started:
        return JSONResponse(content={})
    min_players = MIN_PLAYERS.get(session.game, 2)
    if len(session.players) < min_players:
        return _addon_response({"text": f"Нужно минимум {min_players} игроков, чтобы начать."})
    session.started = True
    return _addon_response(_start_session_game(session, space_name, settings.chat_app_audience))
```

Вставить ветку слеш-команды в **add-on** `MESSAGE` (после блока `_is_onboarding_command`, перед «Сохраняем профиль»):

```python
            game = _is_slash_command(raw_text)
            if game:
                space = _extract_space_dict(chat_data)
                return _addon_response(_game_command_response(game, space.get("name", "")))
```

Вставить ветку слеш-команды в **classic** `MESSAGE` (после блока `_is_onboarding_command`):

```python
        game = _is_slash_command(raw_text)
        if game:
            space = event.get("space", {})
            return JSONResponse(content=_game_command_response(game, space.get("name", "")))
```

Вставить в **add-on** диспетчер кнопок (после `if method == "checkin_present":`, перед `logger.info(...)`):

```python
            if method == "join_game":
                space = _extract_space_dict(chat_data)
                return _handle_join_game(chat_data.get("user", {}), space)
            if method == "start_game":
                space = _extract_space_dict(chat_data)
                return _handle_start_game(space)
```

Вставить в **classic** `CARD_CLICKED` (после блока `checkin_submit`, перед `logger.info(...)`):

```python
        if method == "join_game":
            return _handle_join_game(event.get("user", {}), event.get("space", {}))
        if method == "start_game":
            return _handle_start_game(event.get("space", {}))
```

- [ ] **Step 4: Запустить тест — должен пройти**

Run:
```bash
pytest -m e2e tests/e2e/test_games_framework.py -v
```
Expected: PASS (3 теста).

- [ ] **Step 5: Commit**

```bash
git add app/api/google_chat.py tests/e2e/test_games_framework.py
git commit -m "feat(games): wire slash commands, join_game and start_game into webhook"
```

---

## Self-Review

- **Spec coverage:** сессия (`session.py`), слеш-команды (`_is_slash_command`), карточка «Кто играет?» (`build_join_card`), очки (`award_points`), регистрация (`join_game`) — всё покрыто задачами. `registry.py` из спеки заменён на явный `_start_session_game`-диспетчер с ленивыми импортами (проще, без циклических импортов).
- **Placeholder scan:** этап намеренно оставляет `_start_session_game` возвращающим «механика ещё не подключена» — это не заглушка в плане, а валидное поведение этапа A, которое расширяют этапы C/D.
- **Type consistency:** `GameManager.join(space_id, user_id, name)` и `build_join_card(action_url, title)` используются в Task 3 с теми же именами/типами, что определены в Task 1.
