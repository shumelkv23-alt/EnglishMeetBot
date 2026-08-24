# Inactivity Reminders Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Напоминать участникам, которые 7+ дней не проявляют активность, мягкое сообщение в DM — раз в 3 дня, максимум 3 раза.

**Architecture:** Новое поле `profiles.last_activity_at` фиксирует последнее событие активности; отдельные поля `reminder_count`/`last_reminder_at` — состояние напоминаний. Чистые функции в `app/services/inactivity.py` считают «неактивен?» и «напоминать?»; cron-джоб раз в день прогоняет `remind_inactive()` по активным профилям.

**Tech Stack:** Python 3.11+ / SQLAlchemy 2 async / Alembic / APScheduler / pytest.

**Spec:** `docs/superpowers/specs/2026-08-24-inactivity-reminders-design.md`

## Global Constraints

- Порог неактивности = **7 дней**; интервал повторов = **3 дня**; лимит = **3 раза** подряд.
- Напоминание — **только в DM**, через `app.messaging.send_message(workspace_user_id, MessagePayload(...))`.
- Сравнение «N дней» — в **UTC** (`datetime.now(timezone.utc)`); расписание джоба — в таймзоне приложения.
- Активность (сброс серии) = голос в дневном опросе, ответ на вопрос недели, check-in, сообщение боту.
- НЕ деактивируем (`is_active` не трогаем), НЕ шлём в группу, НЕ наращиваем агрессивность текста.
- `user_id` везде = `workspace_user_id` (`"users/..."`).
- Импорт `touch_activity` в сервисы — **локальный внутри функции** (избегаем циклических импортов между `inactivity` и `weekly_poll`).

---

### Task 1: Миграция 0005 + модели

**Files:**
- Create: `alembic/versions/0005_inactivity_reminders.py`
- Modify: `app/models.py` (класс `Profile`)

**Interfaces:**
- Produces: колонки `Profile.last_activity_at`, `Profile.reminder_count`, `Profile.last_reminder_at`; config-ключи `inactivity_reminder_days`, `inactivity_reminder_interval_days`, `inactivity_max_reminders`, `inactivity_reminder_hour`.

- [ ] **Step 1: Добавить колонки в модель**

В `app/models.py`, в класс `Profile` после `updated_at` (перед закрытием класса) добавь:

```python
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reminder_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    last_reminder_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

- [ ] **Step 2: Создать миграцию**

Создай файл `alembic/versions/0005_inactivity_reminders.py`:

```python
"""inactivity reminders — last_activity_at / reminder_count / last_reminder_at в profiles

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "profiles",
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "profiles",
        sa.Column("reminder_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "profiles",
        sa.Column("last_reminder_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """
        INSERT INTO config (key, value, description) VALUES
        ('inactivity_reminder_days', '7', 'Порог неактивности до первого напоминания, дней'),
        ('inactivity_reminder_interval_days', '3', 'Интервал между повторными напоминаниями, дней'),
        ('inactivity_max_reminders', '3', 'Максимум напоминаний подряд на участника'),
        ('inactivity_reminder_hour', '11', 'Час запуска джоба напоминаний')
        ON CONFLICT (key) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM config WHERE key IN "
        "('inactivity_reminder_days','inactivity_reminder_interval_days',"
        "'inactivity_max_reminders','inactivity_reminder_hour')"
    )
    op.drop_column("profiles", "last_reminder_at")
    op.drop_column("profiles", "reminder_count")
    op.drop_column("profiles", "last_activity_at")
```

- [ ] **Step 3: Применить миграцию**

Run: `.\venv\Scripts\alembic upgrade head`
Expected: no errors.

- [ ] **Step 4: Проверить колонки и config**

Run:
```powershell
docker exec -it meet_bot_db psql -U meet_bot_user -d english_meet_db -c "\d profiles"
docker exec -it meet_bot_db psql -U meet_bot_user -d english_meet_db -c "SELECT key, value FROM config WHERE key LIKE 'inactivity%';"
```
Expected: колонки `last_activity_at`, `reminder_count`, `last_reminder_at` есть; 4 config-ключа со значениями `7`, `3`, `3`, `11`.

- [ ] **Step 5: Commit**

```bash
git add alembic/versions/0005_inactivity_reminders.py app/models.py
git commit -m "feat(inactivity): add last_activity_at + reminder state columns"
```

---

### Task 2: Чистые функции неактивности (TDD)

**Files:**
- Create: `app/services/inactivity.py`
- Test: `tests/test_inactivity_units.py`

**Interfaces:**
- Produces: `touch_activity(profile, now)`, `is_inactive(profile, now, days) -> bool`, `should_remind(profile, now, interval_days, max_reminders) -> bool`, `REMINDER_TEXT: str`.

- [ ] **Step 1: Написать failing-тест**

Создай `tests/test_inactivity_units.py`:

```python
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services.inactivity import REMINDER_TEXT, is_inactive, should_remind, touch_activity

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)


def _profile(**kw):
    base = dict(
        last_activity_at=None,
        reminder_count=0,
        last_reminder_at=None,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_touch_activity_sets_time_and_resets_counter():
    p = _profile(reminder_count=3, last_reminder_at=NOW)
    touch_activity(p, NOW)
    assert p.last_activity_at == NOW
    assert p.reminder_count == 0
    assert p.last_reminder_at is None


def test_is_inactive_after_seven_days():
    assert is_inactive(_profile(last_activity_at=NOW - timedelta(days=7)), NOW, 7) is True


def test_is_inactive_active_recently():
    assert is_inactive(_profile(last_activity_at=NOW - timedelta(days=6)), NOW, 7) is False


def test_is_inactive_falls_back_to_created_at():
    assert is_inactive(_profile(created_at=NOW - timedelta(days=30)), NOW, 7) is True


def test_should_remind_first_time():
    assert should_remind(_profile(), NOW, 3, 3) is True


def test_should_remind_interval_not_elapsed():
    p = _profile(last_reminder_at=NOW - timedelta(days=1))
    assert should_remind(p, NOW, 3, 3) is False


def test_should_remind_interval_elapsed():
    p = _profile(reminder_count=1, last_reminder_at=NOW - timedelta(days=3))
    assert should_remind(p, NOW, 3, 3) is True


def test_should_remind_limit_reached():
    p = _profile(reminder_count=3, last_reminder_at=NOW - timedelta(days=4))
    assert should_remind(p, NOW, 3, 3) is False
```

- [ ] **Step 2: Прогнать тест — убедиться, что падает**

Run: `.\venv\Scripts\pytest tests/test_inactivity_units.py -q`
Expected: FAIL с `ModuleNotFoundError: No module named 'app.services.inactivity'`.

- [ ] **Step 3: Реализовать**

Создай `app/services/inactivity.py`:

```python
"""Напоминания о неактивности: определение и сброс «последней активности»."""
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

REMINDER_TEXT = (
    "Привет! 👋 Давно тебя не было. У нас каждый день короткие встречи по английскому — "
    "заглядывай, если будет минутка. Если формат не зашёл — просто напиши, подстроимся."
)


def touch_activity(profile, now: datetime) -> None:
    """Зафиксировать активность: обновить время и сбросить счётчик напоминаний."""
    profile.last_activity_at = now
    profile.reminder_count = 0
    profile.last_reminder_at = None


def _as_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def is_inactive(profile, now: datetime, days: int) -> bool:
    """Неактивен ли профиль: с последней активности прошло >= days.
    Если last_activity_at не задан — точкой отсчёта служит created_at."""
    base = profile.last_activity_at or profile.created_at
    if base is None:
        return False
    return (now - _as_utc(base)).days >= days


def should_remind(profile, now: datetime, interval_days: int, max_reminders: int) -> bool:
    """Нужно ли слать напоминание: лимит не исчерпан и интервал выдержан."""
    if profile.reminder_count >= max_reminders:
        return False
    if profile.last_reminder_at is None:
        return True
    return (now - _as_utc(profile.last_reminder_at)).days >= interval_days
```

- [ ] **Step 4: Прогнать тест — убедиться, что проходит**

Run: `.\venv\Scripts\pytest tests/test_inactivity_units.py -q`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add app/services/inactivity.py tests/test_inactivity_units.py
git commit -m "feat(inactivity): add pure inactivity helpers"
```

---

### Task 3: `remind_inactive` (TDD)

**Files:**
- Modify: `app/services/inactivity.py`
- Test: `tests/e2e/test_inactivity.py`

**Interfaces:**
- Consumes: `get_or_create_config` из `app.services.weekly_poll` (локальный импорт).
- Produces: `async remind_inactive(db: AsyncSession) -> int`.

- [ ] **Step 1: Написать failing-тест**

Создай `tests/e2e/test_inactivity.py`:

```python
"""E2E: remind_inactive — отправка напоминаний неактивным (реальная БД)."""
from datetime import datetime, timedelta, timezone

import pytest

from app.services.inactivity import remind_inactive
from app.services.onboarding import get_or_create_profile

pytestmark = pytest.mark.e2e

NOW = datetime.now(timezone.utc)


async def _make_profile(db, user_id, *, days_ago, reminder_count=0, last_reminder_days=None):
    p = await get_or_create_profile(db, user_id, chat_space_id="spaces/e2e_inact")
    p.last_activity_at = NOW - timedelta(days=days_ago)
    p.reminder_count = reminder_count
    p.last_reminder_at = (NOW - timedelta(days=last_reminder_days)) if last_reminder_days else None
    await db.commit()
    return p


async def test_remind_inactive_sends_and_increments(db, monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr("app.services.inactivity.send_message", lambda uid, payload: sent.append(uid))
    p = await _make_profile(db, "users/e2e_inact1", days_ago=8)

    await remind_inactive(db)

    assert "users/e2e_inact1" in sent
    await db.refresh(p)
    assert p.reminder_count == 1
    assert p.last_reminder_at is not None


async def test_remind_skips_recently_active(db, monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr("app.services.inactivity.send_message", lambda uid, payload: sent.append(uid))
    await _make_profile(db, "users/e2e_inact_active", days_ago=1)

    await remind_inactive(db)

    assert "users/e2e_inact_active" not in sent


async def test_remind_respects_interval(db, monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr("app.services.inactivity.send_message", lambda uid, payload: sent.append(uid))
    await _make_profile(db, "users/e2e_inact_int", days_ago=8, reminder_count=1, last_reminder_days=1)

    await remind_inactive(db)

    assert "users/e2e_inact_int" not in sent  # интервал 3 дня не прошёл


async def test_remind_stops_at_limit(db, monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr("app.services.inactivity.send_message", lambda uid, payload: sent.append(uid))
    await _make_profile(db, "users/e2e_inact_limit", days_ago=8, reminder_count=3, last_reminder_days=4)

    await remind_inactive(db)

    assert "users/e2e_inact_limit" not in sent  # лимит 3 исчерпан
```

- [ ] **Step 2: Прогнать тест — убедиться, что падает**

Run (нужен поднятый Postgres): `.\venv\Scripts\pytest tests/e2e/test_inactivity.py -m e2e -q`
Expected: FAIL с `ImportError: cannot import name 'remind_inactive'`.

- [ ] **Step 3: Реализовать `remind_inactive`**

В `app/services/inactivity.py` добавь вниз файла:

```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.messaging import send_message
from app.models import Profile
from app.schemas import MessagePayload

DEFAULT_DAYS = 7
DEFAULT_INTERVAL_DAYS = 3
DEFAULT_MAX_REMINDERS = 3


async def remind_inactive(db: AsyncSession) -> int:
    """Найти неактивных активных участников и отправить им напоминание в DM."""
    from app.services.weekly_poll import get_or_create_config

    days = int((await get_or_create_config(db, "inactivity_reminder_days", DEFAULT_DAYS)).value or DEFAULT_DAYS)
    interval = int((await get_or_create_config(db, "inactivity_reminder_interval_days", DEFAULT_INTERVAL_DAYS)).value or DEFAULT_INTERVAL_DAYS)
    max_reminders = int((await get_or_create_config(db, "inactivity_max_reminders", DEFAULT_MAX_REMINDERS)).value or DEFAULT_MAX_REMINDERS)

    now = datetime.now(timezone.utc)
    profiles = (
        await db.execute(
            select(Profile).where(
                Profile.is_active.is_(True),
                Profile.chat_space_id.isnot(None),
            )
        )
    ).scalars().all()

    sent = 0
    for p in profiles:
        if not is_inactive(p, now, days):
            continue
        if not should_remind(p, now, interval, max_reminders):
            continue
        send_message(p.workspace_user_id, MessagePayload(text=REMINDER_TEXT))
        p.reminder_count += 1
        p.last_reminder_at = now
        sent += 1

    if sent:
        await db.commit()
    logger.info("inactivity_reminders_sent sent=%s", sent)
    return sent
```

- [ ] **Step 4: Прогнать тест — убедиться, что проходит**

Run: `.\venv\Scripts\pytest tests/e2e/test_inactivity.py -m e2e -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add app/services/inactivity.py tests/e2e/test_inactivity.py
git commit -m "feat(inactivity): remind_inactive job logic"
```

---

### Task 4: Джоб в планировщике

**Files:**
- Modify: `app/scheduler.py`

**Interfaces:**
- Consumes: `remind_inactive` из `app.services.inactivity`.
- Produces: джоб `inactivity-reminder` (cron, час из config), функция `_run_inactivity_reminder`.

- [ ] **Step 1: Добавить джоб-функцию**

В `app/scheduler.py`, после `_run_weekly_questions`, добавь:

```python
async def _run_inactivity_reminder() -> None:
    """Джоб: напомнить неактивным участникам о встречах."""
    from app.services.inactivity import remind_inactive

    async with AsyncSessionLocal() as db:
        sent = await remind_inactive(db)
        logger.info("inactivity_reminder_job sent=%s", sent)
```

- [ ] **Step 2: Зарегистрировать джоб**

В `init_scheduler()`, в блоке чтения config (после `weekly_hour`) добавь строку:

```python
        rem_h = int((await get_or_create_config(db, "inactivity_reminder_hour", 11)).value or 11)
```

И после `scheduler.add_job(... "weekly-questions" ...)` добавь:

```python
    scheduler.add_job(
        _run_inactivity_reminder,
        "cron",
        hour=rem_h,
        minute=0,
        id="inactivity-reminder",
        replace_existing=True,
        misfire_grace_time=3600,
    )
```

- [ ] **Step 3: Добавить проверку в e2e**

В `tests/e2e/test_jobs.py` добавь два теста (в конец файла):

```python
async def test_inactivity_reminder_job_calls_remind_inactive(db, monkeypatch):
    called: list[int] = []
    async def fake_remind(db):
        called.append(1)
        return 0
    monkeypatch.setattr("app.services.inactivity.remind_inactive", fake_remind)
    from app.scheduler import _run_inactivity_reminder

    await _run_inactivity_reminder()

    assert called == [1]


def test_inactivity_job_registered(db):
    from app.scheduler import init_scheduler, scheduler, shutdown_scheduler

    init_scheduler()
    try:
        assert scheduler.get_job("inactivity-reminder") is not None
    finally:
        shutdown_scheduler()
```

- [ ] **Step 4: Прогнать тест**

Run: `.\venv\Scripts\pytest tests/e2e/test_jobs.py -m e2e -q`
Expected: PASS (все существующие + 2 новых).

- [ ] **Step 5: Commit**

```bash
git add app/scheduler.py tests/e2e/test_jobs.py
git commit -m "feat(inactivity): schedule daily inactivity reminder job"
```

---

### Task 5: Прошивка `touch_activity` в точки активности (TDD)

**Files:**
- Modify: `app/services/weekly_poll.py`, `app/services/weekly_questions.py`, `app/services/checkin.py`, `app/api/google_chat.py`
- Test: `tests/e2e/test_inactivity.py` (добавить 4 теста)

**Interfaces:**
- Consumes: `touch_activity` из `app.services.inactivity` (локальный импорт в каждой функции).

- [ ] **Step 1: Написать failing-тесты**

В `tests/e2e/test_inactivity.py` добавь (в конец файла) следующие 4 теста. Импорты нужны внутри тестов локально — так чище:

```python
async def test_submit_poll_touches_activity(db, today_poll):
    from app.services.weekly_poll import submit_poll

    p = await get_or_create_profile(db, "users/e2e_touch_poll")
    p.reminder_count = 5
    p.last_activity_at = None
    await db.commit()

    await submit_poll(db, p, {"time": {"stringInputs": {"value": ["15:00"]}}})

    await db.refresh(p)
    assert p.last_activity_at is not None
    assert p.reminder_count == 0


async def test_submit_weekly_question_touches_activity(db):
    from app.services.weekly_questions import submit_weekly_question

    p = await get_or_create_profile(db, "users/e2e_touch_wq")
    p.reminder_count = 2
    p.last_activity_at = None
    await db.commit()

    await submit_weekly_question(
        db, p, {"q_llm": {"stringInputs": {"value": ["ответ"]}}}, "личный вопрос", "общий вопрос",
    )

    await db.refresh(p)
    assert p.last_activity_at is not None
    assert p.reminder_count == 0


async def test_submit_checkin_touches_activity(db, today_poll):
    from sqlalchemy import select

    from app.models import MeetingInstance, PollSlot
    from app.services.checkin import submit_checkin

    p = await get_or_create_profile(db, "users/e2e_touch_checkin")
    p.reminder_count = 4
    p.last_activity_at = None
    await db.commit()

    slot = (
        await db.execute(select(PollSlot).where(PollSlot.poll_id == today_poll.id).limit(1))
    ).scalar_one()
    meeting = MeetingInstance(
        poll_id=today_poll.id,
        selected_slot_id=slot.id,
        scheduled_start=datetime.now(timezone.utc),
        scheduled_end=datetime.now(timezone.utc) + timedelta(hours=1),
        location="Онлайн (Meet)",
        status="scheduled",
    )
    db.add(meeting)
    await db.flush()

    await submit_checkin(db, p, meeting.id)

    await db.refresh(p)
    assert p.last_activity_at is not None
    assert p.reminder_count == 0


async def test_message_touches_activity(client, db):
    from sqlalchemy import select

    from app.models import Profile

    event = {
        "type": "MESSAGE",
        "user": {"name": "users/e2e_touch_msg", "displayName": "E2E", "email": "e2e@example.com"},
        "message": {"text": "привет"},
        "space": {"name": "spaces/e2e_dm", "type": "DM"},
    }
    resp = await client.post("/webhooks/google-chat", json=event)
    assert resp.status_code == 200

    profile = (
        await db.execute(select(Profile).where(Profile.workspace_user_id == "users/e2e_touch_msg"))
    ).scalar_one()
    assert profile.last_activity_at is not None
```

- [ ] **Step 2: Прогнать тесты — убедиться, что падают**

Run: `.\venv\Scripts\pytest tests/e2e/test_inactivity.py -m e2e -q`
Expected: FAIL на `test_submit_poll_touches_activity` — `last_activity_at` остаётся `None`.

- [ ] **Step 3: Прошить `touch_activity` в `submit_poll`**

В `app/services/weekly_poll.py`, в `submit_poll`, перед `await db.commit()` (последняя строка успешного пути) вставь:

```python
    from app.services.inactivity import touch_activity

    touch_activity(profile, datetime.now(timezone.utc))
    await db.commit()
```

- [ ] **Step 4: Прошить в `submit_weekly_question`**

В `app/services/weekly_questions.py`, в `submit_weekly_question`, перед `await db.commit()` вставь:

```python
    from datetime import datetime, timezone

    from app.services.inactivity import touch_activity

    touch_activity(profile, datetime.now(timezone.utc))
    await db.commit()
```

- [ ] **Step 5: Прошить в `submit_checkin`**

В `app/services/checkin.py`, в `submit_checkin`, перед `await db.commit()` (переменная `now` уже определена выше) вставь:

```python
    from app.services.inactivity import touch_activity

    touch_activity(profile, now)
    await db.commit()
```

- [ ] **Step 6: Прошить в add-on ветку MESSAGE**

В `app/api/google_chat.py`, в блоке `if "messagePayload" in chat_data:` — после `profile = await get_or_create_profile(...)` и перед `await save_answer(...)` вставь:

```python
                            from datetime import datetime, timezone

                            from app.services.inactivity import touch_activity

                            touch_activity(profile, datetime.now(timezone.utc))
```

- [ ] **Step 7: Прошить в classic ветку MESSAGE**

В `app/api/google_chat.py`, в блоке `if event_type == "MESSAGE":`, перед финальным `return JSONResponse(content={"text": _reply_text(...)})` вставь блок записи активности:

```python
        user = event.get("user", {})
        workspace_user_id = user.get("name", "")
        if workspace_user_id:
            try:
                from datetime import datetime, timezone

                from app.services.inactivity import touch_activity

                space = event.get("space", {})
                async with AsyncSessionLocal() as db:
                    profile = await get_or_create_profile(
                        db,
                        workspace_user_id=workspace_user_id,
                        email=user.get("email"),
                        display_name=user.get("displayName"),
                        chat_space_id=_dm_space_name(space),
                    )
                    touch_activity(profile, datetime.now(timezone.utc))
                    await db.commit()
            except Exception:
                logger.exception("db_write_failed")
        return JSONResponse(content={"text": _reply_text(user_name, raw_text)})
```

- [ ] **Step 8: Прогнать тесты — убедиться, что проходят**

Run: `.\venv\Scripts\pytest tests/e2e/test_inactivity.py -m e2e -q`
Expected: PASS (8 passed — 4 из Task 3 + 4 новых).

- [ ] **Step 9: Прогнать юниты, чтобы не сломать существующее**

Run: `.\venv\Scripts\pytest -q`
Expected: PASS (все юниты; e2e/live исключены по `addopts`).

- [ ] **Step 10: Commit**

```bash
git add app/services/weekly_poll.py app/services/weekly_questions.py app/services/checkin.py app/api/google_chat.py tests/e2e/test_inactivity.py
git commit -m "feat(inactivity): touch last_activity_at on 4 activity events"
```

---

## Self-Review (выполнено автором плана)

- **Spec coverage:** все требования спеки покрыты — миграция (Task 1), чистые функции (Task 2), `remind_inactive` (Task 3), джоб (Task 4), 4 точки активности (Task 5), текст и лимит (Task 2–3). Пункты «не деактивируем / не шлём в группу» — следствие фильтра `is_active`/`chat_space_id` и единого `send_message`.
- **Placeholder scan:** «TBD»/«TODO»/«implement later» отсутствуют; каждый code-step содержит код.
- **Type consistency:** `touch_activity(profile, now)`, `is_inactive(profile, now, days)`, `should_remind(profile, now, interval_days, max_reminders)`, `remind_inactive(db) -> int` — сигнатуры едины во всех задачах и тестах. Config-ключи совпадают с миграцией.
