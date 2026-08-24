# Активности — Этап D: Шпион — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Игра «шпион»: рандомное слово + тайный шпион, раздача слова в личку, голосование кто шпион, очки.

**Architecture:** `app/services/games/spy.py` (банк слов, роли, карточка голосования, подсчёт); вебхук `/spy`, `spy_vote`; очки через `award_points` (Этап A).

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy 2 async, Google Chat add-on, pytest.

## Global Constraints

- Слова захардкожены по темам (`WORD_BANK: dict[str, list[str]]`).
- Не-шпионам слово в личку; шпиону — «Ты шпион 🤫» + тема.
- Голосование «кто шпион» — кнопки с именами.
- Очки: команда угадала шпиона → команде +1; шпион не вычислен (или угадал слово) → шпиону +3.

## File Structure

- `app/services/games/spy.py` — `WORD_BANK`, `assign_roles`, `build_spy_vote_card`, `score_spy`
- `app/api/google_chat.py` — ветки `/spy` (запуск), `spy_vote`
- `tests/test_spy_units.py` — юнит ролей/подсчёта
- `tests/e2e/test_games_spy.py` — e2e

---

### Task 1: Банк слов и роли

**Files:** Create `app/services/games/spy.py`; Test `tests/test_spy_units.py`

**Interfaces:** `WORD_BANK: dict[str, list[str]]`, `assign_roles(players) -> dict` (topic, word, spy), `build_spy_vote_card(players, action_url) -> dict`, `score_spy(session, votes) -> dict`.

- [ ] **Step 1:** Тест: `assign_roles` выбирает слово из банка и одного шпиона; `score_spy` считает очки (угадали шпиона / нет).
- [ ] **Step 2:** FAIL → **Step 3:** реализовать → **Step 4:** PASS → **Step 5:** Commit.

### Task 2: Вебхук запуска и голосования

**Files:** Modify `app/api/google_chat.py`; Test `tests/e2e/test_games_spy.py`

**Interfaces:** обработка `/spy` (запуск + раздача слова в личку через `send_message`) и `spy_vote` (записать голос; при завершении — `score_spy` + `award_points`).

- [ ] **Step 1:** Тест e2e: `/spy` раздаёт слово в личку (стаб), `spy_vote` начисляет очки в БД.
- [ ] **Step 2:** FAIL → **Step 3:** реализовать → **Step 4:** PASS → **Step 5:** Commit.
