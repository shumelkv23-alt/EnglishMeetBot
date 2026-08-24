# Онбординг новых участников поллингом — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Периодический поллинг участников группы: новые участники приглашаются в онбординг (тег/анкета), без повторных тегов.

**Architecture:** Поле `Profile.onboarding_invite_sent` + миграция; `check_new_members` (план + маркировка); джоб `_poll_new_members` (cron 10 мин).

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy 2 async, Alembic, APScheduler, pytest.

## Global Constraints

- Период поллинга — 10 минут.
- Маркер `onboarding_invite_sent` ставится при приглашении, сбрасывается в `mark_onboarded`.
- Каналы: `chat_space_id` → анкета в личку; нет → `@упоминание`.

## File Structure

- `app/models.py` — поле.
- `alembic/versions/xxxx_onboarding_invite_sent.py` — миграция.
- `app/services/space_onboarding.py` — `check_new_members`.
- `app/services/onboarding.py` — сброс маркера.
- `app/scheduler.py` — джоб.
- `tests/test_space_onboarding_units.py` (или в `test_onboarding_units.py`) — юнит плана.

---

### Task 1: Поле + миграция

- [ ] **Step 1:** В `app/models.py` в `Profile` добавить:
  ```python
  onboarding_invite_sent: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"), nullable=False)
  ```
- [ ] **Step 2:** Сгенерировать миграцию: `alembic revision --autogenerate -m "onboarding_invite_sent"`, проверить `upgrade/downgrade`, применить `alembic upgrade head`.
- [ ] **Step 3:** Commit.

### Task 2: check_new_members + сброс маркера

- [ ] **Step 1:** Написать юнит-тест плана (мок `list_space_members`): новые участники делятся на dm/mention, маркер ставится, онборднутые/уже-приглашённые пропускаются.
- [ ] **Step 2:** Реализовать `check_new_members(db, space_name) -> {dm, mention}` в `space_onboarding.py`.
- [ ] **Step 3:** В `onboarding.py::mark_onboarded` добавить `profile.onboarding_invite_sent = False`.
- [ ] **Step 4:** Запустить тесты — PASS.
- [ ] **Step 5:** Commit.

### Task 3: Джоб поллинга

- [ ] **Step 1:** В `app/scheduler.py` добавить `_poll_new_members` (читает `space_id`, зовёт `check_new_members`, шлёт по плану через `send_message`/`send_text`).
- [ ] **Step 2:** Зарегистрировать cron-джоб (каждые 10 минут, `id="onboarding-poll"`).
- [ ] **Step 3:** Запустить юниты — PASS.
- [ ] **Step 4:** Commit.

### Task 4: Прогон + ручная проверка

- [ ] Юниты + e2e зелёные.
- [ ] Ручная проверка: добавить нового человека в группу → в течение 10 мин бот тегает/шлёт анкету; повторный поллинг не тегает повторно.
