# fix.md — план исправлений по итогам code-review (2026-08-26)

Ничего не исправлено, это только план. Порядок = приоритет.
Формат: **Что / Где / Почему / Как**.

---

## P0 — Критические баги (ломают фичи прямо сейчас)

### 1. NameError: `timedelta` не импортирован

- **Где:** `app/services/invites.py:87`
- **Что:** используется `timedelta(minutes=duration)`, но в импортах файла (строка 32) только `from datetime import datetime, timezone`.
- **Почему:** `handle_time_finalized()` падает **всегда**, когда передан `scheduled_start` — а это основной путь из джобы кворума (`scheduler.py:48`). Встреча уже закоммичена в `finalize_day`, но джобы напоминания и check-in окна не создаются, карточка занятия не планируется. Исключение глушится в scheduler-джобе логом — тихо и незаметно.
- **Как:** добавить `timedelta` в импорт на строке 32:
  ```python
  from datetime import datetime, timedelta, timezone
  ```
- **Проверка:** юнит-тест на `handle_time_finalized(scheduled_start=...)` с замоканным шедулером — должен дойти до `add_job` без исключений.

### 2. NameError: `game_id` не определён в `_apply_guess`

- **Где:** `app/services/hangman.py:313`
- **Что:** в ветке «повторная буква» вызывается `build_hangman_card(state, game_id)`, но у `_apply_guess` (строки 285–292) нет параметра `game_id`.
- **Почему:** любой повторный ввод уже названной буквы падает с NameError → юзер видит «Error processing that action 🤕» вместо карточки «You already tried that letter 😉». Фича повторной буквы сломана целиком.
- **Как:** заменить `game_id` на `session.id` (параметр функции, объект `GameSession`).
- **Проверка:** юнит-тест: два раза `guess()` с одной буквой → второй ответ содержит «already tried».

### 3. Alembic: две миграции с `revision = "0005"` — история форкнута

- **Где:** `alembic/versions/0005_inactivity_reminders.py:14` и `alembic/versions/0005_onboarding_invite_sent.py:7` (обе `down_revision = "0004"`); `alembic/versions/0006_game_tables.py:22` ссылается на голое `"0005"`.
- **Почему:** `alembic history` падает (`Revision 0005 is present more than once`), свежий деплой через `alembic upgrade head` невозможен, autogenerate мёртв. Подвох: простое переименование одного файла оставит вторую пачку колонок (`last_activity_at`/`reminder_count`/`last_reminder_at` **или** `onboarding_invite_sent`) неприменённой на чистой БД.
- **Как:** честный merge-ридж:
  1. Переименовать одну миграцию: например `0005_onboarding_invite_sent.py` → `revision = "0005b"`, `down_revision = "0005"` (сериализовать ветки).
  2. `0006_game_tables.py`: `down_revision = "0005b"`.
  3. Текущая БД (где в `alembic_version` записано `0005`): после ребейза выполнить `alembic stamp 0005b` (миграция 0005b на живой БД уже применена физически, менять ничего не надо).
  4. Прогнать `alembic history` — должен показать линейную цепочку.
- **Проверка:** на чистой тестовой БД `alembic upgrade head` проходит, обе пачки колонок существуют.

### 4. Таймзонный сдвиг встреч на 3 часа

- **Где:** `app/services/weekly_poll.py:165-168` (`slot_datetime` хранит «15:00» как 15:00 UTC) и `weekly_poll.py:370-373` (`finalize_day` собирает встречу в UTC).
- **Почему:** при `app_timezone = "Europe/Minsk"` встреча, за которую голосовали как за «15:00», реально создаётся в 15:00 UTC = **18:00 по Минску**. Пользователю пишут «15:00», а окно чек-ина, напоминания и баллы за посещаемость живут по 18:00. Систематический тихий баг.
- **Как:** при создании `MeetingInstance` в `finalize_day` интерпретировать слот-время в таймзоне приложения:
  ```python
  tz = ZoneInfo(get_settings().app_timezone)
  local_start = datetime.combine(meeting_date, slot_start.time(), tzinfo=tz)
  start = local_start.astimezone(timezone.utc)  # в БД храним UTC как раньше
  ```
  `slot_datetime` (дата-переносчик 2000-01-01 UTC) можно не трогать — он нужен только как носитель time(); меняется точка конвертации. Заодно поправить и `_send_reminder` (см. п. 21).
- **Проверка:** юнит-тест: слот «15:00», app_timezone=Europe/Minsk → `scheduled_start` == 12:00 UTC.

---

## P1 — Архитектурные проблемы (системные)

### 5. Блокирующие HTTP-вызовы в async event loop

- **Где:** `chat_sender.py` — синхронный `requests` (timeout 15с). Вызывается из async **без** `asyncio.to_thread`:
  - `app/services/weekly_questions.py:145-151, 160-166` (рассылка всем — loop заморожен на минуты)
  - `app/services/weekly_poll.py:317-319` (`send_space_message` рядом с правильно обёрнутым `patch_message`)
  - `app/services/alias_game.py:435-446, 449-465, 632-634, 767, 875, 934, 994`
  - `app/services/snake_oil.py:270-280, 319-333, 566, 570, 651, 699`
  - `app/services/games/spy.py:141-143`, `app/services/games/guesspionage.py:150-156, 173-176`
  - `app/services/invites.py:74, 133`; `app/services/inactivity.py:98`; `app/services/broadcast.py:25, 38`; `app/services/space_onboarding.py:40, 71`
  - `app/scheduler.py:83-87, 117-120`; `app/api/google_chat.py:2137, 2151, 2179`
- **Почему:** пока идёт рассылка, все вебхуки Google Chat висят/таймаутятся → Google ретраит → дубли обработки событий. Паттерн `asyncio.to_thread` в проекте уже используют правильно (`party_games.py:847-849`, `vocab.py:139`, `lesson_assistant.py:172-191`) — здесь просто пропущен.
- **Как:**
  1. Обернуть все перечисленные вызовы: `await asyncio.to_thread(send_message, ...)`.
  2. **Кэш кредов** в `chat_sender.py:22-29`: `_bot_credentials()` сейчас на каждый вызов читает ключ с диска и делает сетевой `creds.refresh()`. Кэшировать credentials-объект в модуле (google-auth сам обновляет токен по мере истечения).
  3. Ретраи с бэкоффом на 429/5xx в `send_message`/`send_text` (`chat_sender.py:55-65`).
- **Проверка:** `pytest` + ручной прогон рассылки на 5+ юзерах: вебхук `/health` отвечает во время рассылки.

### 6. `find_user_dm_space` игнорирует сохранённый DM и не пагинируется

- **Где:** `chat_sender.py:103-151`; используется в `messaging.py:34` и `inactivity.py:98`.
- **Почему:** (а) перебор ВСЕХ спейсов бота × `members.list` по каждому = O(spaces × members) HTTP-запросов на одного юзера, хотя у профиля уже есть `chat_space_id`; (б) `spaces.list`/`members.list` отдают до 1000 записей + `nextPageToken`, который игнорируется — при росте люди молча теряются.
- **Как:**
  1. В `messaging.send_message` и `remind_inactive` сначала пробовать `profile.chat_space_id`, fallback на `find_user_dm_space` только если пусто.
  2. Добавить цикл по `nextPageToken` в `list_bot_spaces` и `list_space_members`.
- **Проверка:** юнит-тест пагинации с моком из двух страниц.

### 7. GameManager (Spy / Guesspionage) — in-memory состояние

- **Где:** `app/services/games/session.py:17-49`; вызовы в `app/api/google_chat.py:48-51, 75, 99-106`.
- **Почему:** при `uvicorn --workers N` клики попадают на разные воркеры → `GameManager.get()` возвращает None → клики молча теряются. Рестарт процесса теряет партию без подсчёта. Плюс нет таймаутов: незаходящий называющий блокирует space навсегда («A game is already running»). Все остальные игры уже на `game_sessions` (JSONB) — эти две единственные исключения.
- **Как:** перевести на таблицу `game_sessions` по образцу Wheel (`wheel_game.py`): state в JSONB, `spy`/`guesspionage` добавить в CheckConstraint `game_type`. Таймауты — через `phase_deadline` + расширение `close_stale_games` (`party_games.py:1394-1401`).
- **Проверка:** e2e-тест: рестарт приложения посреди партии не теряет игроков/голоса.

### 8. Гонка двойного старта во всех 8 соло-играх → «мёртвый» space

- **Где:** паттерн `if await get_active_game(...) is not None: return` → генерация → `_start_session` без защиты:
  `hangman.py:221`, `millionaire.py:198`, `wordle.py:227`, `two_truths.py:113` (там окно гонки до 60с из-за LLM!), `word_puzzle.py:120`, `translation.py:162`, `words_of_wonders.py:203`, `riddles.py:167`.
- **Почему:** двойной клик по кнопке меню → две сессии `status='active'` в одном space → `get_active_game` (`party_games.py:400-408`, `scalar_one_or_none`) кидает `MultipleResultsFound` → **каждый** следующий старт в space падает, пока сессию не закроют вручную.
- **Как:** partial unique index в миграции:
  ```sql
  CREATE UNIQUE INDEX uq_game_sessions_active_space
  ON game_sessions (space_name) WHERE status = 'active';
  ```
  В `_start_session` ловить `IntegrityError` → возвращать «игра уже запущена».
- **Проверка:** тест: две параллельные вставки активной сессии в один space → вторая падает с IntegrityError.

### 9. Гонки двойного клика: двойные очки и зомби-раунды (DB-игры)

- **Где:** `alias_game.py:837-858 (last_word), 861-877 (_end_round), 904-914 (confirm_round), 917-948 (_finalize_round)`; `snake_oil.py:575-601 (vote), 604-626 (solo_ready), 629-663 (_finalize_vote)`; финалы соло-игр: `hangman.py:244-266`, `wordle.py:286-299`, `millionaire.py:245-257`.
- **Почему:** паттерн `if status != "..."` → действия → commit. Два параллельных запроса в READ COMMITTED оба проходят проверку → двойное применение: +2 вместо +1 очка, `_start_round` создаётся дважды (две карточки), `points_adjustment` применяется дважды. Google к тому же ретраит таймаутнутые вебхуки. `_change_score` в Alias защищает от *потери* апдейта, но не от *дублирования применения*.
- **Как:** compare-and-swap вместо check-then-act:
  ```python
  res = await db.execute(
      update(GameRound)
      .where(GameRound.id == round_id, GameRound.status == "active")
      .values(status="confirming")
  )
  if res.rowcount == 0:
      return {"silent": True}  # кто-то уже обработал
  ```
  Для финалов игр: `UPDATE game_sessions SET status='finished' WHERE id=:id AND status='active'` — очки начислять только при `rowcount == 1`.
- **Проверка:** тест с `asyncio.gather` двух одинаковых кликов → очки применены один раз.

### 10. Leaderboard: идемпотентность не работает при `meeting_instance_id=None`

- **Где:** `app/services/leaderboard.py:27-46` (UNIQUE-колонка с NULL) + вызовы `callready.py:544`, `leveled.py:297`, `games/scores.py:19`.
- **Почему:** в Postgres NULL ≠ NULL в уникальном индексе → `on_conflict_do_nothing` не срабатывает → ретрай после сбоя = двойные баллы. Mirror-баг: `party_games.py:1366` — вторая Quiplash-партия на той же встрече молча **не начислит** очки (docstring обещает «суммарные очки», а `on_conflict_do_nothing` даёт «первая партия выигрывает»).
- **Как:**
  1. Частичный индекс для NULL-событий: `CREATE UNIQUE INDEX ... ON leaderboard_ledger (profile_id, event_type) WHERE meeting_instance_id IS NULL;` и в `award_points` для этого случая использовать `on_conflict_do_nothing(index_elements=[...], index_where=...)` либо пред-SELECT.
  2. Для event_type='game' решить осознанно: либо `on_conflict_do_update(points=points+excluded.points)` (сумма, как в docstring), либо починить docstring.
  3. Два разных `award_points` (`games/scores.py` и `leaderboard.py`) с разным поведением по commit — объединить в один.

### 11. `award_attendance` — мёртвый код, баллы за посещение не начисляются

- **Где:** `app/services/leaderboard.py:49-68`; вызова нет нигде.
- **Почему:** `submit_checkin` (`checkin.py:74-108`) пишет attendance, но фича «points for attendance» (REQ-9.7, config `points_attendance`) молча отсутствует — игроки чекинятся, рейтинга не получают.
- **Как:** вызвать `award_attendance` из `submit_checkin` при `result["within"] == True` (идемпотентность уже есть через UNIQUE + meeting_instance_id — см. п. 10 про NULL не актуален, тут id есть).

### 12. Потеря баллов при сбое в leveled

- **Где:** `app/services/leveled.py:294-301 (_award), 329-337, 381-391`.
- **Почему:** паттерн «сначала commit состояния (тема пройдена), потом `_award`», который глотает **все** исключения. Транзиентная ошибка БД → тема помечена пройденной, баллы не начислены, повторно начислить нельзя. Идемпотентность «по состоянию» не спасает.
- **Как:** начислять баллы в **той же транзакции**, до commit'а состояния: `await award_points(...)` внутри транзакции, и только потом один общий commit. `_award` перестать глотать исключения — пусть роллбакит всю операцию (юзер сможет кликнуть повторно).

### 13. Alias: Finish не гасит раунды, таймеры умирают при рестарте

- **Где:** `alias_game.py:904-914 (finish_game), 917-948 (_finalize_round)`; таймеры `alias_game.py:468-483` + `scheduler.py:155` (MemoryJobStore).
- **Почему:** (а) `finish_game` ставит `game.status="finished"`, но `confirm_round`/`guess_word`/`skip_word` проверяют только `round.status` → `_start_round` создаёт раунды в завершённой игре; (б) рестарт убивает таймеры → раунд навечно `active`, `close_stale_games` про Alias не знает.
- **Как:**
  1. В `finish_game` помечать активные раунды `status='confirmed', ended_at=now()`; в `confirm_round`/`guess_word`/`skip_word` добавить проверку `game.status == "active"`.
  2. В `close_stale_games` добавить ветку Alias: раунды со `started_at` старше `round_seconds + buffer` → закрывать как `time_up` (состояние-то в БД).
- **Соседнее:** Wheel вообще без `phase_deadline` (`wheel_game.py:230-243`) — добавить дедлайн фазы и ветку в `close_stale_games`.

### 14. Spy/Guesspionage: голоса чужаков, протухшие карточки → 500

- **Где:** `games/spy.py:147-159`, `games/guesspionage.py:160-194`; обработчики в `google_chat.py:121-162` без try/except.
- **Почему:** (а) нет проверки `user_id in session.players` — любой участник space влияет на подсчёт; (б) клик по старой кнопке из истории чата при пустом `state` → `state["votes"]` KeyError → FastAPI 500; (в) `submit_guess` без идемпотентности — повторный клик постит вторую карточку голосования и перезаписывает число.
- **Как:**
  1. В начале `vote()`/`submit_guess()`: `if user_id not in session.players: return None` и `state.get("votes") is None: return None`.
  2. Round-токен в параметрах кнопок (как в `party_games.py:982-988`).
  3. Обернуть обработчики в вебхуке try/except по аналогии с остальными.
- **Соседнее:** Quiplash `submit_quiplash_vote` (`party_games.py:1016-1043`) — голоса не-ответивших считаются в порог закрытия раунда: считать только голоса тех, кто есть в `answers`.

### 15. Docker «production» не рабочий

- **Где:** `docker-compose.yml:27-33`, `Dockerfile:12, 15`.
- **Почему:** (а) compose не пробрасывает `CHAT_APP_AUDIENCE`, `SKIP_JWT_VALIDATION`, `GOOGLE_SA_KEY_FILE`, `LLM_API_KEY`, `APP_TIMEZONE` → пустой audience завалит любой реальный JWT (google-auth проверяет `if audience is not None` — пустая строка валидна), LLM тихо деградирует до банка; (б) `sa-key.json` не COPY и не монтируется → `from_service_account_file` упадёт на первой рассылке; (в) `alembic/` и `alembic.ini` не в образе, CMD без `alembic upgrade head`, схема сама не создаётся → чистая БД = падение на первом SELECT; (г) у app нет healthcheck, в slim-образе нет curl/wget.
- **Как:**
  1. В compose: `env_file: .env` + явные переменные; секрет и алумбик — через volume (`./sa-key.json:/app/sa-key.json:ro`, `./alembic:/app/alembic`).
  2. CMD: `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000` (или entrypoint-скрипт).
  3. Healthcheck: поставить в образ `curl` либо использовать `python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')"`.
  4. Убедиться, что в образе есть tzdata (иначе `ZoneInfo("Europe/Minsk")` упадёт), добавить `--proxy-headers` uvicorn.

### 16. `alembic/env.py` не импортирует карточные модели

- **Где:** `alembic/env.py:12` — только `from app import models`.
- **Почему:** таблицы `card_types`/`cards`/`content_bank` не попадают в `Base.metadata` → первый autogenerate после починки п.3 сгенерирует DROP трёх таблиц. В `scripts/wipe_db.py:13-14` импортируют правильно — проблема известна, но починена только в скрипте.
- **Как:** `from app import models, cards.models  # noqa: F401` — все модели в metadata.
- **Проверка:** `alembic revision --autogenerate` на актуальной БД → пустая миграция.

---

## P2 — Важное, но не горит

### 17. Гонка создания профилей — IntegrityError не обрабатывается нигде

- **Где:** `app/services/onboarding.py:31-57` (`get_or_create_profile`); grep: `IntegrityError` не встречается в проекте ни разу.
- **Почему:** SELECT → INSERT без обработки: поллинг каждые 10 мин параллелен вебхукам, Google ретраит события → два одновременных создания одного юзера → unique violation → 500.
- **Как:** ловить `IntegrityError` на commit → rollback → повторный SELECT. Или upsert `INSERT ... ON CONFLICT (workspace_user_id) DO UPDATE`.

### 18. Онбординг: флаг «приглашён» ставится до отправки

- **Где:** `app/services/space_onboarding.py:88-89` (commit `onboarding_invite_sent=True`), отправка потом в `scheduler.py:115-120`; у джобы `onboarding-poll` нет `max_instances=1`.
- **Почему:** сбой отправки (который `messaging.py` глотает!) → человек помечен приглашённым, ничего не получил и не получит. Медленный прогон > 10 мин → наложение джоб → двойные приглашения.
- **Как:** ставить флаг после успешной отправки (или отправлять до commit, по образцу `snake_oil.py:425-434`); добавить `max_instances=1` джобе.

### 19. Inactivity: счётчик растёт без фактической отправки

- **Где:** `app/services/inactivity.py:98-104` + `app/messaging.py:33-41`.
- **Почему:** `messaging.send_message` глотает все исключения → `remind_inactive` инкрементирует `reminder_count` независимо от результата → юзер без DM трижды «получает» невидимые напоминания и выпадает из программы. Плюс send до commit → краш между ними = завтра повторная отправка тем же людям.
- **Как:** `send_message` должен возвращать bool (отправлено/нет), инкремент только при True; порядок: commit после успешной отправки.

### 20. `handle_time_finalized`: напоминание в прошлом теряется + UTC-время в тексте

- **Где:** `app/services/invites.py:79-96` (нет `if remind > now` — сравни с `reminders.py:54`), `invites.py:127-128` (`strftime` на UTC-объекте), `invites.py:133` («in an hour!» захардкожен при конфигурируемом `lead_hours`).
- **Почему:** встреча финализирована позже, чем за `lead_hours` до начала → `add_job(run_date=<прошлое>)` не исполнится никогда; юзеру показывается 15:00 вместо 18:00 (та же таймзона, что п.4).
- **Как:** проверять `run_date > now` перед add_job (иначе лог warning); в `_send_reminder` конвертировать `scheduled_start.astimezone(ZoneInfo(app_timezone))` перед strftime; текст с фактическим `lead_hours`.

### 21. `weekly_poll` — логика и мёртвый код

- **Где:**
  - `weekly_poll.py:229-234` — `day < today_dow` всегда ловит `day=-1` раньше проверки `day < 0` (мёртвая ветка): невалидный день репортится как «past_day»;
  - docstring (строки 3-4) обещает «ОДИН слот на участника», код (строки 251-257) хранит голоса за разные дни → один юзер бьёт квоту двух дней;
  - `weekly_poll.py:149-156` — `get_or_create_config` коммитит в середине чужой транзакции (может увезти чужие незакоммиченные изменения);
  - `weekly_poll.py:440-448` — `restore_day` стирает отказ без восстановления, если слот не нашёлся;
  - ничто не переводит `DailyPoll.status` в 'finalized'/'cancelled' (жизненный цикл из CheckConstraint не существует);
  - `weekly_poll.py:252-270` — два конкурентных сабмита за разные слоты одного дня = 2 голоса (UNIQUE не спасает).
- **Как:** поменять порядок проверок местами; осознанно решить «один день или много» и свести docstring/карточку/код к одному ответу; `get_or_create_config` → flush вместо commit; в `restore_day` мутировать `declined` только после подтверждения, что слот найден; при `ensure_weekly_poll` помечать прошлые опросы `status='finalized'`.

### 22. LLM-клиенты: копипаст ×3 и слабый парсинг

- **Где:** `llm_questions.py:17-18, 43-72` ≈ `cards/generator/llm.py:37-48` ≈ `games_llm.py`; `games_llm.py:319` (`bool(data.get("correct"))`); `games_llm.py:99-108` (нет ретраев).
- **Почему:** три копии одного клиента; `bool("false") == True` — строка от LLM зачтёт неверный ответ верным; один транзиентный 429 режет синонимы в translation (judge-fallback строгий).
- **Как:** общий модуль `app/services/llm_client.py` (call + parse + retry с бэкоффом на 429/5xx); строгая проверка: `data.get("correct") is True`. Заодно `vocab.py:9` перестанет импортировать приватные `_call_llm, _parse_json`.

### 23. LLM-вызовы 30-60с внутри вебхука

- **Где:** `translation.check:193-199`, `riddles.check:196-198`, `words_of_wonders.check:250`, `two_truths.start:116` (timeout 60с, `games_llm.py:265`).
- **Почему:** Google не ждёт вечно → юзер жмёт повторно → параллельная обработка + ретраи платформы → рассинхрон состояния.
- **Как:** кэп на повторную отправку (игнорировать клик, если ход уже в обработке — флаг в state) + снизить таймаут до ~15с; в перспективе быстрый ack + фоновая обработка.

### 24. Мелкие баги игр

- **`wordle.py:273`** — config `wordle_word_length` сломает игру при изменении (банк только 5-буквенный): убрать ключ или валидировать `== 5`.
- **`millionaire.py:63, 202`** — config `millionaire_total_questions` читается, но игнорируется (мёртвая настройка); **`millionaire.py:340-347`** — quit теряет `best_level` (фиксировать `level - 1` как при неверном ответе).
- **`hangman.py:303-308`** — несимметричная дедупликация: повтор буквы бесплатен, повтор неверного слова снова минус попытка.
- **`word_puzzle.py:124`** — `random.sample` может вернуть исходный порядок (пазл сразу собран): перетасовывать до отличия.
- **`words_of_wonders.py:75`** — `state["min_len"]` пишется, но проверка использует константу `MIN_LEN` (строка 231): мёртвое поле.
- **`wordle.py:331-338`, `millionaire.py:340-347`** — quit/reveal/finish не проверяют game_type/status: quit по старой карточке портит статистику (перезапишет 'finished' → 'cancelled').
- **`two_truths.py:81`** — `lie_text` вычисляется и не используется (мёртвый код).
- **`guesspionage.py:15-21, 138-139`** — банк из 5 вопросов мёртв (всегда `GUESS_QUESTIONS[0]`, называющий всегда `players[0]`).
- **`spy.py:31-36`** — `tally_votes` создаёт ключи для целей вне списка игроков → фильтровать по `players`.
- **`party_games.py:921, 1238`** — «my secret» три раза, русского «мой секрет» нет.
- **`party_games.py:894-916`** — `handle_dm_message` тянет ВСЕ активные сессии всех space'ов на каждое сообщение в личку.
- **`riddles.py:233`** — docstring «сдаться → перейти дальше» vs код оставляет ту же загадку.
- **`hangman.py:421`, `wordle.py:384`, `millionaire.py:392`** — подписи лидербордов захардкожены, врут при override конфига.
- **`google_chat.py:433-437` + `alias_game.py:775-799`** — `alias_guess`/`alias_skip` не проверяют, кто кликнул.

### 25. Checkin: двойной клик → IntegrityError без фидбэка

- **Где:** `app/services/checkin.py:86-103`.
- **Почему:** два запроса не находят attendance → двойной INSERT → IntegrityError ловится широким except → юзер не получает фидбэк.
- **Как:** upsert (`ON CONFLICT (profile_id, meeting_instance_id) DO NOTHING`) + заодно подключить п.11.

### 26. Тесты: дыры в покрытии

- **Где:** `tests/`.
- **Почему:** JWT/webhook security не покрыты вообще (единственная точка аутентификации!): нет тестов «без Bearer → 401», «кривой токен → 401», «skip_jwt_validation=true пропускает». Нет ни одного теста на 10 модулей: `alias_game`, `snake_oil`, `party_games`, `hangman`, `millionaire`, `wordle`, `two_truths`, `word_puzzle`, `translation`, `words_of_wonders`, `riddles`. `tests/e2e/test_webhook_message.py:19` ждёт «Привет», бот отвечает «Hi» — тест устарел (или бот изменился, надо проверить).
- **Как:** в порядке ценности: (1) смоук-тесты 401/200 вебхука с моком `id_token.verify_oauth2_token`; (2) юниты топ-3 игр из списка; (3) актуализировать test_webhook_message.

### 27. `google_chat.py` — god-файл на 2815 строк

- **Где:** весь файл; списки методов дублируются на строках 2336-2395 и 2738-2810.
- **Почему:** каждый новый экшен добавляется в 2-3 места (add-on ветка + classic CARD_CLICKED + меню) — главный источник регрессий; восьмёрка почти идентичных `_handle_*_action` (~320 строк).
- **Как (поэтапно, без большого банга):**
  1. Сначала таблица диспетчеризации `METHODS: dict[str, Handler]` — обе ветки (add-on и classic) сводятся к одному lookup.
  2. Общий слой для соло-игр `app/services/solo_games/common.py`: `_action_url`/`_btn`/`active_session`/`get_or_create_score`/`new_game`/лидерборд-билдер — убирает ~530 строк вербатим-копипаста (~22% кода игр) и заодно размноженные ошибки.

### 28. Прочее (мелочи)

- `app/messaging.py:9` — docstring ссылается на несуществующие `app/activities.py` и `app/scheduling.py`.
- `app/scheduler.py:1-5` — docstring обещает «финализацию в 14:05», код ставит квorum-джобу в `check_h:00`.
- `app/services/onboarding.py:14` — константа «7 questions», вопросов в анкете 8.
- `onboarding_answers.py:173-175` — двойной commit (`mark_onboarded` + внешний): падение второго = профиль onboarded, ответы потеряны.
- `invites.py:44` — self-import `from app.services.invites import _theme_from_activity` внутри самого invites.py.
- `reminders.py:42` — `int(cfg.value or 1)` без защиты от мусора в конфиге (есть готовый `_config_int` в inactivity.py:54-62).
- `broadcast.py:50` — `select(Profile)` без фильтров: захватывает неактивных и placeholder-профили.
- `leaderboard.py:79-84` — фильтр только `@test.local`: placeholder-профили (`@placeholder.local`) попадают в лидерборд, `user_name = None` → «None» на карточке.
- `lesson_assistant.py:206` — контекст и вопрос склеиваются в один user-turn (промпт-инъекция ограничена, но лучше разделять по ролям); ответ до 30-40с в вебхуке без идемпотентности.
- `cards/service.py:142-144` — `CEFR_ORDER.get(..., "A2")`: дефолт-строка vs int-ключи → латентный TypeError при невалидном `cefr_min`.
- `cards/seed.py` — не сеет `game_day` и `two_truths` (game_day всегда деградирует к случайной игре).
- `cards/service.py:222-230` — карточка коммитится до отправки: сбой отправки = сообщение потеряно навсегда, ретрай невозможен.
- `cards/validator.py:5-11` — только английские стоп-слова (контент русскоязычный).
- `activity_matcher.py:39` — `tag in lowered` матчит подстроки: «word» найдётся в «password».
- `weekly_questions.py:92` — `week_start` на момент сабмита: ответ в понедельник на вопрос воскресенья уедет в новую неделю.
- `weekly_questions.py:131-158` — N+1 и неограниченный avoid-список в промпте LLM (растёт со временем).
- `models.py:754` — `MutableDict.as_mutable(JSONB)` не трекает вложенные структуры (сейчас везде корректно, паттерн хрупкий).
- `requirements.txt:10` — `pytest==8.2.2`, в venv стоит 9.1.1.
- Dockerfile: нет multi-stage (gcc/libpq-dev в финальном образе), нет `USER` (root).
- Zombie-сессии: `party_games.py:499-511`, `wheel_game.py:244-258` — commit до отправки карточки, сбой = невидимая блокировка space (нет `scoreboard_message_name`, нет дедлайна). Обработчик `_handle_member_added` (`google_chat.py:2165-2186`) пишет в БД до отправки — та же схема.

---

## Порядок работы (рекомендация)

| Этап | Пункты | Оценка |
|------|--------|--------|
| 1. Однострочники | 1, 2 | минуты |
| 2. Alembic + env.py | 3, 16 | ~1 час (аккуратно с stamp на живой БД) |
| 3. Таймзона встреч | 4, 20 | ~1 час + тесты |
| 4. Anti-race пакет | 8, 9, 17 (индекс + CAS + IntegrityError) | ~полдня |
| 5. Async-гигиена | 5, 6 (to_thread + кэш кредов + пагинация) | ~полдня |
| 6. Баллы | 10, 11, 12 (leaderboard-идемпотентность + attendance + leveled) | ~полдня |
| 7. Логика игр | 13, 14, 24 | по мере сил |
| 8. Инфраструктура | 15, 26 | ~день |
| 9. Рефакторинг | 22, 27 | отдельно, после стабилизации |
| 10. Мелочи | 21, 18, 19, 25, 28 | в порядке раздражения |

Каждый этап закрывать тестом (колонка «Проверка» у пунктов 1-4, 8-9, 16) — иначе гонки и таймзоны вернутся.
