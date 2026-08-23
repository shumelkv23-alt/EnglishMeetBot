# Голосование с живыми счётчиками — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ежедневный опрос обновляет карточку на месте (счётчики голосов), вместо спама «Спасибо, учёл!» на каждый клик.

**Architecture:** Карточка опроса получает секцию со счётчиками; при клике кнопки бот сохраняет голос через существующий `submit_poll`, читает свежие счётчики из `poll_slots.votes_count` + число `not_available`, и возвращает `updateMessageAction` с перерисованной карточкой.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy 2 async, Google Chat add-on (`hostAppDataAction.chatDataAction`), pytest + pytest-asyncio.

## Global Constraints

- Формат ответа — add-on: `hostAppDataAction.chatDataAction.{createMessageAction|updateMessageAction}`.
- `updateMessageAction.message` должен содержать `name` (id сообщения) и `cardsV2`.
- `message.name` приходит в событии клика: add-on — `chat.buttonClickedPayload.message.name`; classic — `event.message.name`.
- Переголос «одно время на человека» (существующий `submit_poll`) — НЕ менять.
- Финализация (14:05) и структура БД — НЕ менять.
- Персонального «твой выбор» нет (карточка общая на группу).
- Слоты опроса — `15:00`, `16:00`, `17:00` + `not_available`.

---

## File Structure

- **`app/services/weekly_poll.py`** — чистая логика опроса: `build_daily_poll_card` (карточка со счётчиками), `poll_counts` (чтение счётчиков).
- **`app/api/google_chat.py`** — вебхук: `_addon_update_message` (обёртка update), `_submit_daily_poll` (вернуть update), передача `message.name`.
- **`tests/test_daily_poll_units.py`** — юнит-тесты `build_daily_poll_card`.
- **`tests/e2e/test_jobs.py`** — интеграционный тест `poll_counts` (реальная БД).
- **`tests/test_google_chat_units.py`** — юнит-тест `_addon_update_message` (новый файл).
- **`tests/e2e/test_daily_poll.py`** — e2e: клик возвращает `updateMessageAction`.

---

### Task 1: Карточка со счётчиками (`build_daily_poll_card`)

**Files:**
- Modify: `app/services/weekly_poll.py` (функция `build_daily_poll_card`)
- Test: `tests/test_daily_poll_units.py`

**Interfaces:**
- Produces: `build_daily_poll_card(slots: list[str], action_url: str, counts: dict[str, int] | None = None) -> dict` — counts без ключа или `None` дают нули.

- [ ] **Step 1: Написать падающий тест**

В `tests/test_daily_poll_units.py` добавить:

```python
def test_build_daily_poll_card_shows_counts():
    card = build_daily_poll_card(
        ["15:00", "16:00", "17:00"],
        "https://x/hook",
        {"15:00": 4, "16:00": 2, "17:00": 1, "not_available": 0},
    )
    sections = card["cardsV2"][0]["card"]["sections"]
    counts_text = sections[0]["widgets"][0]["textParagraph"]["text"]
    assert "15:00 — 4" in counts_text
    assert "16:00 — 2" in counts_text
    assert "Не могу — 0" in counts_text
    # кнопки остались во второй секции
    buttons = sections[1]["widgets"][0]["buttonList"]["buttons"]
    assert [b["text"] for b in buttons] == ["15:00", "16:00", "17:00", "Не могу сегодня"]


def test_build_daily_poll_card_defaults_to_zero():
    card = build_daily_poll_card(["15:00"], "https://x/hook")
    text = card["cardsV2"][0]["card"]["sections"][0]["widgets"][0]["textParagraph"]["text"]
    assert "15:00 — 0" in text
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `./venv/Scripts/python.exe -m pytest tests/test_daily_poll_units.py -q`
Expected: FAIL — карточка не имеет секции `textParagraph` со счётчиками.

- [ ] **Step 3: Реализовать**

В `app/services/weekly_poll.py` заменить функцию `build_daily_poll_card`:

```python
def build_daily_poll_card(slots: list[str], action_url: str, counts: dict[str, int] | None = None) -> dict:
    """Карточка ежедневного опроса: счётчики голосов + кнопки.

    counts — {"15:00": N, ..., "not_available": N}; None → все нули.
    """
    counts = counts or {}
    lines = [f"{t} — {counts.get(t, 0)}" for t in slots]
    lines.append(f"Не могу — {counts.get('not_available', 0)}")

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
                "sections": [
                    {"widgets": [{"textParagraph": {"text": "\n".join(lines)}}]},
                    {"widgets": [{"buttonList": {"buttons": buttons}}]},
                ],
            },
        }]
    }
```

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

Run: `./venv/Scripts/python.exe -m pytest tests/test_daily_poll_units.py -q`
Expected: PASS (существующие тесты `test_build_daily_poll_card_has_four_buttons` тоже зелёные — они проверяют кнопки, которые остались во второй секции).

- [ ] **Step 5: Commit**

```bash
git add app/services/weekly_poll.py tests/test_daily_poll_units.py
git commit -m "feat(poll): show vote counts in daily poll card"
```

---

### Task 2: Чтение счётчиков (`poll_counts`)

**Files:**
- Modify: `app/services/weekly_poll.py`
- Test: `tests/e2e/test_jobs.py`

**Interfaces:**
- Consumes: `PollSlot`, `PollResponse` (модели из `app.models`), `AsyncSession`.
- Produces: `poll_counts(db: AsyncSession, poll_id: int) -> tuple[list[str], dict[str, int]]` — возвращает `(slots, counts)`, где `slots` — время слотов по возрастанию, `counts` включает ключ `"not_available"`.

- [ ] **Step 1: Написать падающий тест**

В `tests/e2e/test_jobs.py` добавить (использует фикстуру `today_poll` из conftest):

```python
async def test_poll_counts_reflects_votes(db, today_poll):
    from app.services.weekly_poll import poll_counts

    p = await get_or_create_profile(db, "users/e2e_counts")
    await submit_poll(db, p, FORM_1500)  # голос за 15:00
    na = await get_or_create_profile(db, "users/e2e_counts_na")
    await submit_poll(db, na, {"time": {"stringInputs": {"value": ["not_available"]}}})

    slots, counts = await poll_counts(db, today_poll.id)
    assert slots == ["15:00", "16:00", "17:00"]
    assert counts["15:00"] == 1
    assert counts["16:00"] == 0
    assert counts["not_available"] == 1
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run (нужен поднятый uvicorn + БД):
```powershell
$env:SKIP_JWT_VALIDATION="true"; uvicorn app.main:app --port 8000
./venv/Scripts/python.exe -m pytest tests/e2e/test_jobs.py::test_poll_counts_reflects_votes -m e2e -q
```
Expected: FAIL — `poll_counts` не определён.

- [ ] **Step 3: Реализовать**

В `app/services/weekly_poll.py` заменить импорт sqlalchemy (добавить `func`) и добавить функцию:

```python
from sqlalchemy import delete, func, select
```

```python
async def poll_counts(db: AsyncSession, poll_id: int) -> tuple[list[str], dict[str, int]]:
    """Счётчики голосов опроса: (слоты по возрастанию, {время -> голоса} + not_available)."""
    slots = (
        await db.execute(select(PollSlot).where(PollSlot.poll_id == poll_id).order_by(PollSlot.slot_start))
    ).scalars().all()
    slot_times = [s.slot_start.strftime("%H:%M") for s in slots]
    counts = {t: (s.votes_count or 0) for t, s in zip(slot_times, slots)}
    na = (
        await db.execute(
            select(func.count()).select_from(PollResponse).where(
                PollResponse.poll_id == poll_id, PollResponse.status == "not_available"
            )
        )
    ).scalar_one()
    counts["not_available"] = na
    return slot_times, counts
```

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

Run: `./venv/Scripts/python.exe -m pytest tests/e2e/test_jobs.py::test_poll_counts_reflects_votes -m e2e -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/weekly_poll.py tests/e2e/test_jobs.py
git commit -m "feat(poll): add poll_counts to read vote tallies"
```

---

### Task 3: Обёртка обновления карточки (`_addon_update_message`)

**Files:**
- Modify: `app/api/google_chat.py`
- Test: `tests/test_google_chat_units.py` (новый файл)

**Interfaces:**
- Produces: `_addon_update_message(message_name: str, card: dict) -> JSONResponse` — возвращает `JSONResponse` с `updateMessageAction`.

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_google_chat_units.py`:

```python
from app.api.google_chat import _addon_update_message


def test_addon_update_message_structure():
    card = {"cardsV2": [{"cardId": "dailyPoll", "card": {}}]}
    resp = _addon_update_message("spaces/A/messages/B", card)
    body = resp.body  # JSONResponse.body — bytes
    import json
    data = json.loads(body)
    assert data == {
        "hostAppDataAction": {
            "chatDataAction": {
                "updateMessageAction": {
                    "message": {
                        "name": "spaces/A/messages/B",
                        "cardsV2": [{"cardId": "dailyPoll", "card": {}}],
                    }
                }
            }
        }
    }
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `./venv/Scripts/python.exe -m pytest tests/test_google_chat_units.py -q`
Expected: FAIL — `_addon_update_message` не определён.

- [ ] **Step 3: Реализовать**

В `app/api/google_chat.py` добавить (рядом с `_addon_response`):

```python
def _addon_update_message(message_name: str, card: dict) -> JSONResponse:
    """Ответ updateMessageAction: обновить карточку на месте (add-on формат)."""
    return JSONResponse(content={
        "hostAppDataAction": {
            "chatDataAction": {
                "updateMessageAction": {
                    "message": {
                        "name": message_name,
                        "cardsV2": card.get("cardsV2"),
                    }
                }
            }
        }
    })
```

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

Run: `./venv/Scripts/python.exe -m pytest tests/test_google_chat_units.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/api/google_chat.py tests/test_google_chat_units.py
git commit -m "feat(poll): add add-on updateMessageAction wrapper"
```

---

### Task 4: `_submit_daily_poll` возвращает обновление карточки

**Files:**
- Modify: `app/api/google_chat.py`
- Test: `tests/e2e/test_daily_poll.py`

**Interfaces:**
- Consumes: `poll_counts` (Task 2), `build_daily_poll_card` (Task 1), `_addon_update_message` (Task 3).
- Produces: `_submit_daily_poll(chat_data: dict, common: dict, message_name: str | None = None) -> JSONResponse` — успех при наличии `message_name` → `updateMessageAction`; иначе → `createMessageAction` с текстом.

- [ ] **Step 1: Написать падающий e2e-тест**

В `tests/e2e/test_daily_poll.py` обновить хелпер `_daily_poll_click` (добавить опциональный `message_name`) и добавить тест:

```python
def _daily_poll_click(user_id: str, time_value: str, message_name: str | None = None) -> dict:
    event = {
        "type": "CARD_CLICKED",
        "user": {"name": user_id, "displayName": "E2E", "email": "e2e@example.com"},
        "space": {"name": "spaces/e2e_dm", "type": "DM"},
        "action": {
            "function": "https://example.com/hook",
            "parameters": [
                {"key": "method", "value": "submit_daily_poll"},
                {"key": "time", "value": time_value},
            ],
        },
        "common": {"formInputs": {}},
    }
    if message_name:
        event["message"] = {"name": message_name}
    return event


async def test_submit_updates_card_with_counts(client, db, today_poll):
    resp = await client.post(
        "/webhooks/google-chat",
        json=_daily_poll_click("users/e2e_upd", "15:00", "spaces/e2e_msg/messages/1"),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "updateMessageAction" in body["hostAppDataAction"]["chatDataAction"]
    msg = body["hostAppDataAction"]["chatDataAction"]["updateMessageAction"]["message"]
    assert msg["name"] == "spaces/e2e_msg/messages/1"
    sections = msg["cardsV2"][0]["card"]["sections"]
    counts_text = sections[0]["widgets"][0]["textParagraph"]["text"]
    assert "15:00 — 1" in counts_text
```

Существующие тесты (`test_submit_slot_records_vote` и др.) вызывают `_daily_poll_click` без `message_name` — они продолжат получать текст-фолбэк «Спасибо, учёл!» и не сломаются.

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run (нужен поднятый uvicorn + БД): `./venv/Scripts/python.exe -m pytest tests/e2e/test_daily_poll.py::test_submit_updates_card_with_counts -m e2e -q`
Expected: FAIL — ответ всё ещё `createMessageAction` с текстом «Спасибо».

- [ ] **Step 3: Реализовать**

В `app/api/google_chat.py`:

Заменить функцию `_submit_daily_poll` целиком:

```python
async def _submit_daily_poll(chat_data: dict, common: dict, message_name: str | None = None) -> JSONResponse:
    """Обработать клик по кнопке ежедневного опроса.

    При успехе и наличии message_name — обновляет карточку счётчиками
    (updateMessageAction), иначе/при закрытии — текст (createMessageAction).
    """
    form_inputs = common.get("formInputs", {}) or {}
    params = common.get("parameters") or {}
    if isinstance(params, list):
        params = {p.get("key"): p.get("value") for p in params if isinstance(p, dict)}
    if not form_inputs and isinstance(params, dict) and params.get("time"):
        form_inputs = {"time": {"stringInputs": {"value": [str(params["time"])]}}}
    user = chat_data.get("user", {})
    workspace_user_id = user.get("name", "")
    result = {"ok": False, "reason": "no_user"}
    updated_card = None
    if workspace_user_id:
        try:
            space = _extract_space_dict(chat_data)
            async with AsyncSessionLocal() as db:
                profile = await get_or_create_profile(
                    db, workspace_user_id=workspace_user_id,
                    email=user.get("email"), display_name=user.get("displayName"),
                    chat_space_id=_dm_space_name(space),
                )
                from app.services.weekly_poll import (
                    active_daily_poll, build_daily_poll_card, poll_counts, submit_poll, today,
                )
                result = await submit_poll(db, profile, form_inputs)
                if result.get("ok") and message_name:
                    poll = await active_daily_poll(db, today())
                    if poll is not None:
                        slots, counts = await poll_counts(db, poll.id)
                        updated_card = build_daily_poll_card(
                            slots, settings.chat_app_audience, counts,
                        )
        except Exception:
            logger.exception("daily_poll_submit_failed")
            result = {"ok": False, "reason": "db_error"}
    if result.get("ok"):
        if updated_card is not None and message_name:
            return _addon_update_message(message_name, updated_card)
        return _addon_response({"text": "Спасибо, учёл! 🙌"})
    if result.get("reason") == "closed":
        return _addon_response({"text": "Голосование уже закрыто — итог объявлен."})
    return _addon_response({"text": "Не получилось сохранить — попробуй ещё раз."})
```

Обновить вызовы `_submit_daily_poll` на передачу `message_name`:

В add-on ветке (`if "buttonClickedPayload" in chat_data:`):

```python
            if method == "submit_daily_poll":
                message_name = (chat_data.get("buttonClickedPayload", {}).get("message") or {}).get("name")
                return await _submit_daily_poll(chat_data, common, message_name=message_name)
```

В classic ветке (`if function_name == "submit_daily_poll" or method == "submit_daily_poll":`):

```python
            message_name = (event.get("message") or {}).get("name")
            response_msg = await _submit_daily_poll(
                {"user": user, "space": space},
                {"formInputs": form_inputs, "parameters": params},
                message_name=message_name,
            )
            return response_msg
```

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

Run: `./venv/Scripts/python.exe -m pytest tests/e2e/test_daily_poll.py -m e2e -q`
Expected: PASS — новый тест зелёный, существующие (`test_submit_slot_records_vote`, `test_revote_keeps_single_vote`, `test_not_available_records_no_vote`, `test_submit_after_deadline_is_closed`) продолжают проходить (они не передают `message.name`, поэтому получают текст-фолбэк «Спасибо, учёл!»).

- [ ] **Step 5: Commit**

```bash
git add app/api/google_chat.py tests/e2e/test_daily_poll.py
git commit -m "feat(poll): update card in place on vote instead of new message"
```

---

### Task 5: Полный прогон и проверка в реальном чате

**Files:** нет (только проверка)

- [ ] **Step 1: Юнит-тесты**

Run: `./venv/Scripts/python.exe -m pytest -q`
Expected: все юниты зелёные (e2e/live deselected).

- [ ] **Step 2: E2E-тесты**

Run (поднятый uvicorn + БД): `./venv/Scripts/python.exe -m pytest -m e2e -q`
Expected: все e2e зелёные.

- [ ] **Step 3: Ручная проверка в чате**

1. `scripts/send_poll_now.py` → карточка с нулями в группе.
2. Клик «15:00» → карточка перерисовывается: «15:00 — 1», «спасибо» в чат НЕ приходит.
3. Клик «16:00» (переголос) → «15:00 — 0, 16:00 — 1».
4. Второй аккаунт кликает «16:00» → «16:00 — 2».

- [ ] **Step 4: Commit (если были правки по итогам ручной проверки)**

```bash
git add -A
git commit -m "chore(poll): polish live poll counts after manual check"
```
