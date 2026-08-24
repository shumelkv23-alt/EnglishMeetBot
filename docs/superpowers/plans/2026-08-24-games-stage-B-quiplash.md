# Активности — Этап B: Quiplash English — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Игра Quiplash: промпт → тайные ответы → голосование парами → очки.

**Architecture:** `app/services/games/quiplash.py` (промпты, карточки, подсчёт); вебхук `submit_quiplash_answer` и `quiplash_vote`; очки через `award_points` (Этап A).

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy 2 async, Google Chat add-on, pytest.

## Global Constraints

- Промпты захардкожены (`QUIPLASH_PROMPTS`).
- Ответ тайный — карточка с полем в личку.
- Голосование — пары «Ответ A vs Ответ B», кнопки A/B.
- Очки: топ-1 +3 XP, топ-2 +1 XP (в `leaderboard_ledger`).

## File Structure

- `app/services/games/quiplash.py` — промпты, карточки, подсчёт
- `app/api/google_chat.py` — ветки `submit_quiplash_answer`, `quiplash_vote`
- `tests/test_quiplash_units.py` — юнит подсчёта/карточек
- `tests/e2e/test_games_quiplash.py` — e2e

---

### Task 1: Промпты и карточки

**Files:** Create `app/services/games/quiplash.py`; Test `tests/test_quiplash_units.py`

**Interfaces:** `QUIPLASH_PROMPTS: list[str]`, `build_quiplash_answer_card(prompt, action_url) -> dict`, `build_quiplash_pair_card(a_text, b_text, action_url) -> dict`.

- [ ] **Step 1:** Тест: карточка ответа содержит prompt + textInput; карточка пары содержит оба текста и кнопки A/B.
- [ ] **Step 2:** FAIL → **Step 3:** реализовать → **Step 4:** PASS → **Step 5:** Commit.

### Task 2: record_answer + tally

**Files:** Modify `app/services/games/quiplash.py`; Test `tests/test_quiplash_units.py`

**Interfaces:** `record_answer(session, user_id, answer) -> bool`, `tally(session) -> dict`.

- [ ] **Step 1:** Тест: `record_answer` записывает ответ и сигналит, что все ответили; `tally` считает очки по голосам пар.
- [ ] **Step 2:** FAIL → **Step 3:** реализовать → **Step 4:** PASS → **Step 5:** Commit.

### Task 3: Вебхук ответа и голосования

**Files:** Modify `app/api/google_chat.py`; Test `tests/e2e/test_games_quiplash.py`

**Interfaces:** обработка `submit_quiplash_answer` (сохранить ответ в сессию, при полном сборе — отправить пары) и `quiplash_vote` (записать голос, при завершении — начислить очки через `award_points`).

- [ ] **Step 1:** Тест e2e: клик ответа сохраняет в сессию; клик голосования начисляет очки в БД.
- [ ] **Step 2:** FAIL → **Step 3:** реализовать → **Step 4:** PASS → **Step 5:** Commit.
