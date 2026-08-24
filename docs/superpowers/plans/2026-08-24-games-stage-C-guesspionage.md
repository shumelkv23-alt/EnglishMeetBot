# Активности — Этап C: Guesspionage English — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Игра «угадай процент»: вопрос-процент → «выше/ниже» → очки.

**Architecture:** `app/services/games/guesspionage.py` (вопросы, карточки, подсчёт); вебхук `submit_guesspionage_guess` и `guesspionage_higher_lower`; очки через `award_points` (Этап A).

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy 2 async, Google Chat add-on, pytest.

## Global Constraints

- Вопросы+проценты захардкожены (`GUESS_QUESTIONS: list[tuple[str, int]]`).
- Называющий пишет процент в личку (тайно); остальные голосуют Higher/Lower кнопками.
- Очки: называющий ±5%→3, ±10%→2, иначе 1; остальные +1 за верное «выше/ниже».

## File Structure

- `app/services/games/guesspionage.py` — вопросы, карточки, `score_round`
- `app/api/google_chat.py` — ветки `submit_guesspionage_guess`, `guesspionage_higher_lower`
- `tests/test_guesspionage_units.py` — юнит подсчёта/карточек
- `tests/e2e/test_games_guesspionage.py` — e2e

---

### Task 1: Вопросы и подсчёт

**Files:** Create `app/services/games/guesspionage.py`; Test `tests/test_guesspionage_units.py`

**Interfaces:** `GUESS_QUESTIONS: list[tuple[str, int]]`, `build_guesspionage_higher_lower_card(question, action_url) -> dict`, `score_round(question, guess, higher, lower) -> dict`.

- [ ] **Step 1:** Тест: `score_round` считает очки называющему (по близости) и остальным (за верное higher/lower).
- [ ] **Step 2:** FAIL → **Step 3:** реализовать → **Step 4:** PASS → **Step 5:** Commit.

### Task 2: Вебхук догадки и голосования

**Files:** Modify `app/api/google_chat.py`; Test `tests/e2e/test_games_guesspionage.py`

**Interfaces:** обработка `submit_guesspionage_guess` (сохранить число) и `guesspionage_higher_lower` (записать голос; при завершении — `score_round` + `award_points`).

- [ ] **Step 1:** Тест e2e: догадка сохраняется; голоса higher/lower начисляют очки в БД.
- [ ] **Step 2:** FAIL → **Step 3:** реализовать → **Step 4:** PASS → **Step 5:** Commit.
