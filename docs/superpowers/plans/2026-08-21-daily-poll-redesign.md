# Ежедневное голосование за время встречи — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Перевести бота с недельного опроса на ежедневное голосование «кто сегодня и во сколько» с финализацией в 14:05 и онбордингом в личку.

**Architecture:** Переиспользуем существующую схему: `weekly_polls` переименовывается в `daily_polls` (операция = один день), `poll_slots`/`poll_votes`/`poll_responses`/`meeting_instances` остаются. Логика выбора времени выносится в чистую функцию `resolve_day_result`. Два cron-джоба (9:00 создание+рассылка, 14:05 финализация). Онбординг переделывается на отправку анкеты в DM вместо группы.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy 2 async + asyncpg, PostgreSQL 15, Alembic, APScheduler, google-auth, pytest.

## Global Constraints

- Все даты/время — timezone-aware UTC (`datetime.now(timezone.utc)`), `date` — только для «дня» без времени.
- `user_id` везде — строка `"users/..."` (workspace_user_id), не email и не int.
- Формат ответа вебхука для карточек — `action.function` = URL вебхука (`settings.chat_app_audience`), метод приходит через `parameters` под ключом `method`.
- Слоты времени — фиксированные `15:00` / `16:00` / `17:00`, порог `3`, единые (не настраиваются на группу).
- Бот состоит ровно в одной группе; `space_id` хранится в `config`.
- Комментарии к коду — на русском, по стилю PEP 8, type hints на сигнатурах.

---

## Файловая карта

- Modify: `app/models.py` — `WeeklyPoll` → `DailyPoll`.
- Modify: `app/services/weekly_poll.py` — `resolve_day_result`, `parse_form_inputs`, `submit_poll`, `ensure_daily_poll`, `finalize_daily_poll`, `build_daily_poll_card`.
- Modify: `app/api/google_chat.py` — онбординг в личку, обработка `submit_daily_poll`.
- Modify: `app/scheduler.py` — два джоба (9:00, 14:05).
- Modify: `app/services/chat_sender.py` — не трогаем (уже умеет слать в space и DM).
- Create: `alembic/versions/0003_daily_poll.py`.
- Test: `tests/test_daily_poll_units.py`, `tests/test_onboarding_units.py`.

---

### Task 1: Миграция БД — `weekly_polls` → `daily_polls`

**Files:**
- Create: `alembic/versions/0003_daily_poll.py`
- Modify: `app/models.py`

**Interfaces:**
- Produces: таблица `daily_polls` (поля: `id`, `poll_date` DATE unique, `voting_deadline`, `created_at`, `closed_at`, `status`), обновлённые FK из `poll_slots`, `poll_responses`, `meeting_instances`, `poll_questions` на `daily_polls`. Ключи `config`: `daily_slots`, `quorum_threshold`, `poll_run_hour/minute`, `poll_deadline_hour/minute`, `poll_finalize_hour/minute`, `meeting_duration_minutes`.

- [ ] **Step 1: Переименовать модель в `app/models.py`**

Замени класс `WeeklyPoll` на `DailyPoll`:

```python
class DailyPoll(Base):
    """Ежедневный опрос (2. daily_polls). Один опрос = один день."""

    __tablename__ = "daily_polls"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'finalized', 'cancelled')", name="valid_status"),
        Index("idx_daily_polls_date", "poll_date"),
        Index("idx_daily_polls_status", "status"),
        Index("idx_daily_polls_deadline", "voting_deadline"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    poll_date: Mapped[date] = mapped_column(Date, unique=True, nullable=False)
    voting_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        String(50), default="active", server_default=text("'active'"), nullable=False
    )
```

Обнови все `ForeignKey("weekly_polls.id")` → `ForeignKey("daily_polls.id")` в `PollSlot`, `PollResponse`, `MeetingInstance`, `PollQuestion`, и все `select(WeeklyPoll)`/импорты на `DailyPoll` в `app/services/weekly_poll.py`, `app/services/invites.py`, `app/services/reminders.py`.

- [ ] **Step 2: Создать миграцию `alembic/versions/0003_daily_poll.py`**

```python
"""daily_polls — переименование weekly_polls под ежедневный цикл

Revision ID: 0003
Revises: 0002
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # снять FK и unique перед переименованием
    op.drop_constraint("poll_questions_poll_id_fkey", "poll_questions", type_="foreignkey")
    op.drop_constraint("meeting_instances_poll_id_fkey", "meeting_instances", type_="foreignkey")
    op.drop_constraint("poll_responses_poll_id_fkey", "poll_responses", type_="foreignkey")
    op.drop_constraint("poll_slots_poll_id_fkey", "poll_slots", type_="foreignkey")

    op.alter_column("weekly_polls", "week_start", new_column_name="poll_date")
    op.drop_constraint("valid_reminder_interval", "weekly_polls", type_="check")
    op.drop_constraint("valid_max_reminders", "weekly_polls", type_="check")
    op.drop_column("weekly_polls", "reminder_interval_hours")
    op.drop_column("weekly_polls", "max_reminders")
    op.rename_table("weekly_polls", "daily_polls")

    # вернуть FK на новое имя таблицы
    op.create_foreign_key("poll_slots_poll_id_fkey", "poll_slots", "daily_polls", ["poll_id"], ["id"])
    op.create_foreign_key("poll_responses_poll_id_fkey", "poll_responses", "daily_polls", ["poll_id"], ["id"])
    op.create_foreign_key("meeting_instances_poll_id_fkey", "meeting_instances", "daily_polls", ["poll_id"], ["id"])
    op.create_foreign_key("poll_questions_poll_id_fkey", "poll_questions", "daily_polls", ["poll_id"], ["id"])

    op.execute(
        """
        INSERT INTO config (key, value, description) VALUES
        ('daily_slots', '["15:00", "16:00", "17:00"]', 'Ежедневные слоты времени'),
        ('quorum_threshold', '3', 'Минимум участников для встречи'),
        ('poll_run_hour', '9', 'Час отправки ежедневного опроса'),
        ('poll_run_minute', '0', 'Минута отправки ежедневного опроса'),
        ('poll_deadline_hour', '14', 'Час дедлайна голосования'),
        ('poll_deadline_minute', '0', 'Минута дедлайна голосования'),
        ('poll_finalize_hour', '14', 'Час финализации'),
        ('poll_finalize_minute', '5', 'Минута финализации'),
        ('meeting_duration_minutes', '60', 'Длительность встречи')
        ON CONFLICT (key) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM config WHERE key IN ('daily_slots','quorum_threshold','poll_run_hour','poll_run_minute','poll_deadline_hour','poll_deadline_minute','poll_finalize_hour','poll_finalize_minute','meeting_duration_minutes')")
    op.drop_constraint("poll_questions_poll_id_fkey", "poll_questions", type_="foreignkey")
    op.drop_constraint("meeting_instances_poll_id_fkey", "meeting_instances", type_="foreignkey")
    op.drop_constraint("poll_responses_poll_id_fkey", "poll_responses", type_="foreignkey")
    op.drop_constraint("poll_slots_poll_id_fkey", "poll_slots", type_="foreignkey")
    op.rename_table("daily_polls", "weekly_polls")
    op.alter_column("weekly_polls", "poll_date", new_column_name="week_start")
    op.add_column("weekly_polls", sa.Column("reminder_interval_hours", sa.Integer(), server_default="24", nullable=False))
    op.add_column("weekly_polls", sa.Column("max_reminders", sa.Integer(), server_default="3", nullable=False))
    op.create_foreign_key("poll_slots_poll_id_fkey", "poll_slots", "weekly_polls", ["poll_id"], ["id"])
    op.create_foreign_key("poll_responses_poll_id_fkey", "poll_responses", "weekly_polls", ["poll_id"], ["id"])
    op.create_foreign_key("meeting_instances_poll_id_fkey", "meeting_instances", "weekly_polls", ["poll_id"], ["id"])
    op.create_foreign_key("poll_questions_poll_id_fkey", "poll_questions", "weekly_polls", ["poll_id"], ["id"])
```

Примечание: в `downgrade` нужно `import sqlalchemy as sa` в начале файла.

- [ ] **Step 3: Применить миграцию**

Run: `venv/Scripts/python.exe -m alembic upgrade head`
Expected: `INFO  [alembic.runtime.migration] Running upgrade 0002 -> 0003, daily_polls...`

- [ ] **Step 4: Прогнать юнит-тесты на импорт моделей**

Run: `venv/Scripts/python.exe -m pytest tests/test_contract_smoke.py -q`
Expected: PASS (модели импортируются без ошибок).

- [ ] **Step 5: Commit**

```bash
git add alembic/versions/0003_daily_poll.py app/models.py app/services/weekly_poll.py
git commit -m "db: weekly_polls → daily_polls (ежедневный опрос)"
```

---

### Task 2: Чистая функция `resolve_day_result`

**Files:**
- Modify: `app/services/weekly_poll.py`
- Test: `tests/test_daily_poll_units.py`

**Interfaces:**
- Produces: `resolve_day_result(votes: dict[str, int], quorum: int) -> dict` — вход `{"15:00": 3, "16:00": 2, "17:00": 1}`, выход `{"meetings": ["15:00"], "suggest_to": {"16:00": "15:00", "17:00": "15:00"}, "cancelled": False}`. `suggest_to` — время недобора → время, куда предложить.

- [ ] **Step 1: Написать failing-тест**

```python
# tests/test_daily_poll_units.py
from app.services.weekly_poll import resolve_day_result


def test_resolve_three_groups():
    r = resolve_day_result({"15:00": 3, "16:00": 4, "17:00": 3}, 3)
    assert r["meetings"] == ["15:00", "16:00", "17:00"]
    assert r["suggest_to"] == {}
    assert r["cancelled"] is False


def test_resolve_suggest_losers():
    r = resolve_day_result({"15:00": 3, "16:00": 2, "17:00": 1}, 3)
    assert r["meetings"] == ["15:00"]
    assert r["suggest_to"] == {"16:00": "15:00", "17:00": "15:00"}
    assert r["cancelled"] is False


def test_resolve_cancelled():
    r = resolve_day_result({"15:00": 2, "16:00": 2, "17:00": 2}, 3)
    assert r["meetings"] == []
    assert r["cancelled"] is True
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `venv/Scripts/python.exe -m pytest tests/test_daily_poll_units.py -q`
Expected: FAIL с `ImportError: cannot import name 'resolve_day_result'`.

- [ ] **Step 3: Реализовать**

```python
def resolve_day_result(votes: dict[str, int], quorum: int) -> dict:
    """Итог дня: какие времена набрали порог, кому предложить другое время.

    votes — {"15:00": N, ...}; quorum — минимальное число голосов.
    Возвращает {"meetings": [...], "suggest_to": {...}, "cancelled": bool}.
    """
    meetings = [t for t, c in votes.items() if c >= quorum]
    if not meetings:
        return {"meetings": [], "suggest_to": {}, "cancelled": True}
    # самое популярное из состоявшихся — для предложения недобравшим
    best = max(meetings, key=lambda t: votes[t])
    suggest_to = {
        t: best
        for t, c in votes.items()
        if 0 < c < quorum
    }
    return {"meetings": sorted(meetings), "suggest_to": suggest_to, "cancelled": False}
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `venv/Scripts/python.exe -m pytest tests/test_daily_poll_units.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/weekly_poll.py tests/test_daily_poll_units.py
git commit -m "feat: resolve_day_result — выбор времени по порогу"
```

---

### Task 3: Хелпер парсинга `formInputs` (фикс CRITICAL #2)

**Files:**
- Modify: `app/services/weekly_poll.py`
- Modify: `app/services/onboarding_answers.py`
- Test: `tests/test_daily_poll_units.py`

**Interfaces:**
- Produces: `parse_form_inputs(form_inputs: dict) -> dict[str, list[str]]` — нормализует оба формата Google (плоский `{"stringInputs": {...}}` и add-on `{"": {"stringInputs": {...}}}`) в `{name: [values]}`.

- [ ] **Step 1: Написать failing-тест**

```python
def test_parse_form_inputs_addon_nested():
    addon = {"slots": {"": {"stringInputs": {"value": ["15:00"]}}}}
    assert parse_form_inputs(addon) == {"slots": ["15:00"]}


def test_parse_form_inputs_flat():
    flat = {"q1": {"stringInputs": {"value": ["it", "travel"]}}}
    assert parse_form_inputs(flat) == {"q1": ["it", "travel"]}
```

- [ ] **Step 2: Запустить — падает**

Run: `venv/Scripts/python.exe -m pytest tests/test_daily_poll_units.py::test_parse_form_inputs_addon_nested -q`
Expected: FAIL.

- [ ] **Step 3: Реализовать в `weekly_poll.py`**

```python
def parse_form_inputs(form_inputs: dict) -> dict[str, list[str]]:
    """Нормализовать formInputs в {name: [values]} для обоих форматов Google.

    Плоский:  {"name": {"stringInputs": {"value": [...]}}}
    Add-on:   {"name": {"": {"stringInputs": {"value": [...]}}}}
    """
    result: dict[str, list[str]] = {}
    for name, field in (form_inputs or {}).items():
        if not isinstance(field, dict):
            continue
        si = field.get("stringInputs")
        if not isinstance(si, dict):
            inner = field.get("")
            si = inner.get("stringInputs") if isinstance(inner, dict) else None
        if not isinstance(si, dict):
            continue
        values = [v.strip() for v in si.get("value", []) if isinstance(v, str) and v.strip()]
        if values:
            result[name] = values
    return result
```

- [ ] **Step 4: Переиспользовать в `onboarding_answers.py`**

В `_get_values` заменить тело на вызов `parse_form_inputs` (импорт из `app.services.weekly_poll` или вынести хелпер в `app/services/form_parsing.py`). Чтобы не плодить копии, вынеси `parse_form_inputs` в новый файл `app/services/form_parsing.py` и импортируй оттуда в оба места.

- [ ] **Step 5: Запустить все юнит-тесты**

Run: `venv/Scripts/python.exe -m pytest tests/test_daily_poll_units.py tests/test_weekly_poll_units.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/services/form_parsing.py app/services/weekly_poll.py app/services/onboarding_answers.py tests/test_daily_poll_units.py
git commit -m "fix: парсинг add-on formInputs (вложенный формат)"
```

---

### Task 4: `submit_poll` под ежедневный цикл

**Files:**
- Modify: `app/services/weekly_poll.py`
- Test: `tests/test_daily_poll_units.py`

**Interfaces:**
- Consumes: `DailyPoll`, `parse_form_inputs`.
- Produces: `submit_poll(db, profile, form_inputs) -> dict` — возвращает `{"ok": bool, "reason": "saved"|"closed"|"no_poll"|"empty"}`. Принимает форму с ключом `time` (`"15:00"`/`"16:00"`/`"17:00"`/`"not_available"`).

- [ ] **Step 1: Написать failing-тест логики выбора (через заглушку)**

Проверь чистую часть — `_normalize_submit_time`:

```python
def test_normalize_submit_time():
    assert _normalize_submit_time({"time": {"stringInputs": {"value": ["15:00"]}}}) == "15:00"
    assert _normalize_submit_time({"time": {"stringInputs": {"value": ["not_available"]}}}) == "not_available"
    assert _normalize_submit_time({}) == ""
```

- [ ] **Step 2: Реализовать `_normalize_submit_time` + переписать `submit_poll`**

```python
def _normalize_submit_time(form_inputs: dict) -> str:
    vals = parse_form_inputs(form_inputs).get("time", [])
    return vals[0] if vals else ""
```

Перепиши `submit_poll`: вместо вопросов q_llm/q_bank и `parse_poll_form` — используй `_normalize_submit_time`. Логика:
- нет опроса дня → `{"ok": False, "reason": "no_poll"}`
- дедлайн прошёл → `{"ok": False, "reason": "closed"}`
- `time == ""` → `{"ok": False, "reason": "empty"}`
- `time == "not_available"` → статус ответа `not_available`, голоса удалить.
- иначе: найти слот с этим временем, удалить старые голоса, вставить один, статус `responded`.

```python
async def submit_poll(db: AsyncSession, profile: Profile, form_inputs: dict) -> dict:
    poll = await active_daily_poll(db, today())
    if poll is None:
        return {"ok": False, "reason": "no_poll"}
    deadline = poll.voting_deadline
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    if deadline < datetime.now(timezone.utc):
        return {"ok": False, "reason": "closed"}

    choice = _normalize_submit_time(form_inputs)
    if not choice:
        return {"ok": False, "reason": "empty"}

    response = (
        await db.execute(select(PollResponse).where(
            PollResponse.profile_id == profile.id, PollResponse.poll_id == poll.id))
    ).scalar_one_or_none()
    if response is None:
        response = PollResponse(profile_id=profile.id, poll_id=poll.id)
        db.add(response)

    # одно время на человека: убрать старые голоса
    await db.execute(delete(PollVote).where(
        PollVote.profile_id == profile.id,
        PollVote.poll_slot_id.in_(select(PollSlot.id).where(PollSlot.poll_id == poll.id)),
    ))

    if choice == "not_available":
        response.status = "not_available"
    else:
        slot = (
            await db.execute(select(PollSlot).where(
                PollSlot.poll_id == poll.id, PollSlot.slot_start == slot_datetime(choice)))
        ).scalar_one_or_none()
        if slot is None:
            return {"ok": False, "reason": "empty"}
        db.add(PollVote(profile_id=profile.id, poll_slot_id=slot.id, poll_response_id=response.id))
        response.status = "responded"
        response.responded_at = datetime.now(timezone.utc)

    await db.commit()
    return {"ok": True, "reason": "saved"}
```

Здесь `active_daily_poll(db, day)` и `slot_datetime(t)` — новые помощники (см. Task 6); если их ещё нет, добавь заглушки в этом таске.

- [ ] **Step 3: Запустить юнит-тесты**

Run: `venv/Scripts/python.exe -m pytest tests/test_daily_poll_units.py -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add app/services/weekly_poll.py tests/test_daily_poll_units.py
git commit -m "feat: submit_poll — одно время на человека (ежедневный)"
```

---

### Task 5: Карточка ежедневного голосования

**Files:**
- Modify: `app/services/weekly_poll.py`
- Test: `tests/test_daily_poll_units.py`

**Interfaces:**
- Produces: `build_daily_poll_card(slots: list[str], action_url: str) -> dict` — Cards V2: заголовок, три кнопки времени + кнопка «не могу сегодня».

- [ ] **Step 1: Написать failing-тест**

```python
def test_build_daily_poll_card_has_four_buttons():
    card = build_daily_poll_card(["15:00", "16:00", "17:00"], action_url="https://x/hook")
    buttons = card["cardsV2"][0]["card"]["sections"][0]["widgets"][0]["buttonList"]["buttons"]
    labels = [b["text"] for b in buttons]
    assert labels == ["15:00", "16:00", "17:00", "Не могу сегодня"]
    assert all(b["onClick"]["action"]["function"] == "https://x/hook" for b in buttons)
```

- [ ] **Step 2: Реализовать**

```python
def build_daily_poll_card(slots: list[str], action_url: str) -> dict:
    buttons = []
    for t in slots:
        buttons.append({
            "text": t,
            "onClick": {"action": {
                "function": action_url or "submit_daily_poll",
                "parameters": [
                    {"key": "method", "value": "submit_daily_poll"},
                    {"key": "time", "value": t},
                ],
            }},
        })
    buttons.append({
        "text": "Не могу сегодня",
        "onClick": {"action": {
            "function": action_url or "submit_daily_poll",
            "parameters": [
                {"key": "method", "value": "submit_daily_poll"},
                {"key": "time", "value": "not_available"},
            ],
        }},
    })
    return {
        "cardsV2": [{
            "cardId": "dailyPoll",
            "card": {
                "header": {"title": "Кто сегодня и во сколько? 🗓️",
                           "subtitle": "Выбери время или «не могу»"},
                "sections": [{"widgets": [{"buttonList": {"buttons": buttons}}]}],
            },
        }]
    }
```

- [ ] **Step 3: Запустить — проходит**

Run: `venv/Scripts/python.exe -m pytest tests/test_daily_poll_units.py::test_build_daily_poll_card_has_four_buttons -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add app/services/weekly_poll.py tests/test_daily_poll_units.py
git commit -m "feat: build_daily_poll_card — кнопки времени + не могу"
```

---

### Task 6: Создание опроса дня + финализация

**Files:**
- Modify: `app/services/weekly_poll.py`
- Modify: `app/scheduler.py`

**Interfaces:**
- Produces: `active_daily_poll(db, day) -> DailyPoll | None`, `ensure_daily_poll(db, now) -> DailyPoll`, `finalize_daily_poll(db, poll) -> dict`, `slot_datetime(time_str) -> datetime` (naive UTC).

- [ ] **Step 1: Написать failing-тест на `slot_datetime`**

```python
def test_slot_datetime():
    dt = slot_datetime("15:00")
    assert dt.hour == 15 and dt.minute == 0
```

- [ ] **Step 2: Реализовать помощники + `ensure_daily_poll`**

```python
def today() -> date:
    return datetime.now(timezone.utc).date()


def slot_datetime(time_str: str) -> datetime:
    """datetime слота в UTC для хранения (дата не важна — сравниваем по времени)."""
    h, m = time_str.split(":")
    return datetime(2000, 1, 1, int(h), int(m), tzinfo=timezone.utc)


async def active_daily_poll(db: AsyncSession, day: date) -> DailyPoll | None:
    return (await db.execute(
        select(DailyPoll).where(DailyPoll.poll_date == day, DailyPoll.status == "active")
    )).scalar_one_or_none()


async def ensure_daily_poll(db: AsyncSession, now: datetime) -> DailyPoll | None:
    day = now.date()
    poll = await active_daily_poll(db, day)
    if poll is not None:
        return poll
    slots_cfg = json.loads((await get_or_create_config(db, "daily_slots", '["15:00","16:00","17:00"]')).value)
    deadline_h = int((await get_or_create_config(db, "poll_deadline_hour", 14)).value)
    deadline_m = int((await get_or_create_config(db, "poll_deadline_minute", 0)).value)
    poll = DailyPoll(
        poll_date=day,
        voting_deadline=datetime(day.year, day.month, day.day, deadline_h, deadline_m, tzinfo=timezone.utc),
        status="active",
    )
    db.add(poll)
    await db.flush()
    for t in slots_cfg:
        st = slot_datetime(t)
        db.add(PollSlot(poll_id=poll.id, slot_start=st, slot_end=st + timedelta(minutes=60), location="Онлайн (Meet)"))
    await db.commit()
    return poll
```

- [ ] **Step 3: Реализовать `finalize_daily_poll`**

```python
async def finalize_daily_poll(db: AsyncSession, poll: DailyPoll) -> dict:
    slots = (await db.execute(select(PollSlot).where(PollSlot.poll_id == poll.id))).scalars().all()
    votes = {
        s.slot_start.strftime("%H:%M"): (s.votes_count or 0)
        for s in slots
    }
    quorum = int((await get_or_create_config(db, "quorum_threshold", 3)).value or 3)
    result = resolve_day_result(votes, quorum)

    for t in result["meetings"]:
        st = slot_datetime(t)
        db.add(MeetingInstance(
            poll_id=poll.id,
            selected_slot_id=next(s.id for s in slots if s.slot_start.strftime("%H:%M") == t),
            scheduled_start=st, scheduled_end=st + timedelta(minutes=60),
            location="Онлайн (Meet)", status="scheduled",
        ))
    poll.status = "finalized" if result["meetings"] else "cancelled"
    poll.closed_at = datetime.now(timezone.utc)
    await db.commit()
    return {"result": result, "space_id": await _config_value(db, "space_id", "")}
```

- [ ] **Step 4: Подключить два джоба в `app/scheduler.py`**

```python
async def _run_daily_poll():
    from app.services.weekly_poll import ensure_daily_poll, build_daily_poll_card, get_or_create_config
    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)
        poll = await ensure_daily_poll(db, now)
        space_id = (await get_or_create_config(db, "space_id", "")).value or ""
        if poll is not None and space_id:
            slots = ["15:00", "16:00", "17:00"]
            send_message(space_id, MessagePayload(
                text="Кто сегодня и во сколько? 🗓️",
                card=build_daily_poll_card(slots, get_settings().chat_app_audience),
            ))

async def _finalize_daily_poll():
    from app.services.weekly_poll import active_daily_poll, finalize_daily_poll
    async with AsyncSessionLocal() as db:
        poll = await active_daily_poll(db, datetime.now(timezone.utc).date())
        if poll is not None:
            await finalize_daily_poll(db, poll)
```

В `init_scheduler` замени `_run_weekly_poll` (cron mon 10:00) на два джоба:
```python
scheduler.add_job(_run_daily_poll, "cron", hour=9, minute=0, id="daily-poll", replace_existing=True)
scheduler.add_job(_finalize_daily_poll, "cron", hour=14, minute=5, id="daily-finalize", replace_existing=True)
```

- [ ] **Step 5: Запустить юнит-тесты**

Run: `venv/Scripts/python.exe -m pytest tests/test_daily_poll_units.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/services/weekly_poll.py app/scheduler.py tests/test_daily_poll_units.py
git commit -m "feat: ежедневный опрос — создание в 9:00, финализация в 14:05"
```

---

### Task 7: Обработка `submit_daily_poll` в вебхуке

**Files:**
- Modify: `app/api/google_chat.py`

**Interfaces:**
- Consumes: `submit_poll`, `build_daily_poll_card`.
- Produces: обработка `method == "submit_daily_poll"` в add-on `buttonClickedPayload` и классическом `CARD_CLICKED`.

- [ ] **Step 1: Добавить обработчик в `google_chat.py`**

Рядом с `_submit_weekly_poll` добавь:

```python
async def _submit_daily_poll(chat_data: dict, common: dict) -> dict:
    form_inputs = common.get("formInputs", {}) or {}
    user = chat_data.get("user", {})
    workspace_user_id = user.get("name", "")
    result = {"ok": False, "reason": "no_user"}
    if workspace_user_id:
        try:
            async with AsyncSessionLocal() as db:
                profile = await get_or_create_profile(
                    db, workspace_user_id=workspace_user_id,
                    email=user.get("email"), display_name=user.get("displayName"),
                    chat_space_id=_extract_space_name(chat_data) or None,
                )
                result = await submit_poll(db, profile, form_inputs)
        except Exception:
            logger.exception("daily_poll_submit_failed")
            result = {"ok": False, "reason": "db_error"}
    if result.get("ok"):
        return {"text": "Спасибо, учёл! 🙌"}
    if result.get("reason") == "closed":
        return {"text": "Голосование уже закрыто — итог объявлен."}
    return {"text": "Не получилось сохранить — попробуй ещё раз."}
```

В `buttonClickedPayload` ветке добавь:
```python
if method == "submit_daily_poll":
    return _addon_response(await _submit_daily_poll(chat_data, common))
```

И в классической `CARD_CLICKED` ветке — аналог по `method == "submit_daily_poll"`.

- [ ] **Step 2: Прогнать смоук-тест**

Run: `venv/Scripts/python.exe -m pytest tests/test_contract_smoke.py -q`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add app/api/google_chat.py
git commit -m "feat: webhook — submit_daily_poll"
```

---

### Task 8: Онбординг в личку

**Files:**
- Modify: `app/api/google_chat.py`
- Create: `app/services/onboarding.py` (добавить функцию) — либо отдельный `app/services/space_onboarding.py`
- Test: `tests/test_onboarding_units.py`

**Interfaces:**
- Consumes: `chat_sender.list_space_members`, `send_message`.
- Produces: `onboard_space_members(db, space_name) -> dict` — `{"dm_sent": int, "mentioned": int}`.

- [ ] **Step 1: Написать failing-тест на чистую часть**

Вынеси решение «кому DM, кому упоминание» в чистую функцию:

```python
def plan_onboarding(profiles_by_ws: dict[str, bool], members: list[str]) -> dict:
    """members — workspace_user_id участников; profiles_by_ws — есть ли DM у ws id.
    Возвращает {'dm': [...], 'mention': [...]}."""
    dm = [m for m in members if profiles_by_ws.get(m)]
    mention = [m for m in members if not profiles_by_ws.get(m)]
    return {"dm": dm, "mention": mention}
```

```python
# tests/test_onboarding_units.py
from app.services.space_onboarding import plan_onboarding

def test_plan_onboarding_split():
    members = ["users/a", "users/b", "users/c"]
    profiles = {"users/a": True, "users/b": False}
    r = plan_onboarding(profiles, members)
    assert r["dm"] == ["users/a"]
    assert r["mention"] == ["users/b", "users/c"]
```

- [ ] **Step 2: Реализовать `space_onboarding.py`**

```python
# app/services/space_onboarding.py
def plan_onboarding(profiles_by_ws: dict[str, bool], members: list[str]) -> dict:
    dm = [m for m in members if profiles_by_ws.get(m)]
    mention = [m for m in members if not profiles_by_ws.get(m)]
    return {"dm": dm, "mention": mention}


async def onboard_space_members(db, space_name: str) -> dict:
    from app.services.chat_sender import list_space_members
    from app.services.onboarding import get_or_create_profile
    from app.models import Profile
    from sqlalchemy import select
    memberships = list_space_members(space_name)
    member_ids = [m["member"]["name"] for m in memberships if m.get("member", {}).get("type") == "HUMAN"]
    profiles = (await db.execute(select(Profile).where(Profile.workspace_user_id.in_(member_ids)))).scalars().all()
    by_ws = {p.workspace_user_id: bool(p.chat_space_id and not p.onboarding_completed) for p in profiles}
    plan = plan_onboarding(by_ws, member_ids)
    return {"dm": plan["dm"], "mention": plan["mention"]}
```

- [ ] **Step 3: Подключить в `ADDED_TO_SPACE`**

В `google_chat.py` в ветке `addedToSpacePayload` вместо `_onboarding_card` в группу — вызвать `onboard_space_members`, отправить анкету в DM (для `dm`) и @упоминание в группу (для `mention`).

```python
if "addedToSpacePayload" in chat_data:
    space_name = chat_data["addedToSpacePayload"].get("space", {}).get("name", "")
    async with AsyncSessionLocal() as db:
        await get_or_create_config(db, "space_id", space_name)  # зафиксировать группу
        plan = await onboard_space_members(db, space_name)
    # DM: анкета в личку
    for ws in plan["dm"]:
        from app.messaging import send_message
        send_message(ws, MessagePayload(text="Привет! Заполни короткую анкету 🙌", card=_onboarding_card("друг")))
    # упоминания
    if plan["mention"]:
        mentions = " ".join(f"<{m.replace('users/', '')}>" for m in plan["mention"])
        send_message(space_name, MessagePayload(text=f"{mentions} — напишите мне в личку, чтобы пройти анкету 👋"))
    return JSONResponse(content={})
```

- [ ] **Step 4: Запустить юнит-тест**

Run: `venv/Scripts/python.exe -m pytest tests/test_onboarding_units.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/space_onboarding.py app/api/google_chat.py tests/test_onboarding_units.py
git commit -m "feat: онбординг в личку при добавлении в группу"
```

---

## Self-Review (заметки исполнителю)

- Спек покрывает пп. 1–11. Задачи: Task 1 (схема), Task 2 (выбор времени), Task 3 (парсинг), Task 4 (сабмит), Task 5 (карточка), Task 6 (джобы), Task 7 (вебхук), Task 8 (онбординг).
- Перед стартом убедись, что `app/services/form_parsing.py` создан (Task 3) и импортируется в `weekly_poll.py` и `onboarding_answers.py` без циклических импортов.
- В Task 6 следи, что `send_message`/`MessagePayload`/`get_settings` импортированы в `scheduler.py` (часть уже есть в `weekly_poll.py`).
- `resolve_day_result` детерминирован: `sorted(meetings)` гарантирует стабильный порядок.
- При прогоне интеграционных скриптов используй `APP_ENV=production`, чтобы не спамить SQL-лог.
