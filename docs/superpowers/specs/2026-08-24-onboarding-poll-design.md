# Онбординг новых участников поллингом

Дата: 2026-08-24

## Цель

Бот периодически проверяет участников группы и приглашает в онбординг новых —
тегает в группу или шлёт анкету в личку. Вместо событий Google (которые не шлются
через вебхук без Events API подписки).

## Решения

- **Поллинг** — джоб каждые 10 минут → `check_new_members(db, space_id)`.
- **Маркер** — `Profile.onboarding_invite_sent: bool` (default False): не тегать повторно.
  Сбрасывается в `mark_onboarded` (при прохождении онбординга).
- **Каналы** — есть `chat_space_id` → анкета в личку; нет → `@упоминание` в группу.
- Прошлый вебхук-фикс `MEMBERSHIP_ADDED` оставляем (безвреден).

## Модули

- `app/models.py` — поле `onboarding_invite_sent` + миграция Alembic.
- `app/services/space_onboarding.py` — `check_new_members(db, space_name) -> {dm, mention}` (план + маркировка).
- `app/services/onboarding.py` — сброс маркера в `mark_onboarded`.
- `app/scheduler.py` — джоб `_poll_new_members` (cron 10 мин), отправка по плану.

## Вне скоупа

- Events API подписка. Поллинг достаточен для онбординга.
