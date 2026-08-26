# Дизайн: уровни (CEFR), кворум 4, персонализированные вопросы и лексика

- **Дата:** 2026-08-26
- **Статус:** на ревью
- **Тип:** architectural (новый сабсистем персонализированной лексики + изменения онбординга/вопросов/кворума)

## Цель

1. Спрашивать у пользователя уровень английского в онбординге (CEFR A1–C2) с расшифровкой и объяснением, зачем это нужно.
2. Поднять кворум в голосовании с 3 до 4 человек.
3. Слать вопросы недели посложнее/полегче в зависимости от уровня.
4. Слать участникам в личку полезную лексику по теме занятия перед занятием, на основе их уровня.
5. Дать возможность менять свой уровень позже командой `/level`.

## Ключевой факт (что уже есть)

- `profiles.english_level` **уже существует** (`String(50)`, индекс `idx_profiles_level`) — миграции на колонку не нужно.
- Движок карточек **уже читает** `english_level` для сложности группы (`_group_difficulty`, `CEFR_ORDER` в `cards/service.py`). Для сложности карточки занятия ничего нового писать не надо — достаточно заполнить поле.
- Значит мы не строим новую систему уровней, а **наполняем существующее поле** и прокидываем его в места, где его сейчас нет.

## Вне scope (YAGNI)

- Не трогаем провайдера вопросов недели (OpenRouter) — только добавляем параметр уровня в промпт.
- Не делаем перевод лексики на русский (по умолчанию примеры на английском; перевод — тривиальная доработка позже, если понадобится).
- Общий вопрос недели из банка оставляем общим для всех (намеренный «вопрос для всех»).

## Шкала уровней (CEFR)

| Код | Название | Описание для онбординга |
|-----|----------|--------------------------|
| A1 | Beginner | I know a few words and simple phrases. |
| A2 | Elementary | I can talk about everyday things in simple sentences. |
| B1 | Intermediate | I can hold a conversation on familiar topics. |
| B2 | Upper-Intermediate | I speak fairly fluently, with some mistakes. |
| C1 | Advanced | I speak fluently on complex topics. |
| C2 | Proficient | I speak nearly like a native speaker. |

Эти описания попадают в пояснительный блок карточки онбординга.

## Изменения данных

- Миграция `0012` (down_revision `0011`):
  - `UPDATE config SET value = '4' WHERE key = 'quorum_threshold'` (значение в БД перекрывает дефолт кода; колонка JSONB, читается через `int(...)`, так что и строка `"4"`, и число `4` валидны — в реализации совпадаем с уже хранимым форматом).
- Новых колонок/таблиц нет.

## Компоненты

### 1. Карточка уровня (общая, переиспользуемая)

Переиспользуемый кусок — **CEFR-опции** (коды A1–C2 + описания). Стендалон-карточка `build_level_card(current_level)` + обработчик сабмита `set_level` используются в **двух** сценариях:

- **backfill** — отдельная DM-карточка для тех, у кого `english_level IS NULL`;
- **`/level`** — DM-карточка по запросу, с текстом «Current level: X», если уровень уже есть.

Онбординг **q8** — это обычный `selectionInput` внутри анкеты, который субмитится вместе с остальными вопросами (существующий путь CARD_CLICKED онбординга), а не через `set_level`.

Структура карточки уровня (DM-вариант):

```
header: "Your English level"
textParagraph: "We'll use this to send you questions and vocabulary that fit you."
textParagraph (только если есть): "Current level: B1"
selectionInput (radio, name=q_level): A1..C2 (text = "A1 — Beginner", value = "A1")
button "Save" -> action.function "set_level"
```

Обработчик `set_level` читает `formInputs.q_level`, валидирует значение против `CEFR_ORDER`, пишет `profile.english_level`, возвращает короткое подтверждение. Идемпотентно (повторный сабмит просто перезаписывает).

### 2. Онбординг q8

- `app/services/onboarding_answers.py`:
  - `QUESTIONS` + `q8: "8. What's your English level?"`;
  - `OTHER_FIELDS` не меняем (у уровня нет «Свой вариант»);
  - `update_profile_from_onboarding` пишет `profile.english_level = q8.choice` (первый выбранный вариант).
- `app/api/google_chat.py` (карточка онбординга, ~строка 1596): добавить `selectionInput` q8 + пояснительный блок (зачем это нужно + расшифровка уровней).

### 3. Кворум 3 → 4

- `app/services/weekly_poll.py:330`: дефолт `get_or_create_config(db, "quorum_threshold", 3)` → `4`.
- Миграция `0012` обновляет засиженное значение.
- Обновить `tests/e2e/test_jobs.py` (`test_finalize_creates_meeting_on_quorum`, `test_finalize_cancels_without_quorum`) — голосуют 4-мя голосами.

### 4. Вопросы недели по уровню

- `app/services/llm_questions.py`: `generate_personal_question(..., level)` — промпт по уровню:
  - A1/A2: simple words, short sentences, present tense, everyday topics;
  - B1/B2: opinions, «why», light hypotheticals;
  - C1/C2: abstract, nuance, idioms, debate-style.
- `app/services/weekly_questions.py`: `questions_for_profile` принимает `level`, передаёт в `generate_personal_question`. Общий банковский вопрос — без изменений.
- **Self-heal backfill**: в `send_weekly_questions`, если у активного профиля `english_level IS NULL` → вместо вопроса недели шлём `build_level_card(None)`. Плюс разовый скрипт `scripts/backfill_levels.py` для немедленного переспроса.

### 5. Лексика в личку (по теме, по уровню, вместе с карточкой)

- В `app/cards/service.py::send_card` после генерации карточки занятия:
  1. участники = `_attendee_profiles(db, meeting)`;
  2. группируем по `english_level` (NULL → A2);
  3. для каждого уровня — один LLM-запрос (Azati `llm_games_model`) на 5–7 фраз по теме + пример на английском, под уровень;
  4. каждому участнику — DM-карточка «📚 Vocabulary for today: <topic>» с фразами его уровня.
- Новый `app/services/vocab.py`: генерация (LLM + fallback), рендер DM-карточки, отправка.
- **Fallback**: LLM упал → `vocab_box` уже сгенерированной карточки (уровень группы) или статический банк по уровню.
- **Идемпотентность**: guard в начале `send_card` — если `Card` с этим `meeting_id` уже есть, выходим (логируем). Чинит и существующий double-send карточки при рестарте (`restore_cards_on_startup`).

### 6. Команда `/level`

- `app/api/google_chat.py`: матчер `_is_level_command` (принимает `/level`, `!level`, `level`, «уровень»).
- В DM → `build_level_card(profile.english_level)`; в группе → текст «DM me to change your level 🙌» (как у онбординга).
- Роутинг в оба диспетчера (add-on и classic), как у `top`/`points`.
- Нюанс: Google Chat перехватывает `/...` как нативную слэш-команду, в живой переписке реальный триггер — `!level`; `/level` оставляем для тестов, шлющих запросы в обход Google (см. `_is_slash_command`).

## Обработка ошибок

- LLM (вопросы/лексика): любой сбой → тихий fallback на шаблон/банк, лог `exc_info` (уже принято в проекте).
- Профиль без `workspace_user_id` или неактивный → пропускаем DM, не падаем.
- Некорректный `q_level` в сабмите → игнорируем (не пишем), возвращаем «Something went wrong, try again».

## Тесты

- Unit:
  - парсинг q8 → `english_level`;
  - `generate_personal_question` с level (mock `requests`), проверка промпта;
  - `finalize_day` граница кворума: 3 голоса → `None`, 4 → встреча;
  - генерация/группировка лексики по уровням;
  - `build_level_card` + обработчик `set_level` (валидный/невалидный уровень).
- E2E:
  - сабмит карточки уровня;
  - `/level` в DM → карточка;
  - отправка DM лексики.
- Обновить 2 кворум-теста (3→4).

## Файлы

| Файл | Действие |
|------|----------|
| `app/services/onboarding_answers.py` | q8 + `english_level` |
| `app/api/google_chat.py` | q8 в карточке онбординга; `_is_level_command`, `/level`-роутинг, `build_level_card`, `set_level` |
| `app/services/weekly_poll.py` | дефолт кворума 4 |
| `app/services/llm_questions.py` | параметр `level` |
| `app/services/weekly_questions.py` | прокидывание level + self-heal |
| `app/cards/service.py` | guard идемпотентности + вызов лексики |
| `app/services/vocab.py` | новый: генерация + DM-карточка + fallback |
| `alembic/versions/0012_quorum_level.py` | миграция кворума |
| `scripts/backfill_levels.py` | новый: разовый переспрос |
| тесты | unit + e2e |

## Порядок реализации

1. Миграция 0012 + `weekly_poll.py` (кворум 4) + кворум-тесты.
2. Онбординг q8 (карточка + парсинг + сохранение).
3. Карточка уровня + `set_level` (общий компонент).
4. `/level` команда.
5. Вопросы недели по уровню + self-heal + скрипт backfill.
6. Лексика в личку (vocab.py + hook в `send_card` + guard).
7. Тесты + прогон.

## Подводные камни (сводка)

1. Кворум засижен в БД и перекрывает код → нужна миграция `0012`.
2. `english_level = NULL` у существующих → self-heal + скрипт `backfill_levels.py`.
3. Double-send карточки/лексики при рестарте → guard по `Card.meeting_id`.
4. Лексика ≠ карточка: карточка генерится под минимум уровня группы, личка — под каждый уровень отдельно. Два разных набора контента.
5. `/...` перехватывается Google Chat → рабочий триггер `!level`, `/level` для тестов.
