# Активности — Этап A: каркас — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Общий каркас игр: in-memory сессия, слеш-команды, регистрация участников, очки в `leaderboard_ledger`.

**Architecture:** Новый пакет `app/services/games/` (`session.py`, `scores.py`), обработка `/...` в вебхуке, карточка «Кто играет?».

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy 2 async, Google Chat add-on, pytest.

## Global Constraints

- Слеш-команда — `MESSAGE`, текст начинается с `/` (без нативных slash-команд Google).
- Сессия — in-memory `{space_id: GameSession}` (синглтон `GameManager`).
- Очки — `leaderboard_ledger` (`event_type="bonus"`, `meeting_instance_id=None`, `reason=<игра>`).
- Регистрация — карточка «Кто играет?», кнопка `method=join_game`.

## File Structure

- `app/services/games/__init__.py`
- `app/services/games/session.py` — `GameSession`, `GameManager`
- `app/services/games/scores.py` — `award_points`
- `app/api/google_chat.py` — обработка `/` и `join_game`
- `tests/test_games_session_units.py` — юнит сессии
- `tests/e2e/test_games_framework.py` — e2e слеш-команды и регистрации

---

### Task 1: GameSession + GameManager

**Files:** Create `app/services/games/__init__.py`, `app/services/games/session.py`; Test `tests/test_games_session_units.py`

**Interfaces:**
- `GameSession(game, space_id)` — поля `players: dict[str, bool]`, `state: dict`.
- `GameManager.start(game, space_id) -> GameSession`, `.get(space_id)`, `.end(space_id)`.

- [ ] **Step 1:** Написать тест: `start` создаёт сессию, повторный `start` возвращает ту же, `end` удаляет.
- [ ] **Step 2:** Запустить — FAIL.
- [ ] **Step 3:** Реализовать `GameSession` + `GameManager` (класс-синглтон со словарём).
- [ ] **Step 4:** Запустить — PASS.
- [ ] **Step 5:** Commit.

### Task 2: award_points

**Files:** Create `app/services/games/scores.py`; Test `tests/e2e/test_games_framework.py`

**Interfaces:** `award_points(db, profile_id, points, reason) -> None`.

- [ ] **Step 1:** Написать тест: вызов добавляет строку `LeaderboardLedger` (event_type="bonus", points, reason).
- [ ] **Step 2:** Запустить — FAIL.
- [ ] **Step 3:** Реализовать `award_points`.
- [ ] **Step 4:** Запустить — PASS.
- [ ] **Step 5:** Commit.

### Task 3: Слеш-команда

**Files:** Modify `app/api/google_chat.py`; Test `tests/e2e/test_games_framework.py`

**Interfaces:** `_is_slash_command(text) -> str | None`; в `MESSAGE` ветке — если команда известна, вернуть карточку «Кто играет?».

- [ ] **Step 1:** Написать тест: `POST` MESSAGE с текстом `/quiplash` → ответ содержит карточку.
- [ ] **Step 2:** Запустить — FAIL.
- [ ] **Step 3:** Реализовать `_is_slash_command` + вызов `GameManager.start` + карточку.
- [ ] **Step 4:** Запустить — PASS.
- [ ] **Step 5:** Commit.

### Task 4: Регистрация (join_game)

**Files:** Modify `app/api/google_chat.py`; Test `tests/e2e/test_games_framework.py`

**Interfaces:** обработка `method=join_game` — добавить `user.name` в `session.players`.

- [ ] **Step 1:** Написать тест: кнопка `join_game` → профиль в `session.players`.
- [ ] **Step 2:** Запустить — FAIL.
- [ ] **Step 3:** Реализовать ветку `join_game` в диспетчере.
- [ ] **Step 4:** Запустить — PASS.
- [ ] **Step 5:** Commit.
