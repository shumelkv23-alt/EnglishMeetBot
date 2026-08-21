# English Meet Bot

Бот для Google Chat, который помогает организовывать разговорные встречи для изучения английского: проводит онбординг новых участников, рассылает приглашения и напоминания через DM.

## Возможности

- **Онбординг** — пошаговое знакомство с участником прямо в Google Chat (карточки с кнопками)
- **Рассылки** — отправка сообщений участникам через сервисный аккаунт Google (проактивные DM)
- **Хранение данных** — PostgreSQL с миграциями Alembic (SQLAlchemy 2 async)

## Стек

| Компонент | Технология |
|-----------|-----------|
| API | Python 3.14, FastAPI 0.111 |
| БД | PostgreSQL 15, SQLAlchemy 2 (async), asyncpg |
| Миграции | Alembic |
| Интеграция | Google Chat API, google-auth (сервисный аккаунт) |
| Деплой | Docker / Docker Compose |

## Быстрый старт

1. Скопируй `.env.example` в `.env` и заполни значения:
   ```bash
   cp .env.example .env
   ```
   Важно: `sa-key.json` (ключ сервисного аккаунта) не коммить — он уже в `.gitignore`.

2. Запусти через Docker Compose:
   ```bash
   docker compose up --build
   ```

3. Примени миграции:
   ```bash
   alembic upgrade head
   ```

Без Docker (локально): `uvicorn app.main:app --reload`

## Структура проекта

```
app/
  api/          # эндпоинты: вебхуки Google Chat, health-check
  services/     # онбординг, рассылки, отправка сообщений в Chat
  main.py       # точка входа FastAPI
  models.py     # модели SQLAlchemy
  schemas.py    # Pydantic-схемы
alembic/        # миграции БД
scripts/        # диагностические и тестовые скрипты
```


