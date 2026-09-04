# Ручная проверка English Meet Bot

Чеклист для прогона бота в реальном Google Chat. Идёт по порядку: каждый сценарий
содержит **действия → что должно случиться → как проверить в БД**.

Автотесты (`pytest -m e2e` / `pytest -m live`) уже покрывают логику без UI. Здесь —
то, что видно только в живом чате: карточки, кнопки, проактивные DM.

---

## Что нужно заранее

- **Docker Desktop** — запущен (БД в контейнере).
- **cloudflared** — туннель до `localhost:8000`.
- **Второй Google-аккаунт** (или коллега) — чтобы играть роль «нового участника».
- **Тестовая группа** в Google Chat, куда можно добавить бота.

---

## S0. Подготовка окружения (разово)

- [ ] Запусти Docker Desktop.
- [ ] Подними БД и примени миграции:
  ```powershell
  docker compose up -d db
  alembic upgrade head
  ```
- [ ] Подними бота (пока с выключенной JWT-проверкой — так проще отлаживать):
  ```powershell
  $env:SKIP_JWT_VALIDATION="true"; uvicorn app.main:app --reload
  ```
- [ ] Подними туннель:
  ```powershell
  cloudflared tunnel --url http://localhost:8000
  ```
- [ ] В Google Cloud Console → твоё Chat App → настройка вебхука: впиши новый cloudflared-URL
  в поле вебхука и в "Authentication audience". Обнови `CHAT_APP_AUDIENCE` в `.env`,
  перезапусти бота.

**Проверка готовности:**
```powershell
curl http://localhost:8000/api/v1/health   # → {"status":"ok","database":"connected"}
```

> ℹ️ Если `SKIP_JWT_VALIDATION=true`, бот принимает события Google без проверки подписи —
> этого достаточно для проверки всей логики. Проверку самой JWT-валидации делаем отдельно в S8.

---

## S1. Онбординг нового участника

**Цель:** анкета показывается в DM, ответы сохраняются в `profiles` + `answers`.

- [ ] Вторым аккаунтом открой **личный чат (DM)** с ботом.
- [ ] Напиши боту `анкета`.
  - ✅ Ожидание: бот присылает карточку «Привет! Я EnglishMeetBot 🎉» с 7 вопросами.
- [ ] Заполни все поля (чекбоксы, радио, свободный текст) и нажми **«Отправить анкету»**.
  - ✅ Ожидание: «Спасибо, анкета сохранена!».
- [ ] Заполни анкету **ещё раз**.
  - ✅ Ожидание: снова «Спасибо», история растёт (не перезаписывается).

**Проверка в БД** (замени `<ID>` на реальный id пользователя):
```powershell
docker exec -it meet_bot_db psql -U meet_bot_user -d english_meet_db
```
```sql
-- профиль появился и отмечен как онборднутый
SELECT workspace_user_id, onboarding_completed, interests, preferred_days, public_consent
FROM profiles
WHERE workspace_user_id = 'users/<ID>';

-- ответов 7, после повторного прохождения — 14
SELECT COUNT(*) FROM answers a JOIN profiles p ON p.id = a.profile_id
WHERE p.workspace_user_id = 'users/<ID>';
```

---

## S2. Добавление бота в группу

**Цель:** при добавлении в группу бот пишет анкету в DM тем, у кого DM уже есть,
а остальных тегает `@упоминанием` в группу.

- [ ] Создай тестовую группу (Space) и **добавь в неё бота**.
  - ✅ Ожидание: в `config["space_id"]` запишется имя группы.
- [ ] Для участника **с уже созданным DM** (ты прошёл S1) — бот должен прислать анкету **в личку**.
- [ ] Для участника **без DM** (новый аккаунт, который боту не писал) — бот пишет **в группу**
  строку вида `@Имя — напишите мне в личку, чтобы пройти анкету 👋`.
  - ✅ Ожидание: в группе карточка анкеты **не** появляется — только упоминание.

**Проверка в БД:**
```sql
-- группа хранится в config, а НЕ в chat_space_id профиля
SELECT * FROM config WHERE key = 'space_id';

-- у «старых» участников chat_space_id заполнен, у «новых» — NULL
SELECT workspace_user_id, chat_space_id FROM profiles ORDER BY id DESC LIMIT 10;
```

---

## S3. Ежедневный опрос — полный цикл

**Цель:** карточка опроса уходит в группу, голоса пишутся, в 14:05 подводится итог.

- [ ] Бот должен быть в группе (S2) и `config["space_id"]` заполнен.
- [ ] Запусти отправку опроса сейчас (не жди 9:00):
  ```powershell
  .\venv\Scripts\python scripts\send_poll_now.py
  ```
  - ✅ Ожидание: в группу приходит карточка «Кто сегодня и во сколько? 🗓️»
    с кнопками `15:00` / `16:00` / `17:00` / `Не могу сегодня`.
- [ ] Нажми **«15:00»**.
  - ✅ Ожидание: «Спасибо, учёл! 🙌».
- [ ] Нажми **«16:00»** (переголос).
  - ✅ Ожидание: голос **сменяется** на 16:00 (у тебя одно время).
- [ ] Нажми **«Не могу сегодня»**.
  - ✅ Ожидание: «Спасибо, учёл!», голос снят.

**Проверка в БД:**
```sql
-- активный опрос дня
SELECT id, poll_date, status, voting_deadline FROM daily_polls
WHERE poll_date = CURRENT_DATE;

-- голос один на человека (после «не могу» — 0 строк)
SELECT p.workspace_user_id, s.slot_start
FROM poll_votes v
JOIN profiles p ON p.id = v.profile_id
JOIN poll_slots s ON s.id = v.poll_slot_id
JOIN daily_polls d ON d.id = s.poll_id
WHERE d.poll_date = CURRENT_DATE;

-- статус ответа
SELECT p.workspace_user_id, pr.status
FROM poll_responses pr JOIN profiles p ON p.id = pr.profile_id
JOIN daily_polls d ON d.id = pr.poll_id
WHERE d.poll_date = CURRENT_DATE;
```

### Финализация (14:05)

- [ ] Собери **≥3 голоса за одно время** (нужно 3 аккаунта или коллеги) — тогда будет встреча.
- [ ] Либо проголосуй один — тогда встреча **не наберётся** и будет отмена.
- [ ] Дождись 14:05 (или попроси меня/прогони финализацию вручную).
  - ✅ Ожидание при кворуме: в группе «Встреча сегодня в 15:00 🎉» + предложения недобравшим.
  - ✅ Ожидание без кворума: «Сегодня встреча не набирается — отмена».

**Проверка в БД:**
```sql
SELECT id, status, closed_at FROM daily_polls WHERE poll_date = CURRENT_DATE;
SELECT * FROM meeting_instances ORDER BY id DESC LIMIT 5;
```

---

## S4. Еженедельный вопрос (LLM + банк)

**Цель:** персональный вопрос генерится по интересам, при сбое — fallback на банк.

- [ ] У профиля должны быть интересы (`interests`) — они появляются после S1.
- [ ] Прогони генерацию вопроса (если нет отдельного скрипта — через автотест `pytest -m live`):
  ```powershell
  pytest tests/e2e/test_live_llm.py -m live
  ```
  - ✅ Ожидание: вернулся непустой персональный вопрос.
- [ ] Чтобы проверить fallback: временно закомментируй `OPENROUTER_API_KEY` в `.env`,
  перезапусти бота, вызови генерацию.
  - ✅ Ожидание: используется детерминированный вопрос из `question_bank.BANK`.

---

## S5. ENG-7: приглашения + напоминание после выбора времени

**Цель:** ответившим на опрос уходят личные приглашения, в группу — пост, за час — напоминание.

- [ ] Должны быть: встреча (`meeting_instances.status='scheduled'`) и профили со статусом `responded`.
- [ ] Прогони:
  ```powershell
  .\venv\Scripts\python -m scripts.test_eng7_flow
  ```
  - ✅ Ожидание: ответившим в личку приходит «Встреча по английскому: <день> в <время>».
- [ ] За час до встречи (джобом) приходит напоминание «⏰ Через час встреча по английскому!».

**Проверка в БД:**
```sql
SELECT id, scheduled_start, status FROM meeting_instances ORDER BY id DESC;
SELECT p.workspace_user_id, pr.status FROM poll_responses pr
JOIN profiles p ON p.id = pr.profile_id WHERE pr.status = 'responded';
```

---

## S6. Check-in «Я на встрече ✅»

**Цель:** кнопка засчитывает отметку только внутри окна встречи.

- [ ] Нужна встреча, начинающаяся вот-вот (`scheduled_start` ≈ сейчас).
- [ ] В момент окна (±`checkin_window_min` минут) в группу приходит карточка
  «Встреча началась?» с кнопкой «Я на встрече ✅».
- [ ] Нажми кнопку **внутри окна** → ✅ «Ты на встрече! Баллы зачислены 🎉».
- [ ] Повтори **вне окна** → ✅ «Кнопка вне окна встречи — отметка не засчитана ⏳».

**Проверка в БД:**
```sql
SELECT p.workspace_user_id, a.status, a.is_within_window, a.checkin_attempted_at
FROM attendance a JOIN profiles p ON p.id = a.profile_id
ORDER BY a.id DESC LIMIT 5;
```

---

## S7. Broadcast-рассылка

**Цель:** сообщение уходит в DM тем, у кого DM есть; остальные — в skipped/missing.

- [ ] У части профилей должен быть заполнен `chat_space_id` (S1).
- [ ] Прогони:
  ```powershell
  .\venv\Scripts\python scripts\test_broadcast_writers.py
  .\venv\Scripts\python scripts\test_broadcast_space.py
  ```
  - ✅ Ожидание: в DM приходит текст; в выводе скрипта видно `sent`/`skipped`/`missing_dm`.

---

## S8. Негативные сценарии

| # | Сценарий | Как воспроизвести | Ожидание |
|---|----------|-------------------|----------|
| 8.1 | Битый/отсутствующий JWT | перезапусти бота с `SKIP_JWT_VALIDATION=false`, дёрни вебхук без валидной подписи | `401` |
| 8.2 | Невалидное время | через скрипт отправь `time="banana"` | «Не получилось сохранить», голос не записан |
| 8.3 | Пустая анкета | нажми «Отправить анкету» с пустыми полями | «Анкета пустая…» |
| 8.4 | Сабмит после дедлайна | проголосуй после `voting_deadline` | «Голосование уже закрыто» |
| 8.5 | «анкета» в группе | напиши `анкета` в общий Space | «Напиши мне в личку…», карточки нет |

- [ ] Проверь 8.5 вручную прямо в группе.
- [ ] 8.1 проверяется перезапуском бота с `SKIP_JWT_VALIDATION=false` (не забудь вернуть `true` после).

---

## Порядок прогона

Рекомендуемый маршрут, чтобы ничего не перепрыгивать:

```
S0 → S1 (онбординг) → S2 (группа) → S3 (опрос) → S5 (приглашения)
   → S6 (check-in) → S4 (LLM) → S7 (broadcast) → S8 (негативные)
```

## Шпаргалка по БД

```powershell
docker exec -it meet_bot_db psql -U meet_bot_user -d english_meet_db
```

```sql
\dt                          -- список таблиц
SELECT * FROM profiles ORDER BY id DESC LIMIT 5;
SELECT * FROM daily_polls ORDER BY poll_date DESC LIMIT 3;
SELECT * FROM poll_responses ORDER BY id DESC LIMIT 5;
SELECT * FROM poll_votes ORDER BY id DESC LIMIT 5;
SELECT * FROM meeting_instances ORDER BY id DESC LIMIT 5;
SELECT * FROM attendance ORDER BY id DESC LIMIT 5;
SELECT * FROM answers ORDER BY id DESC LIMIT 10;
SELECT * FROM config;
```
