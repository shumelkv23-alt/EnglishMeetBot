# Распараллеленный план: 4 задачи одной итерации (v2)

> Дата: 2026-08-20. Версия контракта: **2.0**.
> Участники: Кирилл (ENG-5, ENG-7, интеграция), Тиммейт A (ENG-8), Тиммейт B (ENG-6).
> Всё, что нужно для старта, уже в `main`. Ветки не пересекаются по файлам → конфликтов нет.

---

## 1. Схема: кто что делает параллельно

| Задача | Владелец | Файлы (только эти!) | Начинать | Зависит от |
|---|---|---|---|---|
| **ENG-5** — еженедельный опрос + голосование за слоты (REQ-2, REQ-3.1–3.2) | Кирилл | `app/services/question_bank.py`, `app/services/weekly_poll.py`, правки `app/api/google_chat.py`, `app/scheduler.py` | **сейчас** | ни от кого (базис готов) |
| **ENG-6** — выбор слота и статусы (REQ-3.3–3.5, REQ-9) | Тиммейт B | `app/scheduling.py`, `tests/test_scheduling.py` | сейчас | schemas + messaging |
| **ENG-7** — приглашения, напоминания, check-in окно (REQ-5, REQ-6.2, REQ-9.2–9.3) | Кирилл | `app/services/invites.py`, `app/services/reminders.py`, `app/services/checkin.py`, `app/scheduler.py` | сейчас (каркас) | сигнатуры ENG-6, ENG-8 (заморожены контрактом) |
| **ENG-8** — активности «Мини-дайджест» и «Угадай коллегу» (REQ-4.2) | Тиммейт A | `app/activities.py`, `tests/test_activities.py` | сейчас | schemas |

**Ключевой принцип:** все четыре задачи развязаны **замороженными сигнатурами** из
`app/schemas.py` + `app/messaging.py` (уже в main). Каждый пишет против контракта,
а не против кода соседа. Никто никого не ждёт.

---

## 2. Базис (уже в `main`, все начинают с `git pull`)

- `app/schemas.py` — доменные модели: `MeetingStatus`, `Slot`, `MeetingInstance`, `WeeklyAnswer`, `Activity`, `MessagePayload`. Плюс webhook-схемы.
- `app/messaging.py` — **синхронный** стаб `send_message(user_id, payload)` (пишет в лог). Реальный вызов Chat API Кирилл подключит позже, сигнатура не изменится.
- `requirements.txt` (+ pytest==8.2.2), `pytest.ini` (`pythonpath = .` — тесты работают из корня).
- БД с миграциями (10 таблиц): `weekly_polls`, `poll_slots`, `poll_votes`, `poll_responses`, `meeting_instances`, `answers`, `attendance` и др. + триггеры счётчиков. Upsert-ограничения уже в БД: `poll_votes(profile_id, poll_slot_id)` unique, `poll_responses(profile_id, poll_id)` unique.
- `app/services/chat_sender.py` — рабочий отправитель через service account (для будущей реальной `send_message`; по контракту сейчас никто не трогает).

**Правила данных (общие):**
- `user_id` везде — строка `"users/..."` (workspace_user_id из Google Chat), не email и не int.
- Все `datetime` — timezone-aware UTC.
- Доменные модели ≠ ORM: ребята работают с `schemas.py`, Кирилл — единственный, кто строит мост БД → доменные модели.

---

## 3. Контракт v2 — что изменилось по сравнению с v1

1. **`advance_state` (ENG-6) — ЧИСТАЯ функция, сообщения НЕ отправляет.** Возвращает инстанс с новым статусом — и всё. Все уведомления после голосования (личные приглашения, Space-пост, напоминание, эскалация организатору) — зона ENG-7 (Кирилл). Это убирает двойные сообщения и совпадает с REQ-9.5 («участникам ничего не уходит» при эскалации).
2. **Формулу дедлайна считает Кирилл (ENG-5)**, не Тиммейт B: `deadline = самый ранний слот − буфер` (REQ-2.3, буфер настраивается в `config`). `advance_state` принимает `instance.deadline` готовым.
3. Остальное как в v1: `MIN_QUORUM = 3`, tie-break «раньше по (день недели, время)» (Mon=0…Sun=6, затем строка `"HH:MM"`), идемпотентность (не-VOTING → без изменений), новый инстанс через `model_copy(update=...)`.

---

## 4. ENG-6 (Тиммейт B): суть задачи

```python
from datetime import datetime, timezone

from app.schemas import MeetingInstance, Slot, MeetingStatus

MIN_QUORUM = 3  # минимум голосов за слот, чтобы встреча состоялась


def select_slot(instance: MeetingInstance) -> Slot | None:
    """Слот с максимумом голосов; при ничьей — раньше по (день недели, время).
    Нет слотов или все без голосов — None."""


def advance_state(instance: MeetingInstance) -> MeetingInstance:
    """Чистая функция, НИЧЕГО не отправляет (уведомления — ENG-7).

    voting -> time_finalized (дедлайн прошёл И кворум набран)
           -> escalated (дедлайн прошёл И кворум не набран)
    Прочие статусы и до дедлайна — возвращает как есть.
    """
```

**Поведение:**
- `select_slot`: максимум `len(votes)`; ничья → (порядок дня, `time`); 0 голосов у всех → `None`.
- `advance_state`: `status != VOTING` → вернуть как есть; `now < deadline` → как есть;
  после дедлайна — `TIME_FINALIZED` + `final_slot_id` при `len(selected.votes) >= MIN_QUORUM`,
  иначе `ESCALATED`. Новый объект через `instance.model_copy(update={...})`.

**Тесты** (`tests/test_scheduling.py`), без моков и сети:
- выбор по максимуму голосов; ничья → ранний день; все без голосов → `None`;
- до дедлайна ничего не меняется; после дедлайна с кворумом → `TIME_FINALIZED` + `final_slot_id`;
- после дедлайна без кворума → `ESCALATED`; статус `TIME_FINALIZED` на входе → без изменений.

**Нельзя:** трогать `schemas.py`, `messaging.py`, `pytest.ini`, чужие файлы; добавлять поля в модели (не хватает — пиши Кириллу, он расширит PR-ом); вызывать сеть/БД/`asyncio`.

**Критерий готовности:** `.\venv\Scripts\pytest tests\test_scheduling.py -q` → зелёное; в PR только 2 файла.

---

## 5. ENG-8 (Тиммейт A): суть задачи

```python
from app.schemas import WeeklyAnswer, Activity


def generate_activity(answers: list[WeeklyAnswer]) -> Activity:
    """Чистая функция. Без сети, БД и отправки."""
```

**Поведение:**

| Случай | Результат |
|---|---|
| пустой список | `Activity(type="digest", ...)` с пустым `items` — без исключений |
| 2+ ответов | `digest`: `content = {"kind": "digest", "title": "Мини-дайджест недели", "items": [{"user": user_id, "text": answer_text}, ...]}` |
| (по своему правилу) | `guess_colleague`: `content = {"kind": "guess_colleague", "question": question_id, "answer": answer_text, "author_user_id": user_id}` — один случайный ответ недели |

**Тесты** (`tests/test_activities.py`):
- пустой список → digest с пустыми items;
- `type` ∈ {"digest", "guess_colleague"};
- digest содержит все ответы из входа;
- у guess: `answer` и `author_user_id` принадлежат входным данным (тест не зависит от рандома → не флакает).

**Нельзя:** трогать чужие файлы; обращаться к БД/отправке; фильтровать по приватности — это делает адаптер Кирилла (REQ-4.3).

**Критерий готовности:** `.\venv\Scripts\pytest tests\test_activities.py -q` → зелёное; в PR только 2 файла.

---

## 6. ENG-5 (Кирилл): еженедельный опрос и голосование (REQ-2, REQ-3.1–3.2)

Куски, каждый — со своей проверкой:

1. **Банк вопросов** (`app/services/question_bank.py`):
   константный список лёгких вопросов + функция выбора вопроса недели без повторов
   (в `answers.question_rotation_id` уже хранится номер вопроса — берём следующий свободный индекс).
   → проверка: юнит-тест «повторов нет N недель подряд».
2. **Карточка опроса** (`app/services/weekly_poll.py`): Cards V2 по образцу онбординга —
   блок 1–2 вопросов (textInput) + блок чекбоксов слотов недели (из `poll_slots`).
3. **Рассылка** (`app/scheduler.py`, APScheduler): раз в неделю (день/час в `config`) —
   активным профилям (`is_active`, `onboarding_completed`) в DM через `send_message(...)`;
   создание `WeeklyPoll` + `poll_responses` (status=pending). → проверка: в БД появился опрос.
4. **Приём ответов** (ветка в `app/api/google_chat.py`): клик «Отправить» по карточке опроса →
   текстовые ответы → `answers` (история), отмеченные слоты → `poll_votes` (upsert;
   unique-ограничение уже в БД). → проверка: повторный сабмит не дублирует голоса.
5. **Дедлайн и инстанс** (`app/services/weekly_poll.py`): `deadline = min(слоты) − буфер(из config)`;
   адаптер `WeeklyPoll → MeetingInstance` (со слотами и голосами) — интерфейс под ENG-6.
6. **Жёсткий стоп голосования:** после `deadline` пришедшие голоса не учитываются (REQ-9.4).

Локальная проверка без Google: uvicorn с `SKIP_JWT_VALIDATION=true`, curl-вебхук
с фейковым событием (паттерн из PLAN.md, этап 1.5).

---

## 7. ENG-7 (Кирилл): приглашения и напоминания (REQ-5, REQ-6.2, REQ-9)

Пишется против замороженных сигнатур ENG-6 (`advance_state`) и ENG-8 (`generate_activity`).
Каркас — сейчас; стыковка — после их мержей.

1. **Личные приглашения** (`app/services/invites.py`): событие `TIME_FINALIZED` →
   `send_message` каждому участнику: время (`final_slot`) + тема (из `Activity` от ENG-8).
2. **Пост в Space** (`app/services/invites.py`): одно сообщение с итоговым временем и темой (REQ-5.2).
3. **Calendar-событие с Meet-ссылкой** (REQ-5/REQ-3.7): **заглушка** — требует domain-wide
   delegation и админа (Фаза B из PLAN.md). В MVP делаем интерфейс + TODO, не интеграцию.
4. **Напоминание T−1ч** (`app/services/reminders.py`): отложенная задача с ETA;
   ключ `meeting_instance_id + message_type`, повтор → перезапись, не дубль (REQ-9.2);
   при изменении времени — старые задачи отменяются и пересоздаются (REQ-9.3).
5. **Окно self-check-in** (`app/services/checkin.py`): две отложенные задачи от `TIME_FINALIZED`:
   открыть кнопку «Я на встрече ✅» за 15 мин до, закрыть через 15 мин после (REQ-9.6).
   Клики по кнопке — ветка в `app/api/google_chat.py`, поэтому **мержится после ENG-5**
   (оба трогают вебхук — избегаем конфликта своих же веток).
6. **Эскалация организатору** (REQ-9.5, REQ-3.5): при `ESCALATED` — одно сообщение
   ответственному (id из `config`). Участникам — ничего.

---

## 8. Тестирование без доступа к боту (для Тиммейтов A и B)

Бот им не нужен: чистые функции + стаб `send_message` (логирует). Команды с нуля:

```powershell
git clone <url-репо> english-meet-bot
cd english-meet-bot
git checkout main; git pull
python -m venv venv
.\venv\Scripts\pip install -r requirements.txt
.\venv\Scripts\pytest tests -q    # из корня проекта, pytest.ini уже настроен
```

Импорт `app.*` работает благодаря `pytest.ini` (pythonpath). БД, токены, ngrok — не их забота.

---

## 9. Порядок интеграции (Кирилл, после мержей)

| Шаг | Что | Зависимость |
|---|---|---|
| 1 | Мерж PR B (ENG-6) в main | B сдал + тесты зелёные |
| 2 | Мерж PR A (ENG-8) в main | A сдал + тесты зелёные |
| 3 | `app/services/voting.py`: heartbeat-джоб → собирает `MeetingInstance` из БД (ENG-5 адаптер) → `advance_state` (ENG-6) → сохраняет статус/`final_slot_id` | шаги 1, ENG-5 |
| 4 | Запуск ENG-7 по `TIME_FINALIZED`/`ESCALATED` | шаги 1–3 |
| 5 | Реальная `send_message`: стаб → `services/chat_sender.py` (+ резолв DM через `find_user_dm_space`) | после шага 4 |
| 6 | E2E в живом Google Chat | всё |

Ветки: `feature/english-6-scheduling` (B), `feature/english-8-activities` (A),
`feature/english-5-weekly-poll`, `feature/english-7-invites` (Кирилл, мержатся в этом порядке:
ENG-5 → ENG-7, т.к. оба могут касаться вебхука).

---

## 10. Чек-лист перед PR (для всех)

1. Прогнал свои тесты — зелёные.
2. Изменены только файлы твоей строки из таблицы раздела 1.
3. `git add` — только своих файлов (`git add .` / `-A` запрещены).
4. Ветка от свежего `main`; PR с указанием прогнанных тестов.
5. Если контракт (schemas/messaging) обновил Кирилл — `git merge main` в свою ветку
   (конфликтов нет, ты не трогаешь общие файлы) и перепроверь тесты.

**Вопросы, нехватка полей, споры — в общий чат, не в код.**