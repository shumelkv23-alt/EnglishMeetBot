# EnglishMeetBot: ENG-5 + ENG-7 — опрос с LLM-вопросами и приглашения (дизайн)

> Дата: 2026-08-20. Автор: Кирилл. Статус: утверждён (20.08.2026).
> Параллельно идёт: ENG-6 (Тиммейт B), ENG-8 (Тиммейт A). Эта спека не меняет их контракты.

## 1. Контекст и цель

ENG-5 и ENG-7 — задачи Кирилла, выполняются параллельно с задачами ребят:

- **ENG-5** (REQ-2, REQ-3.1–3.2): еженедельный опрос в DM: 2 вопроса + голосование за слоты.
  Новое: один из вопросов — **персональный, сгенерированный LLM** под интересы участника
  (OpenRouter), второй — из банка (общий). Фолбэк при недоступности LLM — банк (REQ-10).
- **ENG-7** (REQ-5, REQ-6.2, REQ-9): по `TIME_FINALIZED` — личные приглашения + пост в Space,
  напоминание T−1ч, окно self-check-in; по `ESCALATED` — уведомление организатору.

Стыковка с ребятами — только через контрактные сигнатуры (`advance_state`, `generate_activity`),
которые заморожены. Никакой код этой спеки не требует их файлов.

## 2. Принятые решения

1. **Подход Б: пакетная генерация заранее.** Перед рассылкой карточек LLM-вопросы
   генерируются пакетом и сохраняются в БД; рассылка собирает карточки из готового.
   Повторный запуск не генерирует заново (идемпотентность по `UNIQUE (poll_id, profile_id)`).
2. **Провайдер: OpenRouter** — один ключ, модель конфигурируется (`LLM_MODEL`),
   дефолт — бесплатная free-модель (уточнить при первой живой проверке).
3. **Персонализация:** сгенерированный вопрос = персональный (по `profiles.interests`);
   второй вопрос = общий из банка (детерминирован по неделе).
4. **Новая таблица `poll_questions`** для сгенерированных вопросов; `answers` для неё
   не подходит (CHECK `valid_answer` запрещает вопрос без ответа; нет ключа идемпотентности;
   семантика «история ответов» не совпадает).
5. **Дедлайн считает Кирилл:** `deadline = min(время слотов) − VOTING_BUFFER_HOURS`
   (REQ-2.3). `advance_state` Тиммейта B принимает его готовым; вызов — после мержа ENG-6.
6. **`advance_state` ничего не шлёт** (контракт v2): все уведомления после голосования — ENG-7.
7. **Calendar с Meet-ссылкой — заглушка** (Фаза B, нужен domain-wide delegation и админ).

## 3. Данные: миграция

```sql
CREATE TABLE poll_questions (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    poll_id       BIGINT NOT NULL REFERENCES weekly_polls(id),
    profile_id    BIGINT NOT NULL REFERENCES profiles(id),
    question_text TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (poll_id, profile_id)
);
```

- Только для LLM-вопросов. Банковский вопрос в БД не хранится:
  `index = iso_week_number % len(BANK)`, неделя из `date.isocalendar()`.
- SQLAlchemy-модель `PollQuestion` в `app/models.py` + alembic-ревизия. Только Кирилл.

## 4. Модули и интерфейсы

### 4.1. `app/services/question_bank.py` — банк вопросов
- `BANK: list[str]` — 20+ лёгких разговорных вопросов («фильм, который пересмотрел» и т.п.).
- `bank_question_for(week_start: date) -> str` — вопрос недели (общий для всех), ротация
  без повторов пока банк не исчерпан.

### 4.2. `app/services/llm_questions.py` — генерация (OpenRouter)
- `generate_personal_question(interests: list[str]) -> str | None`:
  один вызов `POST https://openrouter.ai/api/v1/chat/completions`,
  `response_format={"type": "json_object"}`, промпт требует `{"question_text": "..."}`;
  таймаут 10с, 1 ретрай, любое исключение/невалидный JSON → `None`.
- `generate_for_profiles(db, poll, profiles) -> None`: пакет по всем активным профилям,
  результат — upsert в `poll_questions` (`INSERT ... ON CONFLICT (poll_id, profile_id) DO UPDATE`).
- Приватность: в промпт уходят только `interests` (данные, которые юзер сам дал на подбор).

### 4.3. `app/services/weekly_poll.py` — жизнь опроса
- `ensure_weekly_poll(db, now) -> WeeklyPoll`: активный опрос на неделю есть → вернуть;
  иначе создать с дедлайном `min(слоты) − VOTING_BUFFER_HOURS`. Слоты: из `config`
  (JSON `[{day, time}, ...]`); пусто → автокопия слотов прошлой недели (REQ-10).
- `build_card(profile, personal_q, bank_q, slots) -> dict`: Cards V2 — 2 textInput
  (`q_llm`, `q_bank`) + selectionInput чекбоксы слотов + кнопка «Отправить» (method=`submit_weekly_poll`).
  Паттерн карточки — как у онбординга.
- `send_weekly_polls(db, now) -> int`: шаг 1 `ensure_weekly_poll`; шаг 2 генерация LLM;
  шаг 3 рассылка активным профилям без ответа в этой неделе (`poll_responses.status != 'responded'`)
  через `send_message`; шаг 4 `poll_responses` = pending (reminder_count=0).
- `submit_poll(db, profile, form_inputs) -> bool`: сабмит карточки. Если опрос недели закрыт
  (`voting_deadline` прошёл) — отклоняем (REQ-9.4). Иначе:
  тексты вопросов → `answers` (история; для LLM-вопроса `question_rotation_id=None`);
  слоты → `poll_votes`: delete+insert в транзакции (идемпотентно, триггер счётчика обновит).

### 4.4. `app/api/google_chat.py` — новые ветки диспетчера
- `submit_weekly_poll` (buttonClickedPayload, add-on формат, паттерн `submit_onboarding`).
- Проверка окна check-in будет добавлена в ENG-7 **после мержа** этой ветки (обе трогают вебхук).

### 4.5. `app/services/invites.py` — приглашения (ENG-7)
- `notify_time_finalized(db, instance, activity | None) -> None`: персональные приглашения
  всем ответившим на опрос (время из `final_slot`, тема из `Activity` или дефолтный текст)
  + один пост в общий Space (id из `config`).
- `notify_escalated(db, instance) -> None`: одно сообщение организатору (id из `config`).

### 4.6. `app/services/reminders.py` — отложенные задачи (ENG-7)
- `schedule_for(instance with scheduled events)`: при `TIME_FINALIZED` —
  джоб напоминания T−1ч с id `remind_{instance_id}` (REQ-9.2: перезапись, не дубль);
  при изменении времени — remove + add (REQ-9.3).
- `restore_on_startup()`: при старте приложения пересоздать джобы из `meeting_instances`
  (status=scheduled).

### 4.7. `app/services/checkin.py` — окно посещаемости (ENG-7)
- Два джоба от `TIME_FINALIZED`: открыть окно (T−15 мин), закрыть (T+15 мин) — REQ-9.6.
- Клик «Я на встрече ✅» → проверка окна → `attendance` (source=self_checkin,
  status=present, `is_within_window`), ошибка вне окна — не засчитываем (REQ-10).

### 4.8. `app/scheduler.py` — APScheduler
- Еженедельный джоб опроса (день/час из `config`); heartbeat-джоб вызова `advance_state`
  (после мержа ENG-6); джобы ENG-7 ставятся по событиям.

## 5. Конфигурация и секреты

- `.env`: `OPENROUTER_API_KEY`. `.env.example` — плейсхолдер. В `.gitignore` не попадает (не секрет пути).
- `config`-таблица (ключи с дефолтами в коде): `LLM_MODEL`, `WEEKLY_POLL_DAY`,
  `WEEKLY_POLL_HOUR`, `VOTING_BUFFER_HOURS` (24), `ORGANIZER_USER_ID`,
  `SPACE_ID` (общий Space), `CHECKIN_WINDOW_MIN` (15), `MEET_REMINDER_HOURS` (1).
- `app/config.py` (pydantic-settings): только `OPENROUTER_API_KEY` + `LLM_MODEL` из env.

## 6. Ошибки и фолбэки (REQ-10)

| Сбой | Поведение |
|---|---|
| OpenRouter ошибка/таймаут/невалидный JSON | вопрос = из банка (нет записи в `poll_questions` → карточка берёт 2 банковских) |
| Рассылка упала на середине | повторный запуск джоба: идемпотентно по `poll_questions` и `poll_responses` |
| Голосование никто не открыл | эскалация (без криков): см. ENG-7 после мержа ENG-6 |
| LLM недоступен целиком | банк, ничего не блокируется |

## 7. Тестирование (локально, без бота)

- Юниты (pytest): банк-ротация, формула дедлайна, карточка (структура), submit (сабмит
  закрытого опроса отклонён), окно check-in, тексты приглашений, id джобов remind.
- `llm_questions` — с моком `requests.post` (успех / таймаут / кривой JSON).
- Вебхук — curl с `SKIP_JWT_VALIDATION=true` (паттерн PLAN.md).
- Рассылка E2E — временная задача «отправить сейчас» (как на этапе 9C).
- Стыковочные тесты ENG-6/ENG-8 — после их мержей.

## 8. Вне скоупа (сознательно)

- Calendar/Meet API (Фаза B, нужен админ) — интерфейс-заглушка.
- Напоминания об опросе (поля `reminder_count`/`next_reminder_at` готовы — следующий шаг).
- Реальный `send_message` (стаб → chat_sender) — после прогона всех цепочек на стабе.
- Интерактив «Угадай коллегу» голосование и лидерборд — другие задачи/этапы.

## 9. Критерии готовности

1. Миграция `poll_questions` накатана; модель в `models.py`.
2. Банк + генерация работают: с моком и, вручную, с реальным ключом (1 запрос).
3. Один ручной запуск «отправить сейчас» → в логах стаба `[STUB SEND]` для каждого
   участника с карточкой опроса (2 вопроса + слоты).
4. curl-сабмит карточки → в `answers` 2 записи, в `poll_votes` голоса; повторный сабмит
   не дублирует; сабмит закрытого опроса отклонён.
5. После мержа ENG-6: heartbeat → `TIME_FINALIZED`/`ESCALATED` → ENG-7 цепочка
   (приглашения в логах стаба, джобы remind/checkin видны в APScheduler, эскалация организатору).
6. Все новые юниты зелёные; ветки ENG-5 и ENG-7 смержены в main в этом порядке.