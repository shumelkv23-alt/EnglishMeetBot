# Развёртывание «параллельного» EnglishMeetBot — инструкция для второго разработчика

> Этот документ — пошаговая инструкция, как поднять **точно такой же бот, как у Кирилла**,
> у себя локально: тот же функционал (онбординг-карточка, сохранение ответов в PostgreSQL,
> проактивные DM-рассылки через сервисный аккаунт).

## 0. Важно понять до старта (5 минут чтения)

**Почему нельзя «просто скопировать настройки»:** у Google Chat приложение — это конфигурация
в конкретном GCP-проекте, а конфигурация указывает на **один** HTTP endpoint. У Кирилла endpoint —
это его ngrok. У тебя будет **свой** ngrok, поэтому нужен **свой** Chat App:

| Компонент        | У Кирилла                        | У тебя (новый)                    |
|------------------|----------------------------------|-----------------------------------|
| GCP-проект       | `english-meet-assistant`         | свой проект (любое имя)           |
| Chat App         | `EnglishMeetBot`                 | своё имя, например `EnglishMeetBot2` |
| ngrok-домен      | `renewed-ditto-knee.ngrok-free.app` | свой статический домен (бесплатный) |
| Сервисный аккаунт| `english-meet-sender`            | свой SA в своём проекте           |
| PostgreSQL       | docker `meet_bot_db` (порт 5432) | свой контейнер (если твой 5432 занят — см. п. 2) |

Код один и тот же — берётся из проекта Кирилла. Настройка «под себя» — только через `.env` и GCP-консоль.

**Требования к железу/ПО:**
- Python 3.11+ (у нас проверено на 3.14)
- Docker Desktop (для PostgreSQL)
- Учётка Google (для GCP + Google Chat)
- Учётка ngrok (бесплатная)

---

## 1. Получить код и подготовить окружение

Скопировать у Кирилла папку проекта `english-meet-bot` (git-клонировать или архивом).
Принести локально. Далее все команды — из корня проекта.

Проверить версии:

```powershell
python --version        # >= 3.11
docker --version        # Docker Desktop запущен
```

## 2. Поднять PostgreSQL

```powershell
docker compose up -d db
```

Проверка (контейнер должен быть healthy):

```powershell
docker ps --filter name=meet_bot_db
```

⚠️ Если порт 5432 уже занят другим Postgres — в `docker-compose.yml` сменить
`"5432:5432"` на `"5433:5432"` и в `.env` поставить `DB_PORT=5433`.

## 3. Виртуальное окружение и зависимости

```powershell
python -m venv venv
.\venv\Scripts\pip install -r requirements.txt
```

macOS/Linux: `python3 -m venv venv && venv/bin/pip install -r requirements.txt`

## 4. Файл `.env`

Скопировать шаблон и заполнить:

```powershell
Copy-Item .env.example .env
```

Минимально для локального старта (все значения по умолчанию из примера подойдут,
кроме `CHAT_APP_AUDIENCE` — его заполним на шаге 7):

```env
POSTGRES_USER=meet_bot_user
POSTGRES_PASSWORD=супер-секретный-пароль
POSTGRES_DB=english_meet_db
DB_HOST=localhost
DB_PORT=5432
SKIP_JWT_VALIDATION=true        # пока не настроен аудиенс — не блокирует локальные тесты
CHAT_APP_AUDIENCE=              # пусто до шага 7
GOOGLE_SA_KEY_FILE=sa-key.json  # появится на шаге 8
CHAT_TEST_SPACE=                # появится на шаге 9
```

## 5. Миграции БД + запуск

Создать схему (10 таблиц + триггеры + служебные записи config):

```powershell
.\venv\Scripts\alembic upgrade head
```

Запустить приложение (в отдельном окне терминала):

```powershell
.\venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

Проверка:

```powershell
Invoke-RestMethod -Uri http://localhost:8000/api/v1/health
# -> {"status": "ok", "database": "connected"}
```

✅ С этого момента код работает локально. Дальше — привязка к Google Chat.

## 6. Плашка: какой формат событий у бота

Бот принимает **оба** формата событий Google Chat:
- классический interaction event (`type`/`user`/`message` на верхнем уровне),
- формат Workspace Add-on (обёртка `chat.messagePayload` / `chat.addedToSpacePayload`).

Ответы на аддон-формат оборачиваются в `hostAppDataAction` — это уже реализовано,
**ничего настраивать не нужно**, просто имей в виду, что в GCP-консоли галку
«Build this Chat app as a Workspace add-on» ставить не обязательно. Код переживёт любой путь.

## 7. Свой GCP-проект и Chat App (самый важный шаг)

### 7.1. Создать проект

1. https://console.cloud.google.com → New Project → имя, например `my-english-bot`.
2. Внутри проекта включить API: **APIs & Services → Library → Google Chat API → Enable**.

### 7.2. Зарегистрировать Chat App

1. **Google Chat API → Configuration** (или Manage) → **+ Add Chat app / Create**.
2. Заполнить:
   - **App name**: `EnglishMeetBot2` (уникальное имя — по нему бот ищется в Google Chat)
   - **App avatar** — картинка по желанию
   - **Connection settings → HTTP endpoint URL** — сюда поставим ngrok-URL (шаг 7.3)
   - **Authentication audience** — читай ниже
   - **App status: LIVE**
   - **Functionality**: отметить «Receive 1:1 messages» и «Join group conversations»
3. **Audience для JWT (важно!):** в этом проекте Chat App работает как Workspace Add-on,
   и Google валидирует токены по полю **Authentication audience**, которое должно **посимвольно
   совпадать** с `CHAT_APP_AUDIENCE` в `.env`. Значение = **URL твоего endpoint'а**:

   ```
   https://<твой-домен>.ngrok-free.app/webhooks/google-chat
   ```

   То есть: сначала запускаешь ngrok (7.3), потом endpoint URL И audience в конфиге Google
   заполняешь одним и тем же URL, и то же самое пишешь в `.env` → `CHAT_APP_AUDIENCE`.
4. **Visibility**: если твой аккаунт в том же Workspace-домене, что и у Кирилла —
   бот найдётся поиском после статуса LIVE и (если домен строгий) после добавления твоего
   аккаунта в Testing users на OAuth consent screen (Google Cloud → APIs & Services →
   OAuth consent screen → Test users → + Add Users — добавить свой аккаунт).
   ВНИМАНИЕ: неопубликованный Chat App доступен только аккаунтам того же Workspace-домена.
   Если твой аккаунт с другого домена/личный Gmail — понадобится публикация в Marketplace
   (ревью Google) — это отдельная история, для локальной разработки лучше взять доменный аккаунт.
5. **Save Changes.** Изменения применяются до ~5 минут.

### 7.3. Свой ngrok (отдельная учётка!)

1. Скачать ngrok (https://ngrok.com/download), зарегистрироваться, получить авторизационный токен:
   ```powershell
   ngrok config add-authtoken <твой-токен>
   ```
2. Бесплатный **статический домен**: https://dashboard.ngrok.com → Domains → New Domain →
   получить свой `что-то.ngrok-free.app` (постоянный, не меняется между перезапусками).
3. Запустить туннель (отдельное окно терминала):
   ```powershell
   ngrok http --domain=что-то.ngrok-free.app 8000
   ```

### 7.4. Финальный `.env`

```env
CHAT_APP_AUDIENCE=https://что-то.ngrok-free.app/webhooks/google-chat
SKIP_JWT_VALIDATION=false
```

Перезапустить uvicorn. Проверить туннель: открыть браузером
`https://что-то.ngrok-free.app/api/v1/health` → JSON «ok».

## 8. Сервисный аккаунт (для проактивных DM-рассылок)

1. GCP-консоль → тот же проект → **IAM & Admin → Service Accounts → + Create Service Account**
   (имя любое, роль не нужна).
2. Открыть аккаунт → **Keys → Add Key → Create new key → JSON** → сохранить.
3. Файл положить в корень проекта как `sa-key.json`.
4. `.env`: `GOOGLE_SA_KEY_FILE=sa-key.json`.
5. ⚠️ Файл `sa-key.json` — секрет: он уже в `.gitignore`, в репозиторий его не заливать.

## 9. Проверка бота в живом Google Chat

1. Google Chat → «Новый чат» → поиск по имени бота (`EnglishMeetBot2`) → открыть DM.
   У бота появится приветственная карточка онбординга (5 вопросов + блок про приватность).
2. Написать «привет» → бот ответит. Написать что-нибудь ещё → эхо-ответ.
3. Проверить, что ответы записались в БД:
   ```powershell
   docker exec meet_bot_db psql -U meet_bot_user -d english_meet_db -c "SELECT id, user_name, chat_space_id FROM profiles;"
   docker exec meet_bot_db psql -U meet_bot_user -d english_meet_db -c "SELECT profile_id, answer_text FROM answers;"
   ```

Если бот молчит:
- ngrok inspector (http://localhost:4040) — приходят ли POST на `/webhooks/google-chat`?
  Нет → endpoint URL в конфиге Google не совпал. 401 → audience не совпал до символа
  (сверь `CHAT_APP_AUDIENCE` и поле Authentication audience в консоли Google).

## 10. Проактивные рассылки (функционал «бот сам пишет первым»)

Рассылки работают только в DM, где бот **уже участник** (т.е. ты хотя бы раз написал ему —
такое пространство он отлично видит через API).

1. Узнать свой DM-space. После первого сообщения боту профиль создан, но `chat_space_id`
   мог не записаться — это нормально, есть автозаполнение:
   ```powershell
   .\venv\Scripts\python -m scripts.backfill_dm_spaces
   ```
   В выводе должен появиться `user_name: DM = spaces/XXXX`.
2. `CHAT_TEST_SPACE` в `.env` = этот `spaces/XXXX` (можно подсмотреть в БД — запрос выше).
3. Тест отправки:
   ```powershell
   .\venv\Scripts\python -m scripts.test_send_dm --text "Привет! Это тест рассылки."
   ```
4. Рассылка всем, кто писал боту (осторожно — шлёт реально, всем профилям с известным DM):
   ```powershell
   .\venv\Scripts\python -m scripts.test_broadcast_writers --text "Еженедельное напоминание о созвоне."
   ```
5. Рассылка участникам конкретного space (шлёт только тем, у кого есть профиль и DM):
   ```powershell
   .\venv\Scripts\python -m scripts.test_broadcast_space --space spaces/XXXX --text "Напоминание для участников группы."
   ```

Ограничение: бот пишет только в пространства, где он состоит. Чтобы делать
авто-онбординг всех сотрудников домена — нужна установка приложения на домен
(доступ администратора Workspace), это отдельная фаза.

## 11. Чек-лист «запустился как у Кирилла»

- [ ] `docker compose up -d db` — контейнер healthy
- [ ] `alembic upgrade head` — 10 таблиц, без ошибок
- [ ] uvicorn на 8000, `/api/v1/health` → `{"status": "ok", "database": "connected"}`
- [ ] Свой статический ngrok-домен, туннель на 8000
- [ ] Каноничный GCP-проект: Chat API enabled, свой Chat App, App status = LIVE
- [ ] endpoint URL и Authentication audience в GCP = `${CHAT_APP_AUDIENCE}` в `.env` (посимвольно)
- [ ] Отыскал бота поиском в Google Chat, получил онбординг-карточку
- [ ] Ответ «привет» работает, в `profiles` и `answers` появились записи
- [ ] SA-ключ `sa-key.json` на месте, в `.gitignore`, `GOOGLE_SA_KEY_FILE` в `.env`
- [ ] `backfill_dm_spaces` нашёл твой DM; `test_send_dm` доставил сообщение
- [ ] `test_broadcast_writers` разослал всем писавшим

## 12. Частые грабли

| Проблема | Причина | Решение |
|----------|---------|---------|
| Порт 5432 занят | другой Postgres | сменить маппинг в docker-compose + `DB_PORT` в `.env` |
| Бот не ищется поиском | App status не LIVE / политики домена / не прошло 5 минут | статус LIVE; добавить себя в Test users; подождать |
| 401 в ngrok inspector | audience не совпал | сверить посимвольно `CHAT_APP_AUDIENCE` и поле в консоли |
| Нет запросов в inspector | не тот endpoint URL | проверить Connection settings в GCP |
| Бот отвечает с задержкой/молчит | Google ждёт ответ вебхука до 15 секунд | в логах uvicorn смотреть ошибки (БД недоступна и т.п.) |
| `send_text` падает с 403/404 | SA не имеет прав / не то пространство | проверить заголовок ключа, `spaces/` перед id |
| Рассылка никому не ушла | у профилей нет DM с ботом | сначала сам напиши боту, потом `backfill_dm_spaces` |

---

*Документ составлен на основе реально развёртываемого проекта `english-meet-bot`
(проверено 2026-08-19). Версии зависимостей зафиксированы в `requirements.txt`.*