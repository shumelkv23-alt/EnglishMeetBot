

# English Meet Bot — полный обзор проекта

> Назначение файла: за 30–40 минут понять, **что** делает бот, **как** устроен изнутри,
> **какие модули за что отвечают** и **как они взаимодействуют**. Писано для человека,
> который будет этот код читать и развивать.
>
> Актуально на: 2026-08-23. Всё, что ниже, сверено с исходным кодом (`app/`), миграциями
> (`alembic/`), планами (`PLAN.md`, `PARALLEL_PLAN.md`) и докой (`docs/`).

---

## 1. Что это и зачем

**English Meet Bot** — бот для **Google Chat**, который помогает команде организовывать
короткие разговорные встречи на английском. Он живёт как Chat-приложение в Google Workspace
и делает три вещи:

1. **Знакомится** с участниками через интерактивную анкету (онбординг).
2. **Ежедневно** спрашивает в группе «кто сегодня и во сколько?» и сам подводит итог —
   собирает встречу, если набрался кворум.
3. **Напоминает и отмечает присутствие**: приглашает ответивших, шлёт напоминание за час,
   раздаёт кнопку «Я на встрече ✅» (self-check-in).

Главная идея: **снять с организатора рутину**. Вместо «переписка → опрос → выбор времени →
напоминания» бот делает это сам по расписанию, а люди только нажимают кнопки в карточках.

### Стек

| Слой | Технология |
|------|------------|
| Язык | Python 3.11+ (проверено на 3.14) |
| Веб-фреймворк | FastAPI 0.111 + Uvicorn |
| БД | PostgreSQL 15 (async через `asyncpg`) |
| ORM | SQLAlchemy 2.0 (async), декларативный стиль |
| Миграции | Alembic |
| Планировщик | APScheduler 3.10 (async, in-process) |
| Интеграция с Google | Chat REST API (`chat.bot`) + вебхук, `google-auth` (сервисный аккаунт) |
| LLM | OpenRouter (OpenAI-совместимый `/chat/completions`), модель `deepseek/deepseek-chat` |
| Деплой | Docker Compose + cloudflared (dev); Cloud Run — в планах |
| Тесты | pytest + pytest-asyncio |

---

## 2. Высокоуровневая картина: как устроен бот

Бот — это **веб-сервер FastAPI**, ко

торый Google Chat дёргает через HTTP-вебхук.
Есть два независимых канала связи:

```
                        ┌──────────────────────────────────────────────┐
                        │                 Google Chat                  │
                        └──────────────┬───────────────┬───────────────┘
                                       │               │
                     (1) вебхук:       │               │  (2) проактивные вызовы
                     события боту      │               │  Chat REST API от имени бота
                     (пользователь     ▼               ▼  (сервисный аккаунт, chat.bot)
                     пишет/жмёт)  ┌─────────┐     ┌──────────────┐
                                  │ FastAPI │     │ chat_sender  │
                                  │  app    │     │ (requests →  │
                                  │         │     │  chat.google │
                                  │         │     │  apis.com)   │
                                  └────┬────┘     └──────────────┘
                                       │
                          ┌────────────┼─────────────┐
                          │            │             │
                     ┌────▼────┐  ┌────▼─────┐  ┌────▼─────┐
                     │ services│  │ scheduler │  │  Postgres│
                     │ (логика)│  │(APScheduler│  │ (SQLAlchemy│
                     │         │  │  cron/date│  │  async)  │
                     └────┬────┘  └──────────┘  └──────────┘
                          │
                     ┌────▼─────┐
                     │ messaging │  ← единственная граница между логикой и отправкой
                     └──────────┘
```

Два канала:

- **(1) Вебхук** — Google присылает события, когда пользователь пишет боту, добавляет его
  в чат или жмёт кнопку на карточке. Бот отвечает **синхронно** (в том же HTTP-ответе).
- **(2) Проактивная отправка** — бот сам инициирует сообщения (рассылка опроса, напоминание,
  приглашение) через Chat REST API, используя **сервисный аккаунт**. Это отдельный путь,
  он не зависит от вебхука.

---

## 3. Карта файлов: что где лежит и зачем

```
english-meet-bot/
├── app/
│   ├── main.py                     # точка входа FastAPI, lifespan, логирование, роутеры
│   ├── config.py                   # настройки из .env (pydantic-settings)
│   ├── database.py                 # async engine + sessionmaker + Base + get_db()
│   ├── models.py                   # ORM-модели (11 таблиц)
│   ├── schemas.py                  # Pydantic-схемы: вебхук + доменные контракты
│   ├── messaging.py                # ИНТЕРФЕЙС отправки send_message() — стаб/реальный
│   ├── scheduler.py                # APScheduler: джобы ежедневного опроса
│   ├── api/
│   │   ├── google_chat.py          # ВЕБХУК — главный обработчик всех событий Google
│   │   └── health.py               # health-check /api/v1/health
│   └── services/                   # бизнес-логика, разбитая по сервисам
│       ├── onboarding.py           # профиль (get_or_create) + свободный ответ
│       ├── onboarding_answers.py   # парсинг анкеты онбординга → профиль + answers
│       ├── form_parsing.py         # нормализация formInputs Google → {name: [values]}
│       ├── weekly_poll.py          # ежедневный опрос: карточка, сабмит, финализация
│       ├── question_bank.py        # банк вопросов (fallback для LLM)
│       ├── llm_questions.py        # генерация персональных вопросов через OpenRouter
│       ├── invites.py              # приглашения + эскалация организатору (ENG-7)
│       ├── reminders.py            # расчёт времени напоминания + восстановление после рестарта
│       ├── checkin.py              # окно self-check-in «Я на встрече»
│       ├── space_onboarding.py     # план онбординга участников пространства
│       ├── broadcast.py            # массовые рассылки в DM
│       └── chat_sender.py          # низкоуровневая отправка через Chat REST API
├── alembic/
│   ├── env.py                      # async-конфиг Alembic (URL из Settings)
│   └── versions/                   # миграции 0001..0004
├── scripts/                        # диагностические/ручные скрипты (см. §12)
├── tests/                          # юнит + e2e тесты
├── docs/
│   ├── e2e-scenarios.md            # чеклист ручной проверки в живом чате
│   ├── db-schema.html              # визуальная схема БД
│   └── superpowers/                # планы и спеки по фичам (история разработки)
├── docker-compose.yml              # db (postgres) + app
├── Dockerfile                      # python:3.11-slim + uvicorn
├── requirements.txt                # зависимости
├── .env / .env.example             # конфиг (секреты — не в git)
├── sa-key.json                     # ключ сервисного аккаунта (СЕКРЕТ, в .gitignore)
├── PLAN.md                         # история сессий 1–2 (что уже сделано)
├── PARALLEL_PLAN.md                # план параллельной разработки (контракт v2)
├── SETUP_SECOND_BOT.md             # инструкция «поднять второго бота»
└── db_schema.puml                  # PlantUML-схема БД (⚠️ частично устарела, см. §7)
```

---

## 4. Поток запроса: что происходит, когда пользователь что-то делает

Всё заходит через **один** эндпоинт — `POST /webhooks/google-chat` (`app/api/google_chat.py`).
Обработчик большой, но логика линейная:

```
request.json()
      │
      ├─ JWT-проверка (если SKIP_JWT_VALIDATION=false)
      │
      ├─ это формат Add-on?  (event["chat"] существует)
      │     ├─ buttonClickedPayload  → разобрать method → онбординг / опрос / check-in
      │     ├─ messagePayload        → MESSAGE (текст) → ответ / сохранение ответа
      │     ├─ addedToSpacePayload   → ADDED_TO_SPACE → регистрация + онбординг
      │     └─ action.function       → сабмит анкеты (легаси-ветка)
      │
      └─ это классический формат? (type на верхнем уровне)
            ├─ ADDED_TO_SPACE        → регистрация + онбординг
            ├─ MESSAGE               → ответ текстом
            ├─ CARD_CLICKED          → разобрать function/method → сабмиты
            └─ REMOVED_FROM_SPACE / прочее → пустой {}
```

**Важный факт (выяснен боем, зафиксирован в PLAN.md §10):** этот Chat App фактически работает
в формате **Google Workspace Add-on** — события приходят внутри ключа `"chat"`, а ответ обязан
быть обёрнут в `hostAppDataAction.chatDataAction.createMessageAction`. Классический формат
(`type`/`user`/`message` наверху) оставлен как fallback. Код поддерживает **оба** пути.

**Ответ бота** бывает двух видов:

- **Синхронный** (на вебхук) — `JSONResponse` с текстом или карточкой. Это то, что видит
  пользователь сразу после сообщения/клика.
- **Проактивный** (позже, по расписанию) — через `chat_sender.send_message()` в Chat REST API.

---

## 5. Бизнес-фичи: сценарии по порядку

### 5.1 Онбординг нового участника

**Когда:** пользователь открывает DM с ботом (`ADDED_TO_SPACE`) или пишет «анкета»/«start».

**Что происходит:**

1. `_register_contact()` → `get_or_create_profile()` создаёт/обновляет профиль в БД.
   В `chat_space_id` пишется **только DM**-пространство (имя `spaces/...`), не группа.
2. `_onboarding_card()` рисует интерактивную карточку Cards V2 с **7 вопросами**
   (интересы, вайб встреч, тема, удобные дни, причины пропуска, согласие на использование,
   стиль общения) + кнопка «Отправить анкету».
3. Пользователь жмёт «Отправить» → `_submit_onboarding()` → `save_onboarding_answers()`:
   - парсит `formInputs` через `form_parsing.parse_form_inputs()`;
   - обновляет денормализованные поля профиля: `interests` (из q1), `preferred_days` (из q4),
     флаги `public_consent` / `anonymize_answers` (из q6);
   - пишет **каждый** ответ в таблицу `answers` (история, append-only);
   - ставит `onboarding_completed = true`.

**Ключевой нюанс приватности (REQ-8):** q6 определяет, можно ли использовать ответы публично.
Флаги: `public_consent` (использовать вообще) и `anonymize_answers` (только обезличенно).

**Онбординг в группе** (`space_onboarding.py`): когда бота добавляют в группу, он не спамит
карточками всем. Он делит участников на два канала:
- у кого уже есть DM с ботом → анкета **в личку**;
- у кого нет DM → одно сообщение в группу с `@упоминаниями` («напишите мне в личку»).

### 5.2 Ежедневный опрос «Кто сегодня и во сколько?»

**Когда:** каждый день в 9:00 UTC (джоб `daily-poll` в `scheduler.py`).

**Что происходит:**

1. `_run_daily_poll()` → `ensure_daily_poll()` создаёт `DailyPoll` на сегодня (если нет)
   и слоты времени из `config["daily_slots"]` (по умолчанию `["15:00", "16:00", "17:00"]`).
2. `build_daily_poll_card()` рисует карточку с кнопками-временами + «Не могу сегодня».
3. Карточка уходит в группу (`config["space_id"]`) через `chat_sender`.

**Голосование:** пользователь жмёт кнопку времени → `_submit_daily_poll()` →
`submit_poll()`. Правила:

- **одно время на человека**: старые голоса за этот опрос удаляются, пишется новый
  (`poll_votes` с unique-констрейнтом);
- проверяется дедлайн (`voting_deadline`): после него голоса не принимаются (REQ-9.4);
- «Не могу сегодня» → `PollResponse.status = "not_available"`, голоса снимаются.

### 5.3 Финализация → создание встречи

**Когда:** каждый день в 14:05 UTC (джоб `daily-finalize`).

**Что происходит** (`_finalize_daily_poll()` → `finalize_daily_poll()`):

1. Берёт голоса по слотам (`poll_slots.votes_count`, денормализованный триггером).
2. `resolve_day_result()`: какие времена набрали кворум (`config["quorum_threshold"]`,
   по умолчанию 3). Для недобравших считает, какое время им предложить.
3. Если кворум есть → создаёт `MeetingInstance` (статус `scheduled`) на это время,
   пишет в группу «Встреча сегодня в 15:00 🎉» + предложения недобравшим.
4. Если нет → опрос `cancelled`, в группу «Сегодня встреча не набирается — отмена».

### 5.4 Приглашения, напоминания, check-in (ENG-7)

Эта логика описана под названием **ENG-7** в `PARALLEL_PLAN.md` и реализована в
`invites.py` + `reminders.py` + `checkin.py`. Срабатывает по событию `TIME_FINALIZED`
(время выбрано):

- **Личные приглашения** (`handle_time_finalized`) — каждому `responded` участнику в DM
  «Встреча по английскому: <день> в <время>» + тема.
- **Пост в группу** — одно сообщение с итоговым временем.
- **Напоминание за час** (`_send_reminder`) — отложенный джоб `remind_<instance_id>`.
- **Окно self-check-in** (`_open_checkin` / `_close_checkin`) — за 15 мин до встречи в группу
  уходит карточка «Я на встрече ✅»; клик по ней → `submit_checkin()` записывает
  `Attendance`, но **только если сейчас в окне** (±`checkin_window_min`, по умолчанию 15 мин).
- **Эскалация** (`handle_escalated`) — если кворум не набрался, одно сообщение организатору
  (`config["organizer_user_id"]`), участникам — ничего (REQ-9.5).

> ⚠️ Важный нюанс: в текущем коде **ежедневный** цикл (5.2–5.3) не вызывает ENG-7 напрямую —
> финализация создаёт `MeetingInstance` со статусом `scheduled`, но приглашения/напоминания
> (`handle_time_finalized`) завязаны на отдельный поток с событием `TIME_FINALIZED`, который
> частично описан в `PARALLEL_PLAN.md` (интеграция `voting.py`/`advance_state`). Стыковку
> ежедневного и недельного циклов см. в §10 «Незавершённое».

### 5.5 Персональные вопросы (LLM + банк)



`llm_questions.py` генерирует персональный разговорный вопрос по `interests` участника через
OpenRouter. При **любом** сбое (нет ключа, сеть, невалидный JSON) возвращает `None`, и
вызывающий код берёт вопрос из `question_bank.BANK` — детерминированный по ISO-номеру недели
(никакого состояния в БД). Так что LLM — «приятный бонус», а не хард-зависимость.

### 5.6 Broadcast-рассылки

`broadcast.py` — утилитарная рассылка «всем, кто писал боту» или «участникам конкретного
space». Отправляет **только тем, у кого есть DM с ботом** (`chat_space_id` известен или
находится через `find_user_dm_space()`). Остальных считает `skipped`/`missing`.

---

## 6. Сервисы: кто за что отвечает (шпаргалка)

| Сервис (`app/services/`) | Ответственность | Ключевые функции |
|--------------------------|-----------------|------------------|
| `chat_sender.py` | Единственный, кто умеет **проактивно** писать в Chat (REST API, сервисный аккаунт) | `send_message`, `send_text`, `list_space_members`, `list_bot_spaces`, `find_user_dm_space` |
| `onboarding.py` | Профиль: upsert + свободные ответы | `get_or_create_profile`, `save_answer`, `mark_onboarded` |
| `onboarding_answers.py` | Парсинг анкеты онбординга → профиль + answers | `parse_onboarding_form`, `save_onboarding_answers`, `_apply_consent` |
| `form_parsing.py` | Нормализация formInputs Google (2 формата) | `parse_form_inputs` |
| `weekly_poll.py` | Ежедневный опрос: карточка, сабмит, финализация | `ensure_daily_poll`, `submit_poll`, `finalize_daily_poll`, `resolve_day_result`, `build_daily_poll_card` |
| `question_bank.py` | Банк вопросов (fallback LLM) | `bank_questions_for` |
| `llm_questions.py` | Генерация персонального вопроса (OpenRouter) | `generate_personal_question` |
| `invites.py` | Приглашения, пост в группу, эскалация (ENG-7) | `handle_time_finalized`, `handle_escalated`, `build_invite_text` |
| `reminders.py` | Расчёт времени напоминания + восстановление джобов | `reminder_at`, `restore_reminders_on_startup` |
| `checkin.py` | Окно self-check-in + карточка + запись attendance | `submit_checkin`, `checkin_window`, `build_checkin_card` |
| `space_onboarding.py` | План онбординга участников группы | `plan_onboarding`, `onboard_space_members` |
| `broadcast.py` | Массовые рассылки в DM | `broadcast_to_writers`, `broadcast_to_space_members` |

Модули вне `services/`:

| Модуль | Ответственность |
|--------|-----------------|
| `app/messaging.py` | **Интерфейс** `send_message(user_id, payload)` — граница между логикой и Chat API. Реальный вызов → `chat_sender`, иначе стаб (лог) |
| `app/scheduler.py` | APScheduler: джобы `daily-poll` (9:00) и `daily-finalize` (14:05). Джобы ENG-7 добавляются из `invites.py`/`checkin.py`/`reminders.py` |
| `app/api/google_chat.py` | Вебхук — диспетчер всех событий Google + JWT-валидация |

---

## 7. Модель данных

### 7.1 Таблицы (актуальная схема после миграций 0001–0004)

| # | Таблица | Назначение |
|---|---------|------------|
| 1 | `profiles` | Профиль участника: email, имя, `workspace_user_id`, `chat_space_id` (DM), флаги онбординга и приватности, `interests`, `preferred_days` |
| 2 | `daily_polls` | Ежедневный опрос. Один опрос = один день (`poll_date` unique), `voting_deadline`, `status` |
| 3 | `poll_slots` | Слот времени/места в опросе + денормализованный `votes_count` |
| 4 | `poll_responses` | Статус ответа участника на опрос (`pending`/`responded`/`not_available`) |
| 5 | `poll_votes` | Голос участника за слот (unique `profile_id + poll_slot_id`) |
| 6 | `meeting_instances` | Экземпляр встречи на основе выбранного слота + `participants_count` |
| 7 | `answers` | Ответы (история): онбординг + еженедельные вопросы |
| 8 | `attendance` | Посещаемость (self-check-in или manual) |
| 9 | `leaderboard_ledger` | Журнал баллов (идемпотентный: unique `profile+meeting+event_type`) |
| 10 | `config` | Системные настройки ключ→JSON-значение |
| 11 | `poll_questions` | Сгенерированные LLM-вопросы для участника опроса |

> **История редизайна:** изначально была `weekly_polls` (недельный цикл), затем (миграция
> `0003`) таблицу переименовали в `daily_polls` и перевели цикл на ежедневный. Поэтому
> `db_schema.puml` и часть комментариев всё ещё упоминают `weekly_polls` — **актуальной
> считай `models.py` и итоговую БД** (`daily_polls`), а puml — исторический артефакт.

### 7.2 Связи (главные)

```
profiles 1 ──< poll_responses >── 1 daily_polls
profiles 1 ──< poll_votes     >── 1 poll_slots  >── 1 daily_polls
profiles 1 ──< answers
profiles 1 ──< attendance    >── 1 meeting_instances
profiles 1 ──< leaderboard_ledger >── meeting_instances
profiles 1 ──< poll_questions >── daily_polls
daily_polls 1 ──< meeting_instances
```

### 7.3 Два триггера БД (важно понимать)

1. **`trg_poll_votes_votes_count`** — при `INSERT/DELETE` в `poll_votes` пересчитывает
   `poll_slots.votes_count` (денормализация: чтобы не делать `COUNT(*)` вручную).
2. **`trg_attendance_participants_count`** — при `INSERT/UPDATE OF status` в `attendance`
   пересчитывает `meeting_instances.participants_count` (число `present`).

То есть счётчики в этих двух колонках обновляются **самой БД**, а не приложением.

### 7.4 Таблица `config` — руль всех таймингов и порогов

Вся «настройка поведения» хранится в `config` (JSONB). Ключи, которые реально использует код:

| Ключ | Роль |
|------|------|
| `space_id` | имя **группы**, куда слать опросы и итоги (не DM!) |
| `organizer_user_id` | кому эскалировать при недоборе кворума |
| `daily_slots` | список слотов времени (по умолчанию 15/16/17) |
| `quorum_threshold` | минимум голосов для встречи (по умолчанию 3) |
| `poll_deadline_hour` / `_minute` | дедлайн голосования (по умолчанию 14:00) |
| `meet_reminder_hours` | за сколько часов напоминать (по умолчанию 1) |
| `checkin_window_min` | окно self-check-in ±минут (по умолчанию 15) |
| `meeting_duration_minutes` | длительность встречи (по умолчанию 60) |

Полный список сид-значений — в миграции `0001` и `0003`.

---

## 8. Ключевые контракты и соглашения (это важно, чтобы не сломать)

1. **`user_id` — это `workspace_user_id`** вида `"users/123456789"` (из Google Chat).
   НЕ email, НЕ int-`id` профиля в БД. Это сквозное соглашение по всему проекту
   (зафиксировано в `schemas.py` и `PARALLEL_PLAN.md`).

2. **Всё время — UTC** (`DateTime(timezone=True)` → `TIMESTAMPTZ`). Никакого локального времени.

3. **Доменные модели ≠ ORM.** `schemas.py` содержит Pydantic-контракты (`MeetingInstance`,
   `Slot`, `Activity`, `MessagePayload` и т.д.), а `models.py` — SQLAlchemy-модели. Мост
   между ними строит только один человек (в плане — «Кирилл»).

4. **`app/messaging.py` — единственная граница отправки.** Вся логика вызывает
   `send_message(user_id, payload)` и не знает, реальный ли это Chat API или стаб.
   Сигнатуру менять нельзя без обсуждения (на неё опираются другие модули).

5. **`answers` — история, а не перезапись.** Повторное прохождение анкеты добавляет
   новый батч записей (не затирает старые).

6. **Голос — один на человека на слот** (unique-констрейнты в БД обеспечивают идемпотентность).

7. **`chat_space_id` в профиле = только DM.** Имя группы хранится отдельно в
   `config["space_id"]`. Не путать: проактивные DM-рассылки идут в `chat_space_id`,
   а опросы/итоги — в `config["space_id"]`.

---

## 9. Настройка (`.env`)

| Переменная | Назначение |
|------------|------------|
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | креды БД |
| `DB_HOST` / `DB_PORT` | хост/порт БД (`localhost:5432` локально, `db:5432` в Docker) |
| `APP_ENV` / `LOG_LEVEL` | режим и уровень логирования |
| `CHAT_APP_AUDIENCE` | audience для JWT-валидации = URL endpoint'а вебхука |
| `SKIP_JWT_VALIDATION` | `true` — пропустить проверку подписи (только для локальной отладки) |
| `GOOGLE_SA_KEY_FILE` | путь к JSON-ключу сервисного аккаунта (`sa-key.json`) |
| `CHAT_TEST_SPACE` | DM-space для ручных проверок проактивной отправки |
| `OPENROUTER_API_KEY` | ключ OpenRouter (пусто = LLM-генерация выключена → банк) |
| `LLM_MODEL` | модель LLM (по умолчанию `deepseek/deepseek-chat`) |

Все значения подхватываются `app/config.py` через `pydantic-settings` (`.env` в корне).

---


## 10. Незавершённое / ограничения / TODO

Собранные из `PLAN.md` (этапы без галочек), `PARALLEL_PLAN.md` и комментариев в коде:

1. **Стыковка ежедневного и недельного циклов.** `PARALLEL_PLAN.md` описывает `voting.py` +
   `advance_state` (ENG-6) — чистую функцию перехода статусов (`voting → time_finalized →
   scheduled / escalated`). В текущем коде `app/services/voting.py` **отсутствует**, а
   `scheduling.py`/`activities.py` (ENG-6/ENG-8 от «тиммейтов») в репозитории не видны —
   интеграция приглашений/напоминаний через `handle_time_finalized` не подключена к
   ежедневной финализации. Это главный «шов», который предстоит сшить.

2. **Calendar + Meet (REQ-3.7)** — заглушка. Требует domain-wide delegation и админа
   Workspace («Фаза B» из PLAN.md). Встреча создаётся в БД, но реальное событие с
   Meet-ссылкой не создаётся.

3. **Авто-онбординг всего домена (REQ-1.2)** — требует установки приложения на домен
   (права админа). Пока бот пишет только туда, где он участник.

4. **Баллы / лидерборд.** Таблица `leaderboard_ledger` и config-ключи баллов есть, но кода
   начисления/вывода лидерборда в `services/` нет (только схема под это).

5. **`db_schema.puml` устарел** — показывает `weekly_polls` вместо `daily_polls`.

6. **15-секундный таймаут ответа Google** — обработчик вебхука должен оставаться лёгким;
   тяжёлые вещи (LLM, массовые рассылки) лучше выносить в джобы, не в ответ на вебхук.

7. **Ограничение Chat App:** неопубликованное приложение доступно только аккаунтам того же
   Workspace-домена. Внешним пользователям — только через Marketplace (ревью Google).

---

## 11. Как запустить и проверить

```powershell
# 1. БД
docker compose up -d db

# 2. Окружение и зависимости
python -m venv venv
.\venv\Scripts\pip install -r requirements.txt
Copy-Item .env.example .env    # заполнить

# 3. Миграции
.\venv\Scripts\alembic upgrade head

# 4. Приложение
.\venv\Scripts\python -m uvicorn app.main:app --reload --port 8000

# 5. Проверка
Invoke-RestMethod http://localhost:8000/api/v1/health
# → {"status": "ok", "database": "connected"}
```

Тесты:

```powershell
.\venv\Scripts\pytest -q              # юниты (e2e/live исключены по умолчанию)
.\venv\Scripts\pytest -m e2e -q       # сквозные (нужен поднятый uvicorn + БД)
.\venv\Scripts\pytest -m live -q      # реальные вызовы Google/OpenRouter
```

Для живого Google Chat нужен cloudflared-туннель + Chat App в GCP. Полная пошаговая инструкция —
в `SETUP_SECOND_BOT.md`, чеклист ручной проверки сценариев — в `docs/e2e-scenarios.md`.

---

## 12. Скрипты (`scripts/`) — шпаргалка

| Скрипт | Назначение |
|--------|------------|
| `backfill_dm_spaces.py` | автозаполнить `chat_space_id` у профилей через API |
| `send_poll_now.py` | отправить карточку ежедневного опроса прямо сейчас (не ждать 9:00) |
| `demo_poll_card.py` | демо-генерация карточки опроса |
| `test_send_dm.py` | тест отправки DM в `CHAT_TEST_SPACE` |
| `test_broadcast_writers.py` | рассылка всем, кто писал боту |
| `test_broadcast_space.py` | рассылка участникам конкретного space |
| `test_poll_flow.py` | прогнать поток ежедневного опроса |
| `test_onboarding.py` / `diagnose_onboarding.py` | тест / диагностика онбординга |
| `test_eng7_flow.py` | прогнать поток ENG-7 (приглашения/напоминания) |
| `test_card_via_api.py` / `test_click_webhook.py` | тест карточки и клика через вебхук |

---

## 13. Глоссарий REQ-ов

Ссылки на требования (`REQ-*`) разбросаны по комментариям и планам. Их источник — ТЗ/спек
(не в репозитории напрямую), но из кода и планов восстанавливается картина:

- **REQ-1** — онбординг: карточка (1.3), авто-онбординг домена (1.2).
- **REQ-2** — еженедельный/ежедневный опрос: рассылка, приём ответов, история (2.4).
- **REQ-3** — слоты времени и выбор: голосование (3.1–3.2), выбор слота (3.3–3.4),
  эскалация при недоборе (3.5), Calendar/Meet (3.7).
- **REQ-4** — активности: мини-дайджест, «угадай коллегу» (4.2), фильтр приватности (4.3).
- **REQ-5** — приглашения: личные (5.1), пост в группу (5.2), напоминание (5.3).
- **REQ-6** — посещаемость: Meet API (6.1), self-check-in (6.2).
- **REQ-7** — баллы/лидерборд: идемпотентные начисления (7.5).
- **REQ-8** — приватность: согласие на использование ответов (8.1).
- **REQ-9** — тайминги и edge-кейсы: UTC (9.1), напоминание без дублей (9.2), пересоздание
  при смене времени (9.3), стоп голосования после дедлайна (9.4), эскалация молча (9.5),
  окно check-in (9.6).
- **REQ-10** — голоса/баллы/LLM: fallback на банк при сбое генерации.

---

## 14. Резюме «как это всё связано» (за 1 минуту)

1. **Google Chat** присылает события на **вебхук** (`api/google_chat.py`).
2. Вебхук проверяет JWT, разбирает формат (Add-on/классический) и вызывает нужный **сервис**.
3. Сервисы пишут/читают **PostgreSQL** через SQLAlchemy (`models.py` + `database.py`).
4. Сервисы отправляют сообщения через **`messaging.py`** — единственный интерфейс отправки
   (внутри либо реальный `chat_sender`, либо стаб).
5. **`scheduler.py`** по cron создаёт опрос (9:00) и подводит итог (14:05); джобы
   приглашений/напоминаний/check-in добавляются из `invites.py`/`reminders.py`/`checkin.py`.
6. **`config`** (таблица) рулит таймингами, порогами и id группы/организатора.
7. **`chat_sender.py`** — низкоуровневый доступ к Chat REST API через сервисный аккаунт
   (`chat.bot`) для всего проактивного (бот пишет первым).

Если хочешь разобраться в конкретной фиче — начни с §5 (сценарий), затем смотри
соответствующий сервис в §6, а схемы данных — в §7.
