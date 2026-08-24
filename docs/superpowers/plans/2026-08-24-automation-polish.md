# Автоматизация по расписанию — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Связать финализацию опроса с ENG-7 (напоминание + check-in по расписанию), перевести напоминание в группу, вынести время джобов в config и заставить `meeting_duration_minutes` влиять на окно.

**Architecture:** `scheduler._finalize_daily_poll` вызывает `handle_time_finalized` для созданных встреч; `invites._send_reminder` шлёт в группу; `scheduler.init_scheduler` читает config (async); `weekly_poll.finalize_daily_poll` использует `meeting_duration_minutes`.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy 2 async, APScheduler, Google Chat add-on, pytest.

## Global Constraints

- Напоминание (T−1ч) шлётся в группу (`send_text`), не в личку.
- `handle_time_finalized` анонсирует время в группу и ставит джобы `_send_reminder` (T−1ч), `_open_checkin` (в `scheduled_start`), `_close_checkin` (в `scheduled_end+15`).
- Джобы читают время из config: `poll_run_hour`(9)/`poll_run_minute`(0), `poll_finalize_hour`(14)/`poll_finalize_minute`(5), `weekly_poll_day`("sun")/`weekly_poll_hour`(11).
- `meeting_duration_minutes` (default 60) задаёт `scheduled_end` встречи.
- Таймзона — `app_timezone` (как раньше).

---

## File Structure

- **`app/scheduler.py`** — `_finalize_daily_poll` зовёт `handle_time_finalized`; `init_scheduler` async читает config.
- **`app/main.py`** — `await init_scheduler()`.
- **`app/services/invites.py`** — `_send_reminder` в группу, убрать `_profiles_of_poll`.
- **`app/services/weekly_poll.py`** — `meeting_duration_minutes` для `scheduled_end`.
- **`app/services/checkin.py`** — поправить docstring.
- **`tests/e2e/test_jobs.py`** — тесты финализации (duration) и напоминания.

---

### Task 1: `meeting_duration_minutes` в финализации

**Files:**
- Modify: `app/services/weekly_poll.py`
- Test: `tests/e2e/test_jobs.py`

- [ ] **Step 1: Написать падающий тест**

В `tests/e2e/test_jobs.py` в `test_finalize_creates_meeting_on_quorum` добавить проверку длительности:

```python
    meetings = (
        await db.execute(select(MeetingInstance).where(MeetingInstance.poll_id == today_poll.id))
    ).scalars().all()
    assert len(meetings) == 1
    assert today_poll.status == "finalized"
    # длительность встречи из meeting_duration_minutes (default 60)
    m = meetings[0]
    assert m.scheduled_end - m.scheduled_start == timedelta(minutes=60)
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `./venv/Scripts/python.exe -m pytest tests/e2e/test_jobs.py::test_finalize_creates_meeting_on_quorum -m e2e -q`
Expected: FAIL (сейчас `scheduled_end = start + 60` захардкожен, но тест это и проверяет — до правки пройдёт; см. Step 3: проверка всё равно зелёная, это «защитный» тест, фиксирующий поведение).

Примечание: этот тест скорее «закрепляющий», чем «падающий» — до правки `scheduled_end = start + 60` уже даёт нужный результат. Он фиксирует контракт, чтобы правка не сломала его.

- [ ] **Step 3: Реализовать**

В `app/services/weekly_poll.py` в `finalize_daily_poll` перед циклом:

```python
    duration = int((await get_or_create_config(db, "meeting_duration_minutes", 60)).value or 60)
```

и заменить `scheduled_end` в создании `MeetingInstance`:

```python
        db.add(MeetingInstance(
            poll_id=poll.id,
            selected_slot_id=slot_by_time[t].id,
            scheduled_start=scheduled_start,
            scheduled_end=scheduled_start + timedelta(minutes=duration),
            location="Онлайн (Meet)",
            status="scheduled",
        ))
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `./venv/Scripts/python.exe -m pytest tests/e2e/test_jobs.py -m e2e -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/weekly_poll.py tests/e2e/test_jobs.py
git commit -m "feat: meeting_duration_minutes drives scheduled_end" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Напоминание в группу

**Files:**
- Modify: `app/services/invites.py`
- Test: `tests/e2e/test_jobs.py`

- [ ] **Step 1: Написать падающий тест**

В `tests/e2e/test_jobs.py`:

```python
async def test_send_reminder_posts_to_space(db, today_poll, monkeypatch):
    sent = []
    monkeypatch.setattr("app.services.invites.send_text", lambda space, text: sent.append((space, text)))

    meeting = await _make_meeting(db, today_poll, datetime.now(timezone.utc) + timedelta(hours=1))
    from app.services.invites import _send_reminder

    await _send_reminder(str(meeting.id))
    assert len(sent) == 1
    _, text = sent[0]
    assert "Через час" in text
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `./venv/Scripts/python.exe -m pytest tests/e2e/test_jobs.py::test_send_reminder_posts_to_space -m e2e -q`
Expected: FAIL (`send_text` не вызывается — сейчас напоминание шлёт личные DM через `send_message`).

- [ ] **Step 3: Реализовать**

В `app/services/invites.py` заменить `_send_reminder`:

```python
async def _send_reminder(instance_id: str) -> None:
    """Напоминание за lead_hours до встречи — в общий Space (REQ-9.2)."""
    async with AsyncSessionLocal() as db:
        meeting = (
            await db.execute(select(MeetingORM).where(MeetingORM.id == int(instance_id)))
        ).scalar_one_or_none()
        if meeting is None:
            logger.warning("reminder_no_meeting instance=%s", instance_id)
            return
        text = build_invite_text(
            meeting.scheduled_start.strftime("%a"),
            meeting.scheduled_start.strftime("%H:%M"),
            None,
        )
        space_id = await _config_value(db, "space_id", "")
        if space_id:
            send_text(space_id, f"⏰ Через час встреча по английскому!\n\n{text}")
        logger.info("reminder_sent instance=%s", instance_id)
```

Удалить ставшую неиспользуемой `_profiles_of_poll` (она больше нигде не вызывается).

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `./venv/Scripts/python.exe -m pytest tests/e2e/test_jobs.py -m e2e -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/invites.py tests/e2e/test_jobs.py
git commit -m "feat: send meeting reminder to space instead of DMs" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Финализация запускает ENG-7

**Files:**
- Modify: `app/scheduler.py`

- [ ] **Step 1: Реализовать**

В `app/scheduler.py` заменить `_finalize_daily_poll`:

```python
async def _finalize_daily_poll() -> None:
    """Джоб финализации: подвести итог, создать встречи, запустить ENG-7."""
    from sqlalchemy import select

    from app.models import MeetingInstance
    from app.services.invites import handle_time_finalized
    from app.services.weekly_poll import active_daily_poll, finalize_daily_poll, today

    async with AsyncSessionLocal() as db:
        poll = await active_daily_poll(db, today())
        if poll is None:
            logger.info("daily_finalize_job no_active_poll")
            return
        outcome = await finalize_daily_poll(db, poll)
        result = outcome["result"]
        space_id = outcome.get("space_id") or ""
        if not space_id:
            logger.info("daily_finalize_job done poll=%s status=%s (space_id не задан)",
                        poll.id, poll.status)
            return
        if result["meetings"]:
            meetings = (
                await db.execute(select(MeetingInstance).where(MeetingInstance.poll_id == poll.id))
            ).scalars().all()
            for m in meetings:
                await handle_time_finalized(
                    db, m.id,
                    m.scheduled_start.strftime("%a"),
                    m.scheduled_start.strftime("%H:%M"),
                    scheduled_start=m.scheduled_start,
                )
            for choice, target in result["suggest_to"].items():
                send_space_message(space_id, text=f"Тем, кто выбрал {choice} — встреча также в {target}")
        else:
            send_space_message(space_id, text="Сегодня встреча не набирается — отмена")
        logger.info("daily_finalize_job done poll=%s status=%s", poll.id, poll.status)
```

- [ ] **Step 2: Запустить юниты**

Run: `./venv/Scripts/python.exe -m pytest -q`
Expected: PASS (юниты не трогают scheduler).

- [ ] **Step 3: Ручная проверка**

1. Прогнать `_finalize_daily_poll` на поднятом боте (после голосования).
2. В группу уходит анонс «🗓️ Встреча по английскому: …» (от `handle_time_finalized`).
3. В логах APScheduler видны джобы `remind_<id>`, `checkin_open_<id>`, `checkin_close_<id>` на нужное время.

- [ ] **Step 4: Commit**

```bash
git add app/scheduler.py
git commit -m "feat: finalization triggers ENG-7 (reminder + check-in jobs)" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Время джобов из config

**Files:**
- Modify: `app/scheduler.py`, `app/main.py`

- [ ] **Step 1: Реализовать**

В `app/scheduler.py` заменить `init_scheduler`:

```python
async def init_scheduler() -> None:
    """Создать и запустить шедулер; время джобов — из config."""
    global scheduler
    if scheduler is not None:
        return
    from app.services.weekly_poll import get_or_create_config

    async with AsyncSessionLocal() as db:
        run_h = int((await get_or_create_config(db, "poll_run_hour", 9)).value or 9)
        run_m = int((await get_or_create_config(db, "poll_run_minute", 0)).value or 0)
        fin_h = int((await get_or_create_config(db, "poll_finalize_hour", 14)).value or 14)
        fin_m = int((await get_or_create_config(db, "poll_finalize_minute", 5)).value or 5)
        weekly_day = str((await get_or_create_config(db, "weekly_poll_day", "sun")).value or "sun")
        weekly_hour = int((await get_or_create_config(db, "weekly_poll_hour", 11)).value or 11)

    scheduler = AsyncIOScheduler(timezone=get_settings().app_timezone)
    scheduler.add_job(_run_daily_poll, "cron", hour=run_h, minute=run_m, id="daily-poll", replace_existing=True, misfire_grace_time=3600)
    scheduler.add_job(_finalize_daily_poll, "cron", hour=fin_h, minute=fin_m, id="daily-finalize", replace_existing=True, misfire_grace_time=3600)
    scheduler.add_job(_run_weekly_questions, "cron", day_of_week=weekly_day, hour=weekly_hour, minute=0, id="weekly-questions", replace_existing=True, misfire_grace_time=3600)
    scheduler.start()
    logger.info("scheduler_started")
```

В `app/main.py` заменить вызов:

```python
    init_scheduler()
```
на
```python
    await init_scheduler()
```

- [ ] **Step 2: Запустить юниты**

Run: `./venv/Scripts/python.exe -m pytest -q`
Expected: PASS

- [ ] **Step 3: Ручная проверка**

1. Перезапустить бота → в логе `scheduler_started`, джобы на времени из config.
2. Изменить `poll_run_hour` в config → перезапустить → джоб на новом часу.

- [ ] **Step 4: Commit**

```bash
git add app/scheduler.py app/main.py
git commit -m "feat: read job schedule from config" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: Docstring + полный прогон

**Files:**
- Modify: `app/services/checkin.py`

- [ ] **Step 1: Поправить docstring**

В `app/services/checkin.py` заменить первую строку модуля:

```python
"""Self-check-in окно ±N минут вокруг встречи (REQ-6.2, REQ-9.6)."""
```
на
```python
"""Self-check-in: отметка «Я на встрече» в окне встречи (start..end+15)."""
```

- [ ] **Step 2: Полный прогон**

Run: `./venv/Scripts/python.exe -m pytest -q` → юниты зелёные.
Run: `./venv/Scripts/python.exe -m pytest -m e2e -q` → e2e зелёные.

- [ ] **Step 3: Commit**

```bash
git add app/services/checkin.py
git commit -m "chore: fix stale checkin module docstring" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```
