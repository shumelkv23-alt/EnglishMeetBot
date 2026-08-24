# Активности — Этап A: каркас (слеш-команды + регистрация + очки)

Дата: 2026-08-24

## Цель

Общий каркас для игр-активностей: слеш-команды, сессия игры в памяти,
регистрация участников и начисление очков в `leaderboard_ledger`.
На этот каркас нанизываются конкретные игры (Quiplash, Guesspionage, Шпион).

## Решения

- **Слеш-команды** — сообщение `MESSAGE` с текстом, начинающимся на `/`
  (`/quiplash`, `/guesspionage`, `/spy`). Нативные slash-команды Google — вне скоупа.
- **Сессия** — in-memory словарь `{space_id: GameSession}` (синглтон `GameManager`).
  Игры короткие, рестарт бота во время игры не переживаем.
- **Очки** — `leaderboard_ledger` (`event_type="bonus"`, `reason=<игра>`, `meeting_instance_id=NULL`).
- **Регистрация** — карточка «Кто играет?» с кнопкой «Я в деле» (`method=join_game`).

## Модули

```
app/services/games/
  __init__.py
  session.py     # GameSession, GameManager (in-memory)
  scores.py      # award_points -> leaderboard_ledger
  registry.py    # команда -> тип игры (заглушка, игры подключаются в B/C/D)
```

## Интерфейсы

- `GameManager.start(game, space_id) -> GameSession`
- `GameManager.get(space_id) -> GameSession | None`
- `GameManager.end(space_id) -> None`
- `award_points(db, profile_id, points, reason) -> None`
- `_is_slash_command(text) -> str | None` (в `google_chat.py`)

## Флоу

1. Пользователь пишет `/quiplash` в группе.
2. Бот: если игры ещё нет — создать сессию, показать карточку «Кто играет?».
3. Участники жмут «Я в деле» → `join_game` добавляет их в `session.players`.
4. Когда все готовы — бот запускает игру (передаёт управление конкретной игре).

## Вне скоупа

- Конкретная механика игр (Этапы B/C/D).
- Нативные slash-команды, лидерборд-вывод.
