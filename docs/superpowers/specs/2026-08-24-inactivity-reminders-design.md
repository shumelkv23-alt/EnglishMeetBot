# Спек: напоминания о неактивности (inactivity reminders)

> Дата: 2026-08-24
> Статус: на ревью у Кирилла
> Проект: `english-meet-bot`

## 1. Цель

Мягко напоминать участникам, которые долго не проявляют активность в группе или в боте,
чтобы они «не забыли» о встречах. Напоминание уходит **только в личку (DM)** и не давит:
это пинг «мы ещё тут», а не механизм принуждения или деактивации.

## 2. Требования (зафиксированы с Кириллом)

| Параметр | Значение |
|----------|----------|
| Что сбрасывает неактивность | любое из 4 событий: голос в дневном опросе, ответ на вопрос недели, check-in на встрече, сообщение боту |
| Порог неактивности (N) | **7 дней** полного молчания |
| Куда слать | **только DM** |
| Каденс повторов | **раз в 3 дня** |
| Лимит напоминаний (M) | **3 раза** подряд, потом остановиться |
| Что после лимита | ничего не шлём, пока человек снова не проявит активность |
| Цель | «не дать забыть» — мягкий, неагрессивный тон |

## 3. НЕ делаем (осознанно)

- НЕ деактивируем неактивных (`is_active` не трогаем; ключ `max_inactive_days` остаётся мёртвым).
- НЕ шлём в группу и не используем публичные `@упоминания` (стыд — не наш метод).
- НЕ наращиваем агрессивность текста от повтора к повтору.
- НЕ строим полный event-sourcing / аналитику активности (overkill для этой цели).

## 4. Ключевое архитектурное решение

**Определяем «последнюю активность» через новое поле `profiles.last_activity_at`** (подход B),
а не вычисляем из существующих таблиц. Причины:

- Одно поле → один дешёвый запрос `WHERE last_activity_at < now() - interval`.
- Покрывает все 4 события, включая «сообщение боту», которое сейчас нигде не сохраняется.
- Явно и предсказуемо: обновляем поле ровно там, где случается событие активности.

Отвергнутые альтернативы: вычисление `MAX()` по `poll_votes`/`answers`/`attendance`
(тяжело и не покрывает сообщения) и отдельная таблица `activity_log` (YAGNI).

## 5. Модель данных (миграция `0005_inactivity_reminders`)

В таблицу `profiles` добавляются три колонки:

| Колонка | Тип | Назначение |
|---------|-----|------------|
| `last_activity_at` | `TIMESTAMPTZ NULL` | момент последнего события активности |
| `reminder_count` | `INTEGER NOT NULL DEFAULT 0` | сколько напоминаний подряд уже отправлено |
| `last_reminder_at` | `TIMESTAMPTZ NULL` | момент отправки последнего напоминания |

В `models.py` (класс `Profile`) добавляются соответствующие `mapped_column`.

Сидинг в `config` (тем же паттерном, что и существующие ключи):

| Ключ | Значение | Назначение |
|------|----------|------------|
| `inactivity_reminder_days` | `7` | порог неактивности, дней |
| `inactivity_reminder_interval_days` | `3` | интервал между повторами, дней |
| `inactivity_max_reminders` | `3` | максимум напоминаний подряд |
| `inactivity_reminder_hour` | `11` | час запуска джоба (в таймзоне приложения) |

## 6. Событие активности = сброс серии

Определяем хелпер (в `app/services/inactivity.py`):

```python
def touch_activity(profile: Profile, now: datetime) -> None:
    """Зафиксировать активность: сбросить счётчик напоминаний и обновить время."""
    profile.last_activity_at = now
    profile.reminder_count = 0
    profile.last_reminder_at = None
```

Вызывается в четырёх местах **перед** `commit` соответствующей сессии:

1. `app/services/weekly_poll.py` → `submit_poll()` — успешный сабмит дневного опроса
   (любой выбор, включая «не могу»).
2. `app/services/weekly_questions.py` → `submit_weekly_question()` — успешный ответ на
   вопрос недели.
3. `app/services/checkin.py` → `submit_checkin()` — self-check-in (независимо от
   `within`, т.к. сам клик уже активность).
4. `app/api/google_chat.py` → обработка `MESSAGE` в **обеих** ветках:
   - add-on (`chat.messagePayload`): внутри уже существующего блока с `get_or_create_profile`;
   - classic (`type == "MESSAGE"`): ветку нужно дополнить блоком БД
     (`get_or_create_profile` + `touch_activity`), сейчас она БД не трогает.

## 7. Сервис `app/services/inactivity.py`

Одна ответственность — неактивность и напоминания. Чистые функции (без БД/сети)
вынесены отдельно для юнит-тестов.

```python
def is_inactive(profile: Profile, now: datetime, days: int) -> bool:
    """Неактивен ли профиль: с последней активности прошло >= days.
    Если last_activity_at не задан — точкой отсчёта служит created_at."""
    base = profile.last_activity_at or profile.created_at
    if base is None:
        return False  # не бывает: created_at всегда есть
    return (now - base).days >= days


def should_remind(
    profile: Profile, now: datetime, interval_days: int, max_reminders: int
) -> bool:
    """Нужно ли слать напоминание: лимит не исчерпан и интервал выдержан."""
    if profile.reminder_count >= max_reminders:
        return False
    if profile.last_reminder_at is None:
        return True
    return (now - profile.last_reminder_at).days >= interval_days


async def remind_inactive(db: AsyncSession) -> int:
    """Найти неактивных активных участников и отправить им напоминание в DM.
    Возвращает количество отправленных напоминаний."""
    # 1. читает параметры из config (с fallback на дефолты выше)
    # 2. select Profile where is_active == true and chat_space_id is not null
    # 3. для каждого: если is_inactive(...) и should_remind(...) —
    #      send_message(workspace_user_id, MessagePayload(text=REMINDER_TEXT))
    #      profile.reminder_count += 1; profile.last_reminder_at = now
    # 4. commit; вернуть sent
```

Отправка — через `app.messaging.send_message()` (единственная граница отправки, как во
всём проекте). Фильтр `chat_space_id is not null` гарантирует, что DM известен.

## 8. Джоб в планировщике

В `app/scheduler.py`:

```python
async def _run_inactivity_reminder() -> None:
    from app.services.inactivity import remind_inactive
    async with AsyncSessionLocal() as db:
        sent = await remind_inactive(db)
        logger.info("inactivity_reminder_job sent=%s", sent)
```

Регистрация в `init_scheduler()`:

```python
scheduler.add_job(
    _run_inactivity_reminder,
    "cron",
    hour=int((await get_or_create_config(db, "inactivity_reminder_hour", 11)).value or 11),
    minute=0,
    id="inactivity-reminder",
    replace_existing=True,
    misfire_grace_time=3600,
)
```

## 9. Текст напоминания

Единый для всех повторов:

> Привет! 👋 Давно тебя не было. У нас каждый день короткие встречи по английскому —
> заглядывай, если будет минутка. Если формат не зашёл — просто напиши, подстроимся.

## 10. Граничные случаи

- `last_activity_at IS NULL` (профиль создан, но событий активности не было) →
  точка отсчёта `created_at` (см. `is_inactive`).
- Активность после серии напоминаний → `touch_activity` обнуляет `reminder_count`
  и `last_reminder_at`; новая серия молчания начинается заново.
- Достигнут лимит (3) → `should_remind` возвращает `false`, пинги прекращаются
  до следующей активности.
- Профиль без DM (`chat_space_id IS NULL`) → пропускаем (некуда слать).
- `is_active = false` → пропускаем.
- Время: сравнение «N дней» в **UTC** (`datetime.now(timezone.utc)`); расписание джоба —
  в таймзоне приложения (`app_timezone`, сейчас `Europe/Minsk`). Это соответствует
  существующему подходу проекта.

## 11. Тестирование

### Юнит (`tests/test_inactivity_units.py`)
- `is_inactive`: активен (< N дней) / неактивен (>= N дней) / fallback на `created_at`
  при `last_activity_at = None`.
- `should_remind`: первое напоминание (`last_reminder_at = None`) → True;
  интервал не выдержан → False; лимит `reminder_count >= max` → False.
- `touch_activity`: сбрасывает `reminder_count` и `last_reminder_at`, ставит
  `last_activity_at = now`.

### Интеграция (`tests/e2e/`, по образцу существующих)
- `remind_inactive` отправляет напоминание неактивному профилю и инкрементит счётчик;
- на 4-й раз (лимит 3) — не отправляет;
- после `touch_activity` напоминания возобновляются.

## 12. Критерии приёмки

1. Миграция `0005` применяется без ошибок, колонки и config-ключи на месте.
2. Джоб `inactivity-reminder` есть в планировщике и запускается по расписанию.
3. Неактивный 7+ дней участник получает DM-напоминание раз в 3 дня, максимум 3 раза.
4. Любое из 4 событий активности сбрасывает счётчик и обновляет `last_activity_at`.
5. Юнит-тесты на `is_inactive` / `should_remind` / `touch_activity` проходят.
6. Никто не деактивируется и не упоминается публично.
