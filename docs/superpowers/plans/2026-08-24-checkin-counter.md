# Check-in с счётчиком отметившихся — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Карточка check-in обновляется на месте со счётчиком отметившихся; окно отметки — от начала встречи до `scheduled_end + 15 мин`.

**Architecture:** `checkin.py` — новое окно (`start..end+15`) и `submit_checkin` с возвратом счётчика; `build_checkin_card` со счётчиком; вебхук возвращает `updateMessageAction` (внутри окна) или пустой ответ (вне); `invites.py` — джоб открытия карточки в `scheduled_start`, закрытия в `scheduled_end + 15`.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy 2 async, Google Chat add-on, pytest.

## Global Constraints

- Окно check-in: `[scheduled_start, scheduled_end + after_min]`, `after_min=15`.
- Длительность встречи — `config["meeting_duration_minutes"]` (default 60).
- До начала встречи карточку не шлём, отметку не засчитываем.
- Внутри окна клик → `attendance.status=present` → карточка обновляется (`updateMessageAction`) со счётчиком `present` для встречи. Текста в чат нет.
- Вне окна → пустой ответ (`JSONResponse(content={})`), счётчик не растёт.
- Счётчик = количество `attendance` со `status='present'` для `meeting_instance_id`.
- Напоминание о встрече (T−1ч) — НЕ трогаем.

---

## File Structure

- **`app/services/checkin.py`** — `checkin_window`, `build_checkin_card`, `submit_checkin`.
- **`app/services/invites.py`** — джобы открытия/закрытия check-in окна.
- **`app/api/google_chat.py`** — `_handle_checkin_present` → `updateMessageAction`/пустой.
- **`tests/test_eng7_units.py`** — юниты `checkin_window`/`build_checkin_card`.
- **`tests/e2e/test_jobs.py`** — интеграционный `submit_checkin` (count/within).
- **`tests/e2e/test_daily_poll.py`** — e2e вебхука check-in (обновление карточки).

---

### Task 1: Окно (start..end+15) и счётчик в `submit_checkin`

**Files:**
- Modify: `app/services/checkin.py`
- Test: `tests/test_eng7_units.py`, `tests/e2e/test_jobs.py`

**Interfaces:**
- Produces:
  - `checkin_window(scheduled_start: datetime, scheduled_end: datetime, after_min: int = 15) -> tuple[datetime, datetime]`
  - `submit_checkin(db, profile, instance_id, after_min: int = 15) -> dict` — возвращает `{"ok": True, "within": bool, "count": int}` (или `{"ok": False, "reason": "no_meeting", "within": False, "count": 0}`).

- [ ] **Step 1: Написать падающие тесты**

В `tests/test_eng7_units.py` заменить `test_checkin_window`:

```python
def test_checkin_window_starts_at_meeting_start():
    start = datetime(2026, 8, 24, 19, 0, tzinfo=timezone.utc)
    end = datetime(2026, 8, 24, 20, 0, tzinfo=timezone.utc)
    open_at, close_at = checkin_window(start, end)
    assert open_at == start
    assert close_at == end + timedelta(minutes=15)
```

В `tests/e2e/test_jobs.py` обновить `test_checkin_within_window_marks_present` (добавить `scheduled_end` в meeting и проверить count):

```python
async def test_checkin_within_window_marks_present(db, today_poll):
    p = await get_or_create_profile(db, "users/e2e_checkin")
    meeting = await _make_meeting(db, today_poll, datetime.now(timezone.utc))
    result = await submit_checkin(db, p, meeting.id, after_min=15)
    assert result["within"] is True
    assert result["count"] == 1
```

- [ ] **Step 2: Запустить — убедиться, что падают**

Run: `./venv/Scripts/python.exe -m pytest tests/test_eng7_units.py -q`
Expected: FAIL — `checkin_window` теперь принимает 2 аргумента.

- [ ] **Step 3: Реализовать**

В `app/services/checkin.py`:

Заменить импорт sqlalchemy (добавить `func`) и `checkin_window`:

```python
from sqlalchemy import func, select
```

```python
def checkin_window(scheduled_start: datetime, scheduled_end: datetime, after_min: int = 15) -> tuple[datetime, datetime]:
    """Окно check-in: от начала встречи до конца + after_min минут."""
    return (scheduled_start, scheduled_end + timedelta(minutes=after_min))
```

Заменить `submit_checkin`:

```python
async def submit_checkin(db: AsyncSession, profile: Profile, instance_id: int, after_min: int = 15) -> dict:
    """Записать self-check-in, только если сейчас в окне встречи (start..end+after_min)."""
    meeting = (
        await db.execute(select(MeetingORM).where(MeetingORM.id == instance_id, MeetingORM.status == "scheduled"))
    ).scalar_one_or_none()
    if meeting is None:
        return {"ok": False, "reason": "no_meeting", "within": False, "count": 0}

    open_at, close_at = checkin_window(meeting.scheduled_start, meeting.scheduled_end, after_min)
    now = datetime.now(timezone.utc)
    within = is_within_window(now, open_at, close_at)

    attendance = (
        await db.execute(select(Attendance).where(
            Attendance.profile_id == profile.id,
            Attendance.meeting_instance_id == instance_id,
        ))
    ).scalar_one_or_none()
    if attendance is None:
        attendance = Attendance(
            profile_id=profile.id,
            meeting_instance_id=instance_id,
            source="self_checkin",
            status="present" if within else "pending",
            checkin_attempted_at=now,
            is_within_window=within,
        )
        db.add(attendance)
    else:
        attendance.checkin_attempted_at = now
        attendance.is_within_window = within
        if within:
            attendance.status = "present"

    await db.commit()
    count = (
        await db.execute(
            select(func.count()).select_from(Attendance).where(
                Attendance.meeting_instance_id == instance_id,
                Attendance.status == "present",
            )
        )
    ).scalar_one()
    logger.info("checkin_submitted profile=%s instance=%s within=%s", profile.id, instance_id, within)
    return {"ok": True, "within": within, "count": count}
```

- [ ] **Step 4: Запустить — убедиться, что проходят**

Run: `./venv/Scripts/python.exe -m pytest tests/test_eng7_units.py tests/e2e/test_jobs.py -m "e2e or not e2e" -q`
Expected: PASS (также поправить `test_checkin_outside_window_stays_pending` — с новым окном «вне» достигается `scheduled_start = now - 2h`).

Примечание: в `test_checkin_outside_window_stays_pending` встреча уже в прошлом (`now - 1h`), но `scheduled_end` по умолчанию из `_make_meeting` = `start + 1h`, поэтому окно = `start..start+1h+15` — для `now` (сейчас) это «вне окна». Тест остаётся валидным без правок.

- [ ] **Step 5: Commit**

```bash
git add app/services/checkin.py tests/test_eng7_units.py tests/e2e/test_jobs.py
git commit -m "feat(checkin): window is meeting start..end+15, submit returns count" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Карточка со счётчиком

**Files:**
- Modify: `app/services/checkin.py`
- Test: `tests/test_eng7_units.py`

**Interfaces:**
- Produces: `build_checkin_card(instance_id: str, action_url: str = "", count: int = 0) -> dict` — карточка со строкой «Отметились: N».

- [ ] **Step 1: Написать падающий тест**

В `tests/test_eng7_units.py`:

```python
def test_build_checkin_card_has_count():
    card = build_checkin_card("7", action_url="https://x/hook", count=3)
    sections = card["cardsV2"][0]["card"]["sections"]
    assert sections[0]["widgets"][0]["textParagraph"]["text"] == "Отметились: 3"
    button = sections[1]["widgets"][0]["buttonList"]["buttons"][0]
    assert button["text"] == "Я на встрече ✅"
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `./venv/Scripts/python.exe -m pytest tests/test_eng7_units.py -q`
Expected: FAIL — карточка не имеет секции «Отметились».

- [ ] **Step 3: Реализовать**

В `app/services/checkin.py` заменить `build_checkin_card`:

```python
def build_checkin_card(instance_id: str, action_url: str = "", count: int = 0) -> dict:
    """Карточка с кнопкой «Я на встрече ✅» и счётчиком отметившихся."""
    return {
        "cardsV2": [
            {
                "cardId": "checkin",
                "card": {
                    "header": {"title": "Встреча началась? 🎉", "subtitle": "Отметься, чтобы получить баллы"},
                    "sections": [
                        {"widgets": [{"textParagraph": {"text": f"Отметились: {count}"}}]},
                        {"widgets": [{"buttonList": {"buttons": [
                            {
                                "text": "Я на встрече ✅",
                                "onClick": {"action": {
                                    "function": action_url or "checkin_submit",
                                    "parameters": [
                                        {"key": "method", "value": "checkin_present"},
                                        {"key": "instance", "value": str(instance_id)},
                                    ],
                                }},
                            }
                        ]}}]},
                    ],
                },
            }
        ]
    }
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `./venv/Scripts/python.exe -m pytest tests/test_eng7_units.py -q`
Expected: PASS (существующий `test_build_checkin_card_button_function_is_url` продолжает работать — кнопка во второй секции).

Примечание: `test_build_checkin_card_button_function_is_url` ссылается на `sections[0]` для кнопки — обновить на `sections[1]` (как в фиче голосования).

- [ ] **Step 5: Commit**

```bash
git add app/services/checkin.py tests/test_eng7_units.py
git commit -m "feat(checkin): show count of attendees on card" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Вебхук — обновление карточки вместо текста

**Files:**
- Modify: `app/api/google_chat.py`
- Test: `tests/e2e/test_daily_poll.py`

**Interfaces:**
- Consumes: `submit_checkin` (Task 1), `build_checkin_card` (Task 2), `_addon_update_message` (из фичи голосования).
- Produces: `_handle_checkin_present(chat_data, common) -> JSONResponse`.

- [ ] **Step 1: Написать падающий e2e-тест**

В `tests/e2e/test_daily_poll.py` добавить (фикстуры `client`, `db`, `today_poll`):

```python
async def test_checkin_updates_card(client, db, today_poll):
    from app.models import MeetingInstance, PollSlot
    from sqlalchemy import select
    slot = (await db.execute(select(PollSlot).where(PollSlot.poll_id == today_poll.id).limit(1))).scalar_one()
    from datetime import datetime, timezone, timedelta
    m = MeetingInstance(poll_id=today_poll.id, selected_slot_id=slot.id,
                        scheduled_start=datetime.now(timezone.utc),
                        scheduled_end=datetime.now(timezone.utc) + timedelta(hours=1),
                        location="Онлайн (Meet)", status="scheduled")
    db.add(m); await db.flush()

    ev = {
        "type": "CARD_CLICKED",
        "user": {"name": "users/e2e_checkin_web", "displayName": "E2E", "email": "e2e@example.com"},
        "space": {"name": "spaces/e2e_dm", "type": "DM"},
        "message": {"name": "spaces/e2e_msg/messages/1"},
        "action": {"function": "https://x/hook", "parameters": [
            {"key": "method", "value": "checkin_present"},
            {"key": "instance", "value": str(m.id)},
        ]},
        "common": {"formInputs": {}},
    }
    resp = await client.post("/webhooks/google-chat", json=ev)
    assert resp.status_code == 200
    body = resp.json()
    assert "updateMessageAction" in body["hostAppDataAction"]["chatDataAction"]
    msg = body["hostAppDataAction"]["chatDataAction"]["updateMessageAction"]["message"]
    text = msg["cardsV2"][0]["card"]["sections"][0]["widgets"][0]["textParagraph"]["text"]
    assert "Отметились: 1" in text
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run (нужен перезапуск uvicorn): `./venv/Scripts/python.exe -m pytest tests/e2e/test_daily_poll.py::test_checkin_updates_card -m e2e -q`
Expected: FAIL — ответ всё ещё `createMessageAction` с текстом.

- [ ] **Step 3: Реализовать**

В `app/api/google_chat.py` заменить `_handle_checkin_present`:

```python
async def _handle_checkin_present(chat_data: dict, common: dict) -> JSONResponse:
    """Кнопка «Я на встрече»: self-check-in в окне → обновить карточку счётчиком."""
    params = common.get("parameters") or {}
    instance_id = str(params.get("instance", ""))
    user = chat_data.get("user", {})
    workspace_user_id = user.get("name", "")
    message_name = (chat_data.get("buttonClickedPayload", {}).get("message") or {}).get("name")
    result = {"ok": False, "within": False, "count": 0}
    if workspace_user_id and instance_id.isdigit():
        try:
            from app.services.checkin import build_checkin_card, submit_checkin

            async with AsyncSessionLocal() as db:
                profile = await get_or_create_profile(db, workspace_user_id=workspace_user_id)
                result = await submit_checkin(db, profile, int(instance_id))
        except Exception:
            logger.exception("checkin_submit_failed")
    if result.get("within") and message_name:
        card = build_checkin_card(instance_id, settings.chat_app_audience, result.get("count", 0))
        return _addon_update_message(message_name, card)
    return JSONResponse(content={})
```

Обновить два вызова `_handle_checkin_present` (add-on и classic) — они уже `return _addon_response(...)`; заменить на `return await _handle_checkin_present(...)`:

add-on ветка:

```python
            if method == "checkin_present":
                return await _handle_checkin_present(chat_data, common)
```

classic ветка (заменить весь блок `if function_name == "checkin_submit" or method == "checkin_present":`):

```python
        if function_name == "checkin_submit" or method == "checkin_present":
            user = event.get("user", {})
            space_name = event.get("space", {}).get("name", "")
            params = action.get("parameters") or {}
            instance_id = ""
            for p in params:
                if isinstance(p, dict) and p.get("key") == "instance":
                    instance_id = p.get("value", "")
            response_msg = await _handle_checkin_present(
                {"user": user, "space": {"name": space_name}},
                {"parameters": {"instance": instance_id}},
            )
            return response_msg
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `./venv/Scripts/python.exe -m pytest tests/e2e/test_daily_poll.py -m e2e -q`
Expected: PASS (новый тест зелёный; остальные не затронуты).

- [ ] **Step 5: Commit**

```bash
git add app/api/google_chat.py tests/e2e/test_daily_poll.py
git commit -m "feat(checkin): update card in place on check-in" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Джоб открытия карточки в момент начала

**Files:**
- Modify: `app/services/invites.py`

- [ ] **Step 1: Реализовать**

В `handle_time_finalized` заменить блок джобов check-in:

```python
        duration = int(await _config_value(db, "meeting_duration_minutes", 60) or 60)
        scheduled_end = scheduled_start + timedelta(minutes=duration)
        open_at, close_at = checkin_window(scheduled_start, scheduled_end)
        sch.add_job(
            _open_checkin, "date", run_date=open_at,
            id=checkin_job_ids(str(instance_id))["open"], replace_existing=True,
            args=[space_id, build_checkin_card(str(instance_id), action_url=get_settings().chat_app_audience)],
        )
        sch.add_job(
            _close_checkin, "date", run_date=close_at,
            id=checkin_job_ids(str(instance_id))["close"], replace_existing=True,
        )
```

(заменяет текущие `window_min`/`open_at`/`close_at` строки; `timedelta` уже импортирован в `invites.py`).

- [ ] **Step 2: Запустить юниты и e2e**

Run: `./venv/Scripts/python.exe -m pytest -q` → юниты зелёные.
Run: `./venv/Scripts/python.exe -m pytest -m e2e -q` → e2e зелёные.

- [ ] **Step 3: Ручная проверка**

1. Создать встречу со `scheduled_start` = сейчас.
2. Вызвать `handle_time_finalized` (или дождаться джоба) → карточка check-in приходит в момент начала.
3. Клик «Я на встрече ✅» → карточка перерисовывается: «Отметились: 1».
4. Второй клик другим аккаунтом → «Отметились: 2».

- [ ] **Step 4: Commit**

```bash
git add app/services/invites.py
git commit -m "feat(checkin): open check-in card at meeting start, close end+15" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```
