# План сессии: EnglishMeetBot — бот, которого видно в Google Chat

> Дата: 2026-08-19
> Проект: `english-meet-bot` (эта папка)
> GCP-проект: `english-meet-assistant` (уже существует, Chat API и Calendar API включены)

---

## 1. Цель сессии и критерии успеха

**Цель:** бот EnglishMeetBot находится поиском в Google Chat, отвечает на мои сообщения
и присылает приветственную карточку из ТЗ при добавлении в чат.

**Критерии успеха (все обязательны):**

| # | Критерий | Как проверяем |
|---|----------|---------------|
| 1 | `docker compose up -d db` + uvicorn поднимаются без ошибок | `GET http://localhost:8000/api/v1/health` → `{"status": "ok", "database": "connected"}` |
| 2 | Вебхук отвечает на фейковые события локально | curl POST MESSAGE → ответ бота; curl без JWT → 401 |
| 3 | Google Chat доставляет события боту | В логах ngrok/uvicorn видны запросы от Google при написании боту |
| 4 | Бот отвечает на «привет» в реальном Google Chat | Сообщение от бота появляется в чате |
| 5 | При добавлении бота в DM приходит карточка онбординга | Cards V2 видна в чате |

---

## 2. Исходное состояние (что уже есть, проверено 2026-08-19)

### 2.1. GCP / регистрация (папка `studotryad — копия/english-bot/`)

- GCP-проект `english-meet-assistant` создан; `chat.googleapis.com` + `calendar-json.googleapis.com` включены.
- OAuth consent screen (External, режим **Testing**) + OAuth client типа Desktop — готово (`oauth-credentials.json`).
- Chat App **EnglishMeetBot** зарегистрирован, App status = **LIVE**, но connection settings
  указывают на заглушку `https://example.com/chat/interaction` — **надо будет заменить**.
- User-OAuth токен организатора (`token.json`) + рабочий код отправки сообщений
  (`auth.py`, `messenger.py`) — DM и посты в Space работают. **Для цели этой сессии не нужен**
  (ответы идут синхронным HTTP-ответом), пригодится позже для проактивных рассылок.

### 2.2. Каркас FastAPI (эта папка, `english-meet-bot/`)

- `app/main.py` — FastAPI entry point, lifespan, роутеры health + google_chat. Готово.
- `app/config.py` — pydantic-settings, переменные Postgres. Готово, надо дополнить.
- `app/database.py` — async engine + sessionmaker. Готово.
- `app/models.py` — **пустой** (модели не нужны для этой сессии).
- `app/schemas.py` — pydantic-схемы вебхука. Есть, используются частично.
- `app/api/google_chat.py` — вебхук `/webhooks/google-chat`. Есть, но **основная ветка заточена
  под неверный формат события** (обёртка `chat.messagePayload` — это формат Workspace Add-on;
  у нас классический Chat App, где `type`/`user`/`message` лежат на верхнем уровне —
  подтверждено рабочим кодом референс-бота).
- `app/api/health.py` — health-check с проверкой БД. Готово.
- `docker-compose.yml` — сервисы `db` (postgres:15-alpine, порт 5432) и `app` (build, порт 8000).
- `.env` — заполнен (POSTGRES_*, APP_ENV, LOG_LEVEL, DB_HOST/PORT).
- `Dockerfile`, `requirements.txt` — fastapi/uvicorn/sqlalchemy/asyncpg/pydantic-settings.

### 2.3. Референс по развёртыванию (папка `google_chat — копия/`)

Рабочий бот ChatMonitorBot2 на том же стеке. Оттуда берём проверенные паттерны:

- **Формат interaction-события** (`app/api/interactions.py:50-71`):
  `{"type": "MESSAGE"|"ADDED_TO_SPACE"|"REMOVED_FROM_SPACE", "user": {...}, "message": {...}, "space": {...}}`
  на верхнем уровне JSON.
- **JWT-валидация** (`app/api/interactions.py:23-31`): заголовок `Authorization: Bearer <JWT>`,
  проверка через `google.oauth2.id_token.verify_oauth2_token(token, request, audience=CHAT_APP_AUDIENCE)`,
  где audience = **Project Number** GCP-проекта.
- **Флаг `skip_jwt_validation`** для локальной разработки без реальных токенов Google.
- **Ответ бота** — синхронный JSONResponse (`{"text": ...}` или `{"cardsV2": [...]}`),
  без вызова Chat API — т.е. 7-дневная смерть refresh-токена организатора нас в этой сессии не касается.
- **Цепочка развёртывания на деве**: uvicorn на localhost:8000 + ngrok-туннель наружу,
  ngrok-URL прописывается в Chat App Configuration.

---

## 3. Решения, принятые заранее (согласованы)

1. **Карточка онбординга — статичная** (Cards V2, текстовые вопросы без кнопок).
   Интерактив с обработкой CARD_CLICKED — в следующей сессии.
2. **JWT-валидацию делаем сразу**, с флагом `SKIP_JWT_VALIDATION` для локальных тестов.
3. **Запуск на деве**: Postgres — в Docker, приложение — локально через venv + uvicorn
   (быстрее итерации, hot-reload). Полный `docker compose up` — опционально, для проверки
   контейнеризации.
4. **Папку `studotryad — копия/english-bot/` не трогаем** — она остаётся источником creds
   для будущих фаз (проактивные рассылки, Фаза B из deployment_plan.md).
5. Точку вебхука оставляем `/webhooks/google-chat` (уже в каркасе), а не `/chat/interaction`
   как в референсе — просто иначе, не хуже.

---

## 4. Этапы

### Этап 0. Smoke-тест каркаса (цель: убедиться, что база поднимается)

**Действия:**

1. Проверить, что порт 5432 свободен (иначе старый `chatbot-pg` из референса может конфликтовать):
   ```powershell
   Get-NetTCPConnection -LocalPort 5432 -ErrorAction SilentlyContinue
   ```
2. Поднять только БД:
   ```powershell
   docker compose up -d db
   ```
3. Создать venv, поставить зависимости:
   ```powershell
   python -m venv venv
   .\venv\Scripts\pip install -r requirements.txt
   ```
4. Запустить приложение:
   ```powershell
   .\venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
   ```

**Проверка:**
- `GET http://localhost:8000/api/v1/health` → `{"status": "ok", "database": "connected"}`
- `GET http://localhost:8000/` → `{"message": "English Meet Bot is running"}`

**Возможные грабли:**
- Порт 5432 занят другим Postgres (референс-бот поднимал `chatbot-pg` на 5432) →
  остановить его `docker stop chatbot-pg` либо сменить маппинг порта в docker-compose.
- `.env` подхватывается из корня проекта — запускать uvicorn из папки `english-meet-bot`.

---

### Этап 1. JWT-валидация + нормализация обработчика (цель: правильный формат + безопасность)

**Что нужно от Кирилла перед этапом:** Project Number проекта `english-meet-assistant`
(GCP Console → IAM & Admin → Settings → поле Project Number, 12 цифр;
или `gcloud projects describe english-meet-assistant --format="value(projectNumber)"`).

**Изменения по файлам:**

#### 1.1. `requirements.txt` — добавить:

```
google-auth==2.32.0
```

(версию уточним по факту `pip install`; нужна только `google.oauth2.id_token` — тяжёлые
google-api-python-client тут не нужны)

#### 1.2. `app/config.py` — добавить поля в `Settings`:

```python
# Google Chat
chat_app_audience: str = ""        # Project Number GCP-проекта (audience JWT)
skip_jwt_validation: bool = False  # true только для локальных тестов без реального Google
```

#### 1.3. `app/api/google_chat.py` — переписать обработчик:

Структура нового кода (по образцу референса `interactions.py`):

```python
# Проверка JWT до чтения body:
#   Authorization: Bearer <jwt> -> id_token.verify_oauth2_token(token, req, audience=settings.chat_app_audience)
#   невалидный/отсутствующий -> HTTPException 401
#   settings.skip_jwt_validation == True -> пропустить проверку (локальная разработка)

# Диспетчер по событию (КЛАССИЧЕСКИЙ формат, верхний уровень):
#   type == "ADDED_TO_SPACE"      -> приветственная карточка (этап 2)
#   type == "MESSAGE"             -> text из message.text (fallback message.argumentText), ответ текстом
#   type == "REMOVED_FROM_SPACE"  -> пустой JSONResponse {}
#   прочее                        -> пустой JSONResponse {}
```

Что удаляем: ветку с обёрткой `payload["chat"]["messagePayload"]` — это формат
Workspace Add-on, наш Chat App так не шлёт (у референса события приходят в классическом
виде, обработчик работал в бою). Fallback-ветку со старым форматом заменяем основной.

**Тексты ответов на MESSAGE (первая итерация, без БД и LLM):**

- «привет» (в любом регистре) → приветствие + подсказка, что бот умеет;
- любое другое сообщение → echo с пометкой «я пока учусь» (сохраняем текущее поведение каркаса).

**Проверка (uvicorn запущен с `SKIP_JWT_VALIDATION=true` в `.env`):**

```powershell
# 1. Без токена при включённой валидации -> 401
# (запустить с skip_jwt_validation=false, аудитенс пока можно любой)
Invoke-RestMethod -Uri http://localhost:8000/webhooks/google-chat -Method Post `
  -Body '{"type":"MESSAGE","message":{"text":"привет"}}' -ContentType "application/json"
# ожидание: 401

# 2. С выключенной валидацией -> ответ бота
# (SKIP_JWT_VALIDATION=true, перезапустить uvicorn)
$payload = @{
  type = "MESSAGE"
  user = @{ name = "users/test"; displayName = "Kirill" }
  message = @{ text = "привет"; argumentText = "привет" }
  space = @{ name = "spaces/test"; type = "DIRECT_MESSAGE" }
} | ConvertTo-Json -Depth 5
Invoke-RestMethod -Uri http://localhost:8000/webhooks/google-chat -Method Post `
  -Body $payload -ContentType "application/json"
# ожидание: {"actionResponse":...,"text":"Привет, Kirill!..."}

# 3. REMOVED_FROM_SPACE -> пустой ответ, без 500
```

**Откат:** git (в папке есть `.git/`) — `git checkout -- app/api/google_chat.py` и т.д.

---

### Этап 2. Приветственная карточка онбординга (REQ-1.3 + REQ-8.1 из ТЗ)

**Что делаем:** на `ADDED_TO_SPACE` бот отвечает не текстом, а карточкой Cards V2
(статичной: текст + вопросы, без кнопок).

**Структура ответа:**

```json
{
  "cardsV2": [
    {
      "cardId": "onboardingWelcome",
      "card": {
        "header": {
          "title": "Привет! Я EnglishMeetBot",
          "subtitle": "Помогаю организовывать встречи по английскому"
        },
        "sections": [
          { "widgets": [{ "textParagraph": { "text": "..." } }] },
          { "header": "Расскажи о себе (5 вопросов)", "widgets": [ ... по одному textParagraph на вопрос ... ] },
          { "widgets": [{ "textParagraph": { "text": "примечание про приватность" } }] }
        ]
      }
    }
  ]
}
```

**Тексты карточки (из REQ-1.3 ТЗ — 5 базовых вопросов):**

1. Какой у тебя уровень английского? (A1–C2)
2. Зачем ты практикуешь английский? (работа, переезд, для себя...)
3. Какие темы тебе интересны? (кино, технологии, путешествия...)
4. Какой формат встреч тебе ближе? (свободный разговор, обсуждение статьи, игры)
5. Какие дни недели удобны для встреч?

**Приватность (REQ-8.1):** короткий блок «Ответы могут звучать на встречах. Если не хочешь,
чтобы твой ответ использовался публично, — просто напиши об этом в ответе».

Примечание: раз карточка статичная, ответы пользователь пока пишет обычным сообщением
(бот их просто примет как echo). Сохранение в профиль — следующая сессия (нужна модель
`participants` + `answers` из плана БД).

**Проверка:**

```powershell
$payload = @{
  type = "ADDED_TO_SPACE"
  user = @{ name = "users/test"; displayName = "Kirill" }
  space = @{ name = "spaces/test"; type = "DIRECT_MESSAGE" }
} | ConvertTo-Json -Depth 5
Invoke-RestMethod -Uri http://localhost:8000/webhooks/google-chat -Method Post `
  -Body $payload -ContentType "application/json"
# ожидание: в ответе есть cardsV2 с карточкой и всеми 5 вопросами
```

---

### Этап 3. ngrok-туннель + настройка Chat App в GCP (руки Кирилла, инструкция пошагово)

**3.1. Статический домен ngrok (один бесплатный на аккаунт):**

1. https://dashboard.ngrok.com → Domains → New Domain → скопировать выданный
   `something.ngrok-free.app` (домен постоянный, не меняется между перезапусками).
2. Запустить туннель (в отдельном окне терминала):
   ```powershell
   ngrok http --domain=something.ngrok-free.app 8000
   ```

**3.2. Настройка Chat App в GCP Console:**

1. https://console.cloud.google.com → выбрать проект `english-meet-assistant`.
2. Поиск по «Google Chat API» → Configuration (или API & Services → Google Chat API → Configure).
3. **Connection settings → HTTP endpoint URL:**
   `https://something.ngrok-free.app/webhooks/google-chat`
   (заменить текущую заглушку example.com).
4. **Authentication audience:** Project Number проекта (те же 12 цифр, что в `CHAT_APP_AUDIENCE`).
5. **App status:** Live (сейчас уже Live — не трогать, если стоит).
6. Проверить галки Functionality: «Receive 1:1 messages» и «Join group conversations»
   (нужно для DM и Space).
7. **НЕ ставить галку «Build this Chat app as a Workspace add-on»** — необратимо меняет
   формат приложения (и это как раз тот формат, из которого мы уходим в этапе 1).
8. Save Changes. Изменения конфигурации применяются до ~5 минут.

**3.3. `.env` — финальные значения:**

```env
CHAT_APP_AUDIENCE=<Project Number>
SKIP_JWT_VALIDATION=false
```

Перезапустить uvicorn с этими значениями.

**Проверка:**
- Открыть http://localhost:4040 (ngrok inspector) — там должны появиться POST-запросы
  от Google (`POST /webhooks/google-chat`, статус 200) после этапа 4.
- Если в inspector прилетает 401 — Google шлёт токен с другой audience (пересверить
  Project Number в Configuration и в .env — они должны совпадать до символа).

**Важный нюанс Workspace:** у Кирилла рабочий аккаунт Google Workspace. Если приложение
не находится поиском в Chat — проверить, не запрещена ли установка приложений политикой
домена (Admin Console → Apps → Google Chat). Обычно для Internal/Testing-приложений в
Workspace поиск работает после App status = Live; если домен строгий — добавим
тестовых пользователей в OAuth consent screen (Testing-режим) и/или попросим админа.
Разбираться по факту, не заранее.

---

### Этап 4. E2E — приёмка цели сессии

**Сценарий (все шаги руками Кирилла, я смотрю логи):**

1. Google Chat → кнопка «Новый чат» → в поиске ввести `EnglishMeetBot`.
2. Если бот находится — открыть с ним DM. В логах uvicorn/ngrok должно появиться
   событие (возможно, `ADDED_TO_SPACE` при открытии DM).
3. Написать «привет» → бот отвечает приветственным текстом (синхронный ответ,
   задержка до ~1–2 сек).
4. Написать что-нибудь другое → echo-ответ.
5. Удалить бота из DM и добавить снова (или открыть новый DM) → приветственная карточка
   с 5 вопросами.
6. Прогнать чек-лист критериев успеха из раздела 1 — все 5 пунктов.

**Если бот не находится поиском:**
- App status точно Live? (в Testing/неопубликовано — не найдётся)
- Прошло ли 5+ минут после Save?
- Поиск в Chat работает по имени приложения из Configuration (App name) — сверить точное имя.
- Workspace-политики (см. 3.2).

**Если бот находится, но молчит:**
- ngrok inspector: приходят ли POST? Если нет — endpoint URL неверный/не сохранился.
- Если приходят с 4xx/5xx — смотреть статус и логи uvicorn, чинить по коду ответа.
- Timeout: Google ждёт ответ вебхука **до 15 секунд** — наши ответы синхронные и быстрые,
  но если что-то зависает (например, обращение к БД) — бот промолчит.

---

## 5. Чего в этой сессии НЕ делаем (осознанно)

- Модели БД (`participants`, `answers`, `votes`, ...) и alembic — models.py остаётся пустым.
- Сохранение ответов онбординга в профиль.
- Интерактивная карточка (кнопки/списки) и обработка `CARD_CLICKED`.
- Еженедельные рассылки, планировщик, лидерборд — всё из ТЗ REQ-2..REQ-7.
- Calendar API, Meet API, Pub/Sub, Workspace Events API — не нужны для этой цели
  (подтверждено deployment_plan.md: «для нашего ТЗ эта подписка не нужна»).
- Проактивная отправка сообщений (мостик user-OAuth из english-bot) — работает, но
  не требуется: ответы на MESSAGE идут синхронно.
- Деплой на Cloud Run — потом (нужен биллинг); сейчас ngrok.
- Сервисный аккаунт / app-auth (Фаза B из deployment_plan.md — требует одобрения админа).

---

## 6. Риски и грабли

| # | Риск | Вероятность | План Б |
|---|------|-------------|--------|
| 1 | Порт 5432 занят (контейнер референс-бота `chatbot-pg`) | средняя | `docker stop chatbot-pg` или сменить порт в docker-compose |
| 2 | ngrok-URL в конфиге Google перезатирается/не сохранился | низкая | перепроверить Configuration через 5 мин; смотреть inspector 4040 |
| 3 | JWT 401 от Google (не та audience) | средняя | сверить Project Number в Configuration и .env посимвольно |
| 4 | Бот не находится поиском из-за политик Workspace | средняя | добавить тестеров в consent screen; письмо админу (шаблон есть в deployment_plan.md) |
| 5 | 15-секундный таймаут ответа Chat API | низкая | наши ответы без БД/LLM — мгновенные; держать обработчик лёгким |
| 6 | Событие приходит в неожиданном формате | низкая | логировать весь payload при неизвестном type (уже в плане обработчика) |
| 7 | ngrok free: показ страницы-предупреждения | нет | это только для браузера; API-запросы Google проходят нормально |

---

## 7. Итоговая карта файлов после сессии

```
english-meet-bot/
├── .env                      # + CHAT_APP_AUDIENCE, SKIP_JWT_VALIDATION
├── .env.example              # + те же ключи с плейсхолдерами
├── requirements.txt          # + google-auth
├── docker-compose.yml        # без изменений
├── Dockerfile                # без изменений
├── PLAN.md                   # этот файл
└── app/
    ├── main.py               # без изменений
    ├── config.py             # + chat_app_audience, skip_jwt_validation
    ├── database.py           # без изменений
    ├── models.py             # пустой (модели — следующая сессия)
    ├── schemas.py            # без изменений / минимальная правка
    └── api/
        ├── health.py         # без изменений
        └── google_chat.py    # ПЕРЕПИСАН: JWT + классический формат + карточка
```

---

## 8. Порядок работы по этапам (сводка для чек-листа)

- [x] Этап 0: docker db + venv + uvicorn → health = ok (2026-08-19)
- [x] Этап 1: google-auth, config, переписать вебхук → curl-тесты (401 / ответ / пустой) (2026-08-19)
- [x] Этап 1.5: Project Number = 540751395097 → вписан в .env, SKIP_JWT_VALIDATION=false (2026-08-19)
- [x] Этап 2: карточка онбординга → curl ADDED_TO_SPACE → cardsV2 (3 секции, 5 вопросов, приватность) (2026-08-19)
- [x] Этап 3: ngrok (renewed-ditto-knee.ngrok-free.dev) + Configuration в GCP (2026-08-19)
- [x] Этап 4: e2e — бот найден в Google Chat, отвечает на сообщения (200 OK в логах, ответ доставлен) (2026-08-19)
- [x] Этап 4.5: карточка онбординга «вживую» доставлена при открытии DM (2026-08-19)
- [ ] Этап 5: доступ коллегам — Visibility в Configuration (specific people/groups или весь домен)

> Ограничение платформы (подтверждено доками Google, test-interactive-features):
> непубликдованный Chat App доступен ТОЛЬКО аккаунтам того же домена Workspace.
> Внешние аккаунты (другие домены, личные Gmail) могут получить бота только через
> публикацию в Google Workspace Marketplace (ревью Google, верификация OAuth,
> политика конфиденциальности). Кодом/конфигом это не обходится.

**Сессия 2 (раздел 9):**
- [x] 9A.1: собрать структуру alembic в english-meet-bot/ (сейчас куски в studiki/)
- [x] 9A.2: alembic.ini + async env.py по образцу референса (URL из Settings)
- [x] 9A.3: models.py — полная схема из «база данных.docx»: 10 таблиц (profiles, weekly_polls, poll_slots, poll_responses, poll_votes, meeting_instances, answers, attendance, leaderboard_ledger, config) + триггеры счётчиков + сидинг config (2026-08-19, заменило 5 MVP-таблиц)
- [x] 9A.4: alembic revision --autogenerate → upgrade head → таблицы в english_meet_db (2026-08-19: вместо autogenerate заменили initial-миграцию целиком, upgrade head создал 10 таблиц)
- [x] 9A.5: вебхук пишет ответы онбординга в БД (2026-08-19: проверено e2e — профиль в profiles, ответ в answers)
- [x] 9B: сервисный аккаунт + JSON-ключ + .gitignore + .env (2026-08-19: sa-key.json создан руками, добавлен в .gitignore, GOOGLE_SA_KEY_FILE в .env)
- [x] 9C.1: chat_sender.py — отправка через Chat REST API (scope chat.bot) (2026-08-19)
- [ ] 9C.2: APScheduler в lifespan
- [x] 9C.3: проверка — бот сам пишет в DM spaces/7UqhjKAAAAE (2026-08-19: отправка через SA работает; добавлены рассылки broadcast_to_writers / broadcast_to_space_members)

> Примечание: asyncpg поднят 0.29.0 → 0.31.0 (нет wheel под Python 3.14),
> в requirements.txt добавлены google-auth==2.32.0 и requests==2.32.3 (транспорт для JWT-проверки).

---

## 9. Сессия 2: БД (alembic) + сервисный аккаунт + проактивные сообщения

Три блока: (A) прикрутить миграции и таблицы к проекту, (B) сервисный аккаунт,
(C) отправка сообщений от имени бота по расписанию.

### 9A. Alembic + БД (прикрутка того, что Кирилл добавил)

**Исходное состояние (разобрано, требует сборки):** в корне `studiki` лежат куски alembic
(`env.py` — sync-шаблон с `target_metadata = None`, `script.py.mako`, `versions/`).
⚠️ Файл `versions/001_initial_schema.py` — это на самом деле **текст alembic.ini**
(конфиг, скопированный не туда), а не миграция. Реальной миграции пока нет.
Рабочий паттерн брать из референса (`google_chat — копия/alembic/env.py`).

**Шаги:**

1. **Перенести структуру в `english-meet-bot/`** (проект живёт там, .env и venv там же):
   ```
   english-meet-bot/
   ├── alembic.ini              # создать (из содержимого 001_initial_schema.py, почистив)
   └── alembic/
       ├── env.py               # переписать по async-паттерну референса
       ├── script.py.mako       # перенести
       └── versions/            # сюда реальные миграции
   ```
   Файл `versions/001_initial_schema.py` (содержимое alembic.ini) → becomes `alembic.ini`,
   из versions/ удалить.
2. **alembic.ini:** `script_location = %(here)s/alembic`; `sqlalchemy.url` НЕ заполнять
   кредами — URL подставит env.py из Settings (как в референсе).
   ⚠️ Сверка имени БД: в черновике указано `english_bot_db`, а у нас в `.env`
   `english_meet_db` (контейнер `meet_bot_db` уже с ней работает) — используем
   **`english_meet_db`**, ничего не пересоздаём.
3. **alembic/env.py (async, по образцу референса):**
   - `config.set_main_option("sqlalchemy.url", settings.database_url)` — URL из наших настроек
   - `target_metadata = Base.metadata` + `from app import models  # noqa: F401`
   - online-режим через `async_engine_from_config` + `connection.run_sync(...)`
4. **`app/models.py` (сейчас пустой):** MVP-таблицы из ТЗ/deployment_plan:
   - `participants` — профиль юзера (user_id из Chat, email, display_name, created_at,
     опции приватности REQ-8)
   - `answers` — ответы на онбординг и еженедельные вопросы (история, не перезапись — REQ-2.4)
   - `votes` — голоса за слоты времени (upsert по user_id + meeting_instance — REQ-10)
   - `checkins` — self-check-in посещаемости (REQ-6.2)
   - `points_ledger` — журнал начислений баллов, идемпотентный ключ (REQ-7.5, REQ-10)
   Время — только UTC (REQ-9.1).
5. **requirements.txt:** + `alembic==1.18.4` (версия как в референсе, проверена).
6. **Генерация и накат:**
   ```powershell
   .\venv\Scripts\pip install -r requirements.txt
   .\venv\Scripts\alembic revision --autogenerate -m "initial schema"
   .\venv\Scripts\alembic upgrade head
   ```
7. **Прикрутить к боту:** вебхук пишет ответы онбординга в `participants`/`answers`
   (сейчас карточка статичная — ответы приходят как обычные MESSAGE).

**Проверка:** `\dt` в psql внутри `meet_bot_db` показывает все 5 таблиц + `alembic_version`;
health-check по-прежнему ok; после ответа на онбординг в `answers` появляется запись.

### 9B. Сервисный аккаунт (руки Кирилла, ~5 минут, админ НЕ нужен)

1. https://console.cloud.google.com → проект `english-meet-assistant`
2. **IAM & Admin → Service Accounts → + Create Service Account**
3. Имя: `english-meet-sender` → Create and Continue → роль не нужна → Done
4. Открыть аккаунт → вкладка **Keys** → **Add Key → Create new key → JSON** → скачать
5. Файл положить в `english-meet-bot\sa-key.json`; **добавить в .gitignore** (секрет!)
6. `.env`: `GOOGLE_SA_KEY_FILE=sa-key.json`

**Статус (2026-08-19):** пункты 1–5 выполнены — `sa-key.json` лежит в корне проекта.
⚙️ Кирилл доделал: `sa-key.json` добавлен в `.gitignore` (строка `sa-key.json`),
в `.env` добавлено `GOOGLE_SA_KEY_FILE=sa-key.json`.

### 9C. Проактивная отправка от имени бота

**Ключевой факт:** аддон-формат событий не мешает проактивной отправке — для сообщений
по расписанию / позже 30 сек / вне пространства взаимодействия Google требует
вызывать Chat REST API (`spaces.messages.create`), и это отдельный путь от вебхука.

**Шаги (код):**

1. `app/services/chat_sender.py`: SA-креды (`google.oauth2.service_account.Credentials`
   + scope `https://www.googleapis.com/auth/chat.bot`) → access token →
   POST `https://chat.googleapis.com/v1/{space}/messages` с Bearer.
2. `app/scheduler.py`: **APScheduler** в lifespan FastAPI (еженедельные рассылки REQ-2;
   Celery не нужен).
3. `.env`: `CHAT_TEST_SPACE=spaces/7UqhjKAAAAE` (твой DM с ботом — уже существует).
4. Тестовый эндпоинт или скрипт «отправить сейчас» → проверка вручную.

**Проверка:** бот сам (без твоего сообщения) пишет тебе в DM сообщение с заданным текстом.

**Ограничения app-auth:** бот пишет только в пространства, где он участник.
Для авто-онбординга всех сотрудников домена (REQ-1.2) — установка приложения на домен
(Фаза B, админ).

**Альтернатива без SA:** user-OAuth мостик (`english-bot/auth.py` + `messenger.py`,
уже работает) — сообщения от имени организатора; refresh-токен умирает через 7 дней
в Testing-режиме, поэтому SA — основной путь.

**Фаза B (когда появится админ Workspace):** domain-wide delegation на тот же SA →
Calendar API (события с Meet-ссылкой, REQ-3.7) и Meet API (посещаемость, REQ-6.1);
установка Chat App на домен; app-auth одобрение. Шаблон письма админу —
в `studotryad — копия/docs/deployment_plan.md`.

---

## 10. Итог сессии 1: важные факты о формате (выяснены боём)

- **Наш Chat App получает события в формате Google Workspace Add-on**, а не в классическом
  формате interaction events: событие внутри ключа `"chat"`, сообщение — в `"chat.messagePayload"`,
  добавление в пространство — в `"chat.addedToSpacePayload"` (см. `app/api/google_chat.py`, ветка 3a).
  Классический формат оставлен как fallback (ветка 3b).
- **Ответ обязан быть обёрнут** в `{"hostAppDataAction": {"chatDataAction": {"createMessageAction": {"message": {...}}}}}`
  — голый `{"text": ...}` или `{"cardsV2": ...}` Google молча игнорирует
  (подтверждено доками: developers.google.com/workspace/add-ons/chat/send-messages).
- **Audience в JWT = URL endpoint'а** (`https://.../webhooks/google-chat`), а НЕ Project Number —
  значение берётся из поля Authentication audience в Configuration и должно совпадать до символа.
- JWT-токен приходит в заголовке `Authorization: Bearer <jwt>`; валидация —
  `google.oauth2.id_token.verify_oauth2_token` (см. `_verify_chat_jwt`).
- ngrok-домен: `renewed-ditto-knee.ngrok-free.dev`; при смене домена — обновить
  endpoint URL в Configuration И `CHAT_APP_AUDIENCE` в `.env` (они связаны).
- Событие ADDED_TO_SPACE при открытии DM срабатывает один раз; для повторной проверки
  карточки нужно удалить диалог с ботом и найти его заново.
