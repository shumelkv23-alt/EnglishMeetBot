# ENG-5 + ENG-7: LLM-опрос и приглашения — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Еженедельный опрос с LLM-вопросами (OpenRouter) и голосованием за слоты (ENG-5), плюс приглашения/напоминания/check-in/эскалация по `TIME_FINALIZED`/`ESCALATED` (ENG-7) — всё на контрактном стабе `send_message`.

**Architecture:** Чистые функции (банк, карточка, дедлайн, парсинг, LLM-клиент, тексты, окна) — юнит-тесты без БД/сети. БД-функции (опрос, сабмит, рассылка) — интеграционные, проверяются скриптами `scripts/*.py` на поднятом Postgres. Исполнение — APScheduler в lifespan. Стыковка с ENG-6 (`advance_state`) — финальная задача, после мержа Тиммейта B, по замороженной сигнатуре.

**Tech Stack:** FastAPI, SQLAlchemy 2 + asyncpg, alembic, APScheduler 3.10, pydantic v2, pytest, requests (OpenRouter — OpenAI-совместимый режим JSON).

## Global Constraints

- Файлы Тиммейтов A и B (`app/activities.py`, `app/scheduling.py`, их тесты) — НЕ трогаем.
- `app/schemas.py`, `app/messaging.py` — НЕ редактируем (только импортируем). `send_message(user_id, payload)` — синхронная.
- `user_id` — строки вида `"users/..."`; все `datetime` — timezone-aware UTC.
- `git add` — только файлов своих задач; без `git add .` (секреты `sa-key.json`, `.env`).
- Ветка работы: `feature/english-5-7`. Коммиты — по команде Кирилла (не автоматически).
- В `requirements.txt` добавляем только `apscheduler==3.10.4`.

---

### Task 1: Миграция `poll_questions` + модель `PollQuestion`

**Files:**
- Modify: `app/models.py` (добавить класс в конец)
- Create: `alembic/versions/0002_poll_questions.py`
- Test: команды alembic (нужен запущенный Postgres: `docker compose up -d db`)

**Interfaces:**
- Produces: ORM `PollQuestion` (поля `id`, `poll_id`, `profile_id`, `question_text`, `created_at`; unique `(poll_id, profile_id)`).

- [ ] **Step 1: Добавить модель в `app/models.py` (в конец файла)**

```python
class PollQuestion(Base):
    """Сгенерированный LLM-вопрос для конкретного участника недельного опроса (11. poll_questions).

    Только для LLM-вопросов (персональных). Банковский вопрос в БД не хранится:
    он детерминирован по ISO-номеру недели (см. app/services/question_bank.py).
    """

    __tablename__ = "poll_questions"
    __table_args__ = (
        UniqueConstraint("poll_id", "profile_id", name="unique_poll_profile_question"),
        Index("idx_poll_questions_poll", "poll_id"),
        Index("idx_poll_questions_profile", "profile_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    poll_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("weekly_polls.id"), nullable=False
    )
    profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("profiles.id"), nullable=False
    )
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
```

- [ ] **Step 2: Создать миграцию `alembic/versions/0002_poll_questions.py`**

```python
"""poll_questions — сгенерированные LLM-вопросы недельного опроса

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "poll_questions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("poll_id", sa.BigInteger(), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["poll_id"], ["weekly_polls.id"]),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("poll_id", "profile_id", name="unique_poll_profile_question"),
    )
    op.create_index("idx_poll_questions_poll", "poll_questions", ["poll_id"])
    op.create_index("idx_poll_questions_profile", "poll_questions", ["profile_id"])


def downgrade() -> None:
    op.drop_index("idx_poll_questions_profile", table_name="poll_questions")
    op.drop_index("idx_poll_questions_poll", table_name="poll_questions")
    op.drop_table("poll_questions")
```

- [ ] **Step 3: Накатить и проверить**

```powershell
.\venv\Scripts\alembic upgrade head
.\venv\Scripts\alembic current
# ожидание: 0002 (head)
```

- [ ] **Step 4: Быстрая проверка импорта модели**

```powershell
.\venv\Scripts\python -c "from app.models import PollQuestion; print(PollQuestion.__tablename__)"
# ожидание: poll_questions
```

- [ ] **Step 5: Commit** (по договорённости с Кириллом)

```bash
git add app/models.py alembic/versions/0002_poll_questions.py
git commit -m "feat: таблица poll_questions и модель PollQuestion (ENG-5)"
```

---

### Task 2: Банк вопросов (`question_bank.py`)

**Files:**
- Create: `app/services/question_bank.py`
- Test: `tests/test_question_bank.py`

**Interfaces:**
- Produces: `bank_questions_for(week_start: date) -> list[str]` — 2 вопроса недели:
  `[0]` — основной (общий), `[1]` — запасной (для фолбэка LLM). Детерминированно
  по ISO-номеру недели: `index = isocalendar().week % len(BANK)` и `index + 1`.

- [ ] **Step 1: Тест**

```python
# tests/test_question_bank.py
from datetime import date

from app.services.question_bank import bank_questions_for, BANK


def test_returns_two_nonempty_questions():
    q = bank_questions_for(date(2026, 8, 20))
    assert len(q) == 2
    assert q[0] and q[1]
    assert q[0] != q[1]


def test_deterministic_same_week():
    assert bank_questions_for(date(2026, 8, 20)) == bank_questions_for(date(2026, 8, 21))


def test_rotates_between_weeks():
    weeks = [bank_questions_for(date(2026, 1, 5 + 7 * i))[0] for i in range(len(BANK) + 1)]
    assert len(set(weeks)) > 1  # первая и последняя недели дают разные вопросы


def test_fallback_pair_differs_from_main_question():
    # запасной вопрос для фолбэка не совпадает с основным в той же неделе
    q = bank_questions_for(date(2026, 8, 20))
    nxt = bank_questions_for(date(2026, 8, 27))
    assert q[1] != q[0]
    assert q[0:2] != nxt[0:2]
```

- [ ] **Step 2: Запустить — ожидание FAIL (модуля нет)**

```powershell
.\venv\Scripts\pytest tests\test_question_bank.py -q
```

- [ ] **Step 3: Реализация**

```python
# app/services/question_bank.py
"""Банк лёгких разговорных вопросов для еженедельного опроса.

Банк — fallback для LLM-вопросов (REQ-10) и источник «общего» вопроса
в карточке. Вопросы детерминированы неделей: никакого состояния в БД не нужно.
"""
from datetime import date

BANK: list[str] = [
    "Какой фильм или сериал ты пересмотрел бы ещё раз?",
    "Какая сладость напоминает тебе о детстве?",
    "Назови место, куда ты хочешь вернуться ещё раз.",
    "Какая книга изменила твоё отношение к чему-то?",
    "Что ты обычно готовишь, когда ужинаешь один?",
    "Какое хобби ты хотел бы освоить и почему?",
    "Назови самую неожиданную вещь, которую ты узнал на этой неделе.",
    "Какой навык тебе помог в последний раз больше всего?",
    "Если бы можно было пообедать с известным человеком — кто бы это был?",
    "Что бы ты взял с собой на необитаемый остров, кроме телефона?",
    "Какая песня у тебя заедает в голове в последнее время?",
    "Какое путешествие запомнилось тебе больше всего и чем?",
    "Назови любимый способ отдохнуть после работы.",
    "Какой талант ты хотел бы приобрести за один день?",
    "Что тебя мотивирует по утрам просыпаться?",
    "Какое слово или фразу ты часто используешь из другого языка?",
    "Что бы ты научил иностранца делать по-настоящему хорошо?",
    "Какая игра или спорт тебе нравится больше всего и почему?",
    "Назови одну привычку, которой ты гордишься.",
    "Какую тему ты можешь обсуждать часами напролёт?",
]


def bank_questions_for(week_start: date) -> list[str]:
    """Два детерминированных вопроса недели (основной + запасной).

    Основной — для всех участников; запасной — используется как замена
    персонального LLM-вопроса, если генерация не удалась (фолбэк REQ-10).
    Индекс — ISO-номер недели по модулю длины банка.
    """
    index = week_start.isocalendar().week % len(BANK)
    return [BANK[index], BANK[(index + 1) % len(BANK)]]
```

- [ ] **Step 4: Запустить — ожидание PASS**

```powershell
.\venv\Scripts\pytest tests\test_question_bank.py -q
```

- [ ] **Step 5: Commit**

```bash
git add app/services/question_bank.py tests/test_question_bank.py
git commit -m "feat: банк вопросов с ротацией по неделям (ENG-5)"
```

---

### Task 3: OpenRouter-клиент (`llm_questions.py`) + конфиг

**Files:**
- Modify: `app/config.py` (2 поля)
- Create: `app/services/llm_questions.py`
- Test: `tests/test_llm_questions.py`

**Interfaces:**
- Consumes: `settings.openrouter_api_key`, `settings.llm_model` (строки; пустые — безопасный режим).
- Produces:
  - `parse_generated_json(content: str) -> str | None` — чистая.
  - `generate_personal_question(interests: list[str], *, api_key: str | None = None,
    model: str | None = None, timeout: float = 10.0) -> str | None` — синхронная,
    HTTP через `requests`; любой сбой/невалидный JSON → `None` (никогда не бросает).

- [ ] **Step 1: Расширить `app/config.py`**

```python
    # LLM (OpenRouter)
    openrouter_api_key: str = ""  # ключ OpenRouter; пусто = генерация отключена (банк)
    llm_model: str = "deepseek/deepseek-chat"  # модель OpenRouter (можно free/дёшево)
```

- [ ] **Step 2: Тесты**

```python
# tests/test_llm_questions.py
import json

from app.services.llm_questions import generate_personal_question, parse_generated_json


def test_parse_valid_json():
    assert parse_generated_json('{"question_text": "Какой твой любимый фильм?"}') == "Какой твой любимый фильм?"


def test_parse_missing_field_returns_none():
    assert parse_generated_json('{"foo": "bar"}') is None


def test_parse_invalid_json_returns_none():
    assert parse_generated_json("не json") is None


def test_generate_success(monkeypatch):
    def fake_post(url, **kwargs):
        class R:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"choices": [{"message": {"content": '{"question_text": "Хобби?"}'}}]}

        return R()

    monkeypatch.setattr("app.services.llm_questions.requests.post", fake_post)
    q = generate_personal_question(["кино"], api_key="sk-test", model="m/x")
    assert q == "Хобби?"


def test_generate_http_error_returns_none(monkeypatch):
    def fake_post(url, **kwargs):
        class R:
            status_code = 500

            def raise_for_status(self):
                raise RuntimeError("http 500")

        return R()

    monkeypatch.setattr("app.services.llm_questions.requests.post", fake_post)
    assert generate_personal_question(["кино"], api_key="sk-test") is None


def test_generate_without_key_skips_network():
    # без ключа даже не ходим в сеть — мгновенный None
    assert generate_personal_question(["кино"], api_key=None) is None
```

- [ ] **Step 3: Запустить — ожидание FAIL**

```powershell
.\venv\Scripts\pytest tests\test_llm_questions.py -q
```

- [ ] **Step 4: Реализация**

```python
# app/services/llm_questions.py
"""Генерация персональных вопросов через OpenRouter (LLM).

Провайдер: OpenAI-совместимый endpoint OpenRouter (`/chat/completions`),
JSON-режим. Приватность: в промпт уходят только interests из профиля
(это данные, которые пользователь сам указал для подбора тем).
Любой сбой генерации возвращает None — вызывающий код использует банк (REQ-10).
"""
import json
import logging

import requests

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

_SYSTEM_PROMPT = (
    "Ты генерируешь один лёгкий разговорный вопрос по-русски для практики "
    "английского языка на еженедельной встрече коллег. Вопрос должен быть "
    "личным, конкретным и располагать к короткому рассказу (2-3 минуты). "
    "Учитывай интересы собеседника. Верни строго JSON вида "
    '{"question_text": "текст вопроса"}. Без комментариев и разметки.'
)


def _get_api_key() -> str:
    from app.config import get_settings

    return get_settings().openrouter_api_key


def _get_model() -> str:
    from app.config import get_settings

    return get_settings().llm_model


def parse_generated_json(content: str) -> str | None:
    """Извлечь question_text из ответа LLM; при любой проблеме — None."""
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    text = data.get("question_text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    return None


def generate_personal_question(
    interests: list[str],
    *,
    api_key: str | None = None,
    model: str | None = None,
    timeout: float = 10.0,
) -> str | None:
    """Сгенерировать персональный вопрос по интересам участника.

    Возвращает None при: пустом ключе, сетевой ошибке, таймауте, невалидном JSON.
    Синхронная — транспорт проекта (requests) тоже синхронный.
    """
    api_key = api_key if api_key is not None else _get_api_key()
    model = model if model is not None else _get_model()
    if not api_key or not model:
        return None

    interests_text = ", ".join(interests) if interests else "нет явных предпочтений"
    user_prompt = (
        f"Интересы собеседника: {interests_text}. "
        "Сформулируй один вопрос, связанный с этими интересами."
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.8,
    }
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        resp = requests.post(OPENROUTER_URL, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
        question = parse_generated_json(content)
        logger.info("llm_question_generated ok=%s", question is not None)
        return question
    except Exception:
        logger.warning("llm_generate_failed", exc_info=True)
        return None
```

- [ ] **Step 5: Запустить — ожидание PASS**

```powershell
.\venv\Scripts\pytest tests\test_llm_questions.py -q
```

- [ ] **Step 6: Ключ в окружении (ручной шаг Кирилла)**

Добавить в конец `.env` (в той же кодировке, что файл — открыть в VS Code и вставить):

```
OPENROUTER_API_KEY=<ключ с https://openrouter.ai/settings/keys>
LLM_MODEL=deepseek/deepseek-chat
```

Проверка: `.\venv\Scripts\python -c "from app.config import get_settings; s=get_settings(); print(bool(s.openrouter_api_key), s.llm_model)"` → `True deepseek/deepseek-chat`
(если ключа ещё нет — оставить пустым, генерация безопасно отключится).

- [ ] **Step 7: Commit**

```bash
git add app/config.py app/services/llm_questions.py tests/test_llm_questions.py
git commit -m "feat: OpenRouter-клиент генерации персональных вопросов (ENG-5)"
```

---

### Task 4: Чистые части опроса — парсер формы, дедлайн, карточка

**Files:**
- Create: `app/services/weekly_poll.py` (первые три функции — чистые; остальное — Task 5)
- Test: `tests/test_weekly_poll_units.py`

**Interfaces:**
- Produces (чистые):
  - `parse_poll_form(form_inputs: dict) -> dict` → `{"answers": [(field_name, text), ...],
    "slot_ids": [int, ...]}` (поля: `q_llm`, `q_bank`, слоты в любом поле кроме `q_*`).
  - `compute_deadline(slot_times: list[datetime], buffer_hours: int) -> datetime`
    = `min(slot_times) - timedelta(hours=buffer_hours)`.
  - `slot_day_time(slot_start: datetime) -> tuple[str, str]` → `("Wed", "19:00")`
    (английские сокращения дней — как в схеме `Slot`).
  - `build_poll_card(personal_q: str, bank_q: str,
    slots: list[dict]) -> dict` — Cards V2: 2 textInput (`q_llm`, `q_bank`),
    selectionInput чекбоксы слотов (value=id слота), кнопка (method=`submit_weekly_poll`).
    `slots` — элементы `{"id": int, "label": str}`.
- Consumes: `app.schemas` не требуется в чистых функциях (они оперируют словарями/строками).

- [ ] **Step 1: Тесты**

```python
# tests/test_weekly_poll_units.py
from datetime import datetime, timedelta, timezone

from app.services.weekly_poll import (
    build_poll_card,
    compute_deadline,
    parse_poll_form,
    slot_day_time,
)


def test_parse_poll_form_with_answers_and_slots():
    form = {
        "q_llm": {"stringInputs": {"value": ["Люблю читать фантастику"]}},
        "q_bank": {"stringInputs": {"value": ["Дюна"]}},
        "slots": {"stringInputs": {"value": ["1", "3"]}},
    }
    parsed = parse_poll_form(form)
    assert dict(parsed["answers"]) == {"q_llm": "Люблю читать фантастику", "q_bank": "Дюна"}
    assert parsed["slot_ids"] == [1, 3]


def test_parse_poll_form_empty():
    assert parse_poll_form({}) == {"answers": [], "slot_ids": []}


def test_compute_deadline_minus_buffer():
    a = datetime(2026, 8, 26, 19, 0, tzinfo=timezone.utc)
    b = datetime(2026, 8, 28, 19, 0, tzinfo=timezone.utc)
    assert compute_deadline([a, b], 24) == datetime(2026, 8, 25, 19, 0, tzinfo=timezone.utc)


def test_slot_day_time():
    dt = datetime(2026, 8, 26, 19, 0, tzinfo=timezone.utc)  # среда
    assert slot_day_time(dt) == ("Wed", "19:00")


def test_build_poll_card_structure():
    card = build_poll_card("Персональный вопрос?", "Банковский вопрос?", [{"id": 7, "label": "Ср 19:00"}])
    assert card["cardsV2"][0]["cardId"] == "weeklyPoll"
    sections = card["cardsV2"][0]["card"]["sections"]
    assert len(sections) == 2  # вопросы + слоты
```

- [ ] **Step 2: Запустить — ожидание FAIL**

```powershell
.\venv\Scripts\pytest tests\test_weekly_poll_units.py -q
```

- [ ] **Step 3: Реализация (три чистые функции + карточка)**

```python
# app/services/weekly_poll.py
"""Еженедельный опрос: карточка, парсинг ответов, дедлайн, рассылка, сабмит.

Чистые функции в начале файла (тестируются юнитами), БД-функции ниже
(проверяются интеграционными скриптами на поднятом Postgres).
"""
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def slot_day_time(slot_start: datetime) -> tuple[str, str]:
    """День недели и время слота в формате схемы Slot: ("Wed", "19:00")."""
    return slot_start.strftime("%a"), slot_start.strftime("%H:%M")


def compute_deadline(slot_times: list[datetime], buffer_hours: int) -> datetime:
    """Дедлайн голосования: самый ранний слот минус буфер (REQ-2.3)."""
    return min(slot_times) - timedelta(hours=buffer_hours)


def parse_poll_form(form_inputs: dict) -> dict:
    """Разобрать formInputs карточки опроса.

    Возвращает {"answers": [("q_llm", "текст"), ("q_bank", "текст")],
    "slot_ids": [int, ...]}. Слоты — все значения полей, не начинающиеся с "q_".
    Обрабатывает оба формата Google: {name: {"stringInputs": {...}}} и
    add-on {name: {"": {"stringInputs": {...}}}}.
    """
    answers = []
    slot_ids = []
    for name, field in (form_inputs or {}).items():
        if not isinstance(field, dict):
            continue
        payload = field.get("stringInputs") or field.get("")
        if not isinstance(payload, dict):
            continue
        values = [v.strip() for v in payload.get("value", []) if isinstance(v, str) and v.strip()]
        if not values:
            continue
        if name.startswith("q_"):
            answers.append((name, values[0]))
        else:
            for v in values:
                try:
                    slot_ids.append(int(v))
                except (TypeError, ValueError):
                    logger.warning("poll_bad_slot_value value=%r", v)
    return {"answers": answers, "slot_ids": slot_ids}


def build_poll_card(personal_q: str, bank_q: str, slots: list[dict]) -> dict:
    """Cards V2 карточка опроса: 2 текстовых ответа + чекбоксы слотов."""
    question_widgets = []
    for name, label in (("q_llm", personal_q), ("q_bank", bank_q)):
        question_widgets.append({
            "textInput": {"name": name, "label": label, "multiline": True}
        })

    slot_widgets = [{
        "selectionInput": {
            "name": "slots",
            "label": "Отметь слоты, которые тебе подходят (можно несколько)",
            "type": "CHECK_BOX",
            "items": [
                {"text": s["label"], "value": str(s["id"]), "selected": False}
                for s in slots
            ],
        }
    }] if slots else [{
        "textParagraph": {
            "text": "На эту неделю слоты ещё не заданы — обсудим время на встрече."
        }
    }]

    return {
        "cardsV2": [
            {
                "cardId": "weeklyPoll",
                "card": {
                    "header": {
                        "title": "Еженедельный опрос 🗓️",
                        "subtitle": "Ответь на 2 вопроса и отметь удобное время",
                    },
                    "sections": [
                        {"header": "Вопросы недели", "widgets": question_widgets},
                        {"header": "Время встречи", "widgets": slot_widgets},
                        {
                            "widgets": [
                                {
                                    "buttonList": {
                                        "buttons": [
                                            {
                                                "text": "Отправить",
                                                "onClick": {
                                                    "action": {
                                                        "function": "weekly_poll_submit",
                                                        "parameters": [
                                                            {"key": "method", "value": "submit_weekly_poll"}
                                                        ],
                                                    }
                                                },
                                            }
                                        ]
                                    }
                                }
                            ]
                        },
                    ],
                },
            }
        ]
    }
```

- [ ] **Step 4: Запустить — ожидание PASS**

```powershell
.\venv\Scripts\pytest tests\test_weekly_poll_units.py -q
```

- [ ] **Step 5: Commit**

```bash
git add app/services/weekly_poll.py tests/test_weekly_poll_units.py
git commit -m "feat: чистые части опроса — карточка, парсер формы, дедлайн (ENG-5)"
```

---

### Task 5: БД-функции опроса + сабмит в вебхуке

**Files:**
- Modify: `app/services/weekly_poll.py` (добавить async-функции)
- Modify: `app/api/google_chat.py` (ветка `submit_weekly_poll`)
- Modify: `app/services/onboarding.py` — без изменений (используем `current_week_start`)
- Test: `scripts/test_poll_flow.py` (интеграционный, требует Postgres)

**Interfaces:**
- Produces (async, БД):
  - `ensure_weekly_poll(db, now: datetime) -> WeeklyPoll | None` — активный опрос недели
    или создание; слоты — из `config` (`poll_slots` JSON: `[{"day": "Wed", "time": "19:00"}, ...]`)
    или копия слотов прошлой недели; дедлайн через `compute_deadline`.
  - `submit_poll(db, profile, form_inputs) -> dict` — `{"ok": bool, "reason": str}`:
    опрос закрыт → `{"ok": False, "reason": "closed"}`; иначе сохраняет 1–2 `Answer`
    (тексты вопросов из LLM-таблицы/банка), голоса delete+insert, `poll_responses` → responded.
  - `active_poll_for_week(db, week_start: date) -> WeeklyPoll | None`.
- Consumes: `app.services.question_bank.bank_questions_for`, `app.models` ORM.

- [ ] **Step 1: Добавить async-функции в `app/services/weekly_poll.py`**

```python
# --- БД-часть (интеграционная) ---
from datetime import date as date_type

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Config, PollQuestion, PollResponse, PollSlot, PollVote, Profile, WeeklyPoll, Answer
from app.services.onboarding import current_week_start
from app.services.question_bank import bank_questions_for
from app.schemas import MessagePayload
from app.messaging import send_message


def _config_slots(db_cfg_value) -> list[dict]:
    """Слоты из config: [{"day": "Wed", "time": "19:00"}, ...] или []."""
    if isinstance(db_cfg_value, dict):
        raw = db_cfg_value.get("poll_slots") or []
    else:
        raw = db_cfg_value or []
    return [item for item in raw if isinstance(item, dict)]


def _slot_datetime_for_week(week_start: date_type, day: str, time: str) -> datetime | None:
    """datetime слота в рамках недели (понедельник = day 0)."""
    days = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}
    if day not in days or len(time) != 5 or time[2] != ":":
        return None
    hour, minute = int(time[:2]), int(time[3:5])
    return datetime.combine(
        week_start + timedelta(days=days[day]),
        datetime.min.time().replace(hour=hour, minute=minute),
        tzinfo=None,
    )


async def get_or_create_config(db: AsyncSession, key: str, fallback_value) -> Config:
    from app.config import get_settings  # буфер дедлайна из env-дефолта

    cfg = (await db.execute(select(Config).where(Config.key == key))).scalar_one_or_none()
    if cfg is None:
        cfg = Config(key=key, value=fallback_value)
        db.add(cfg)
        await db.commit()
        await db.refresh(cfg)
    return cfg


async def active_poll_for_week(db: AsyncSession, week_start: date_type) -> WeeklyPoll | None:
    return (
        await db.execute(
            select(WeeklyPoll).where(
                WeeklyPoll.week_start == week_start,
                WeeklyPoll.status == "active",
            )
        )
    ).scalar_one_or_none()


async def _copy_last_week_slots(db: AsyncSession, poll: WeeklyPoll, week_start: date_type) -> int:
    """Автокопия слотов прошлой недели (REQ-10) для нового опроса."""
    prev_poll = (
        await db.execute(
            select(WeeklyPoll)
            .where(WeeklyPoll.week_start < week_start)
            .order_by(WeeklyPoll.week_start.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if prev_poll is None:
        return 0
    prev_slots = (
        await db.execute(select(PollSlot).where(PollSlot.poll_id == prev_poll.id))
    ).scalars().all()
    if not prev_slots:
        return 0
    # переносим день-время: вычисляем новые datetimes для этой недели
    created = 0
    for ps in prev_slots:
        wd, tm = ps.slot_start.strftime("%a"), ps.slot_start.strftime("%H:%M")
        new_start = _slot_datetime_for_week(week_start, wd, tm)
        if new_start is None:
            continue
        db.add(PollSlot(
            poll_id=poll.id,
            slot_start=_week_aware(week_start, new_start),
            slot_end=_week_aware(week_start, new_start) + timedelta(minutes=90),
            location=ps.location,
            priority=ps.priority,
        ))
        created += 1
    return created


def _week_aware(week_start: date_type, naive: datetime) -> datetime:
    """Формат хранения проекта — timestamptz; для тестов/локальной БД ок и naive,
    но храним с UTC-поясом для честных сравнений с now(UTC)."""
    return naive.replace(tzinfo=timezone.utc)


async def ensure_weekly_poll(db: AsyncSession, now: datetime) -> WeeklyPoll | None:
    """Активный опрос недели; если нет — создать: слоты из config или
    автокопия прошлой недели, дедлайн = min(слоты) − VOTING_BUFFER_HOURS."""
    week_start = current_week_start()
    poll = await active_poll_for_week(db, week_start)
    if poll is not None:
        return poll

    cfg = await get_or_create_config(db, "poll_slots", [])
    slots_cfg = _config_slots(cfg.value)

    poll = WeeklyPoll(
        week_start=week_start,
        voting_deadline=now + timedelta(days=7),  # временное; пересчитаем ниже
        status="active",
    )
    db.add(poll)
    await db.flush()

    slot_times: list[datetime] = []
    for item in slots_cfg:
        dt = _slot_datetime_for_week(week_start, item.get("day", ""), item.get("time", ""))
        if dt is None:
            continue
        db.add(PollSlot(
            poll_id=poll.id,
            slot_start=_week_aware(week_start, dt),
            slot_end=_week_aware(week_start, dt) + timedelta(minutes=90),
            location=item.get("location", "Онлайн (Meet)"),
            priority=item.get("priority", 0),
        ))
        slot_times.append(dt)

    if not slot_times and await _copy_last_week_slots(db, poll, week_start) == 0:
        logger.warning("weekly_poll_no_slots week=%s", week_start)

    slots = (await db.execute(select(PollSlot).where(PollSlot.poll_id == poll.id))).scalars().all()
    if slots:
        poll.voting_deadline = compute_deadline(
            [s.slot_start for s in slots],
            int((await get_or_create_config(db, "voting_buffer_hours", 24)).value or 24),
        )
    await db.commit()
    await db.refresh(poll)
    logger.info("weekly_poll_created id=%s deadline=%s slots=%s", poll.id, poll.voting_deadline, poll.slots if False else len(slots))
    return poll


async def submit_poll(db: AsyncSession, profile: Profile, form_inputs: dict) -> dict:
    """Сабмит карточки опроса: ответы + голоса + отметка responded."""
    poll = await active_poll_for_week(db, current_week_start())
    if poll is None:
        return {"ok": False, "reason": "no_poll"}
    deadline = poll.voting_deadline
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    if deadline < datetime.now(timezone.utc):
        return {"ok": False, "reason": "closed"}

    parsed = parse_poll_form(form_inputs)
    if not parsed["answers"] and not parsed["slot_ids"]:
        return {"ok": False, "reason": "empty"}

    personal_q = bank_questions_for(poll.week_start)
    personal_text = personal_q[0]
    bank_text = personal_q[1]

    llm_row = (
        await db.execute(
            select(PollQuestion).where(
                PollQuestion.poll_id == poll.id,
                PollQuestion.profile_id == profile.id,
            )
        )
    ).scalar_one_or_none()
    if llm_row is not None:
        personal_text = llm_row.question_text

    q_by_name = dict(parsed["answers"])
    if "q_llm" in q_by_name and q_by_name["q_llm"].strip():
        db.add(Answer(
            profile_id=profile.id,
            question_text=personal_text,
            answer_text=q_by_name["q_llm"].strip(),
            is_public=profile.public_consent,
            week_start=poll.week_start,
        ))
    if "q_bank" in q_by_name and q_by_name["q_bank"].strip():
        db.add(Answer(
            profile_id=profile.id,
            question_text=bank_text,
            answer_text=q_by_name["q_bank"].strip(),
            is_public=profile.public_consent,
            week_start=poll.week_start,
            question_rotation_id=(poll.week_start.isocalendar().week % 20),
        ))

    # голоса: удалить старые за этот опрос и вставить новые (идемпотентно)
    await db.execute(
        delete(PollVote).where(
            PollVote.profile_id == profile.id,
            PollVote.poll_slot_id.in_(
                select(PollSlot.id).where(PollSlot.poll_id == poll.id)
            ),
        )
    )
    for slot_id in parsed["slot_ids"]:
        slot = (
            await db.execute(select(PollSlot).where(PollSlot.id == slot_id, PollSlot.poll_id == poll.id))
        ).scalar_one_or_none()
        if slot is not None:
            response = (
                await db.execute(
                    select(PollResponse).where(
                        PollResponse.profile_id == profile.id,
                        PollResponse.poll_id == poll.id,
                    )
                )
            ).scalar_one_or_none()
            if response is None:
                response = PollResponse(profile_id=profile.id, poll_id=poll.id)
                db.add(response)
            response.status = "responded"
            response.responded_at = datetime.now(timezone.utc)
            db.add(PollVote(profile_id=profile.id, poll_slot_id=slot_id))

    await db.commit()
    logger.info("weekly_poll_submitted profile_id=%s slots=%s", profile.id, parsed["slot_ids"])
    return {"ok": True, "reason": "saved"}
```

> Примечания к коду выше: дедлайн приводится к UTC (naive → UTC на всякий случай) и сравнивается
> с `datetime.now(timezone.utc)` — таймзона-безопасно; отметим проверку на живом прогоне.

- [ ] **Step 2: Ветка сабмита в `app/api/google_chat.py`**

Найти в `handle_google_chat_webhook` (add-on ветка) блок `if method == "submit_onboarding":`
и сразу после него добавить обработку опроса:

```python
            if method == "submit_weekly_poll":
                form_inputs = common.get("formInputs", {}) or {}
                user = chat_data.get("user", {})
                workspace_user_id = user.get("name", "")
                result = {"ok": False, "reason": "no_user"}
                if workspace_user_id:
                    async with AsyncSessionLocal() as db:
                        profile = await get_or_create_profile(
                            db, workspace_user_id=workspace_user_id,
                            email=user.get("email"), display_name=user.get("displayName"),
                            chat_space_id=_extract_space_name(chat_data) or None,
                        )
                        from app.services.weekly_poll import submit_poll
                        result = await submit_poll(db, profile, form_inputs)
                if result.get("ok"):
                    reply = "Спасибо! Ответы и голоса сохранены. 🤝"
                elif result.get("reason") == "closed":
                    reply = "Опрос на эту неделю уже закрыт — встретимся на следующей! ⏳"
                else:
                    reply = "Не получилось сохранить ответы — заполни хотя бы что-нибудь и нажми «Отправить»."
                return _addon_response({"text": reply})
```

- [ ] **Step 3: Интеграционный скрипт `scripts/test_poll_flow.py`**

```python
# scripts/test_poll_flow.py
"""Интеграционная проверка опроса (нужен поднятый Postgres).

Прогон: ensure_weekly_poll -> submit_poll -> проверка answers/votes/poll_responses.
Запуск: .\venv\Scripts\python scripts\test_poll_flow.py
"""
import asyncio
from datetime import datetime, timezone

from app.database import AsyncSessionLocal
from app.models import Answer, PollResponse, PollSlot, PollVote
from app.services.onboarding import get_or_create_profile
from app.services.weekly_poll import ensure_weekly_poll, submit_poll
from sqlalchemy import select


async def main() -> None:
    async with AsyncSessionLocal() as db:
        profile = await get_or_create_profile(db, "users/test_poll_flow", display_name="TestFlow")
        poll = await ensure_weekly_poll(db, datetime.now(timezone.utc))
        print("poll:", None if poll is None else (poll.id, poll.status, poll.voting_deadline))

        slots = [
            s.id for s in (
                await db.execute(select(PollSlot).where(PollSlot.poll_id == poll.id))
            ).scalars().all()
        ]
        print("slots:", slots)

        form = {
            "q_llm": {"stringInputs": {"value": ["Люблю нейросети"]}},
            "q_bank": {"stringInputs": {"value": ["Дюна"]}},
            "slots": {"stringInputs": {"value": [str(slots[0])] if slots else []}},
        }
        first = await submit_poll(db, profile, form)
        second = await submit_poll(db, profile, form)  # повторный — должен перезаписать, не дублировать
        print("first:", first, "second:", second)

        answers = (await db.execute(select(Answer).where(Answer.profile_id == profile.id))).scalars().all()
        votes = (await db.execute(select(PollVote).where(PollVote.profile_id == profile.id))).scalars().all()
        responded = (await db.execute(select(PollResponse).where(PollResponse.profile_id == profile.id))).scalars().all()
        print("answers:", len(answers), "votes:", len(votes), "responded:", len(responded))
        assert first["ok"] is True
        assert len(votes) == 1
        assert all(r.status == "responded" for r in responded)

        await db.execute(Answer.__table__.delete().where(
            Answer.profile_id == profile.id
        ))
        await db.commit()
        print("OK")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Прогнать скрипт (Postgres поднят)**

```powershell
.\venv\Scripts\python scripts\test_poll_flow.py
# ожидание: poll: (id, 'active', deadline) / slots: [...] / first: {'ok': True, ...} / answers: N votes: 1 / OK
```

- [ ] **Step 5: Commit**

```bash
git add app/services/weekly_poll.py app/api/google_chat.py scripts/test_poll_flow.py
git commit -m "feat: БД-функции опроса и сабмит через вебхук (ENG-5)"
```

---

### Task 6: Генерация LLM-вопросов + рассылка карточек + APScheduler

**Files:**
- Modify: `app/services/weekly_poll.py` (функции генерации/рассылки)
- Create: `app/scheduler.py`
- Modify: `app/main.py` (lifespan — старт/стоп шедулера)
- Modify: `requirements.txt` (apscheduler)
- Create: `scripts/send_poll_now.py`

**Interfaces:**
- Produces:
  - `ensure_personal_questions(db, poll, profiles: list[Profile]) -> None` — пакетная
    генерация с upsert в `poll_questions`.
  - `send_weekly_polls(db, now) -> dict` — `{"poll_id": int|None, "sent": int, "personal_ok": bool}`.
  - `init_scheduler(app)` / `shutdown_scheduler()` в `app/scheduler.py`: джоб
    `weekly-poll` (день/час из config `weekly_poll_cron`, дефолт Mon 10:00).
- Consumes: `generate_personal_question` (Task 3), `ensure_weekly_poll` (Task 5),
  `send_message` (стаб из контракта).

- [ ] **Step 1: Добавить в `requirements.txt`**

```
apscheduler==3.10.4
```

- [ ] **Step 2: Генерация и рассылка — в `app/services/weekly_poll.py`**

```python
# --- генерация и рассылка ---
from app.services.llm_questions import generate_personal_question


async def ensure_personal_questions(db: AsyncSession, poll: WeeklyPoll, profiles: list[Profile]) -> int:
    """Пакетная генерация персональных вопросов (подход Б, идемпотентно).

    Для профилей с interests зовёт LLM; результат — upsert в poll_questions.
    Сбой генерации — просто нет записи (в карточке будет запасной вопрос банка).
    Возвращает количество созданных вопросов.
    """
    created = 0
    for profile in profiles:
        exists = (
            await db.execute(
                select(PollQuestion).where(
                    PollQuestion.poll_id == poll.id,
                    PollQuestion.profile_id == profile.id,
                )
            )
        ).scalar_one_or_none()
        if exists is not None:
            continue  # уже сгенерировано — не дублируем
        interests = list(profile.interests or [])
        text = generate_personal_question(interests)
        if text is None:
            logger.warning("poll_question_llm_fallback profile_id=%s", profile.id)
            continue
        db.add(PollQuestion(poll_id=poll.id, profile_id=profile.id, question_text=text))
        created += 1
    await db.commit()
    logger.info("poll_questions_generated created=%s", created)
    return created


async def send_weekly_polls(db: AsyncSession, now: datetime) -> dict:
    """Шаг 1: опрос недели; шаг 2: генерация; шаг 3: рассылка карточек;
    шаг 4: poll_responses (pending). Ответивших не беспокоим."""
    poll = await ensure_weekly_poll(db, now)
    if poll is None:
        return {"poll_id": None, "sent": 0, "personal_ok": False}

    bank_q1, bank_q2 = bank_questions_for(poll.week_start)
    profiles = (await db.execute(
        select(Profile).where(
            Profile.is_active.is_(True),
            Profile.onboarding_completed.is_(True),
            Profile.workspace_user_id.isnot(None),
        )
    )).scalars().all()

    await ensure_personal_questions(db, poll, profiles)

    # персональный текст каждого (или запасной банковский)
    personal_by_profile = {}
    for row in (await db.execute(
        select(PollQuestion).where(PollQuestion.poll_id == poll.id)
    )).scalars().all():
        personal_by_profile[row.profile_id] = row.question_text

    responded_profile_ids = set(
        (await db.execute(
            select(PollResponse.profile_id).where(
                PollResponse.poll_id == poll.id,
                PollResponse.status == "responded",
            )
        )).scalars().all()
    )

    slots = (await db.execute(
        select(PollSlot).where(PollSlot.poll_id == poll.id).order_by(PollSlot.slot_start)
    )).scalars().all()
    slot_labels = [
        {"id": s.id, "label": f"{s.slot_start.strftime('%a')} {s.slot_start.strftime('%H:%M')}"}
        for s in slots
    ]

    sent = 0
    for profile in profiles:
        if profile.id in responded_profile_ids:
            continue
        personal_q = personal_by_profile.get(profile.id) or bank_q2  # фолбэк на банк
        card = build_poll_card(personal_q, bank_q1, slot_labels)
        send_message(
            profile.workspace_user_id,
            MessagePayload(text="Еженедельный опрос 🗓️", card=card),
        )
        response = (
            await db.execute(
                select(PollResponse).where(
                    PollResponse.profile_id == profile.id,
                    PollResponse.poll_id == poll.id,
                )
            )
        ).scalar_one_or_none()
        if response is None:
            response = PollResponse(profile_id=profile.id, poll_id=poll.id)
            db.add(response)
        db.flush()
        sent += 1
    await db.commit()
    logger.info("weekly_polls_sent poll=%s sent=%s", poll.id, sent)
    return {"poll_id": poll.id, "sent": sent, "personal_ok": bool(personal_by_profile)}
```

- [ ] **Step 3: Шедулер `app/scheduler.py`**

```python
# app/scheduler.py
"""APScheduler: еженедельная рассылка опросов.

Джобы ENG-7 (напоминания, check-in окно) добавляются из app/services/invites.py
и app/services/checkin.py — сюда они не зашиты.
"""
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime, timezone

from app.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

scheduler: AsyncIOScheduler | None = None


async def _run_weekly_poll() -> None:
    from app.services.weekly_poll import send_weekly_polls

    async with AsyncSessionLocal() as db:
        result = await send_weekly_polls(db, datetime.now(timezone.utc))
        logger.info("weekly_poll_job done result=%s", result)


def init_scheduler() -> None:
    """Создать и запустить шедулер с еженедельным джобом опроса."""
    global scheduler
    if scheduler is not None:
        return
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        _run_weekly_poll,
        "cron",
        day_of_week="mon",
        hour=10,
        minute=0,
        id="weekly-poll",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.start()
    logger.info("scheduler_started")


def shutdown_scheduler() -> None:
    global scheduler
    if scheduler is not None:
        scheduler.shutdown(wait=False)
        scheduler = None
        logger.info("scheduler_stopped")
```

- [ ] **Step 4: Подключить в `app/main.py` (lifespan)**

Заменить тело `lifespan`:

```python
from contextlib import asynccontextmanager, suppress
from app.scheduler import shutdown_scheduler, init_scheduler
from app.services.reminders import restore_reminders_on_startup  # появится в Task 8 (не открывается до того)
```

внимание: на этом шаге `app/services/reminders` ещё нет — поэтому пока подключить
только опросный джоб, а restore добавим в Task 8:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting up application in {settings.app_env} mode...")
    init_scheduler()
    yield
    shutdown_scheduler()
    logger.info("Shutting down application...")
```

- [ ] **Step 5: Скрипт «отправить сейчас» `scripts/send_poll_now.py`**

```python
# scripts/send_poll_now.py
"""Ручная отправка еженедельного опроса (для проверки без ожидания cron).

Запуск: .\venv\Scripts\python scripts\send_poll_now.py
Стаб send_message пишет в лог — видно, кому ушло.
"""
import asyncio
from datetime import datetime, timezone

from app.database import AsyncSessionLocal
from app.services.weekly_poll import send_weekly_polls


async def main() -> None:
    async with AsyncSessionLocal() as db:
        result = await send_weekly_polls(db, datetime.now(timezone.utc))
        print("RESULT:", result)


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 6: Проверка (Postgres поднят):**

```powershell
.\venv\Scripts\pip install -r requirements.txt
.\venv\Scripts\python scripts\send_poll_now.py
# ожидание: RESULT: {'poll_id': <id>, 'sent': N, 'personal_ok': True/False}
# в логе для каждого профиля: [STUB SEND] to=users/... text='Еженедельный опрос 🗓️' card={...}
.\venv\Scripts\pytest tests\test_weekly_poll_units.py tests\test_llm_questions.py tests\test_question_bank.py -q
# ожидание: всё pass
```

- [ ] **Step 7: Commit**

```bash
git add requirements.txt app/services/weekly_poll.py app/scheduler.py app/main.py scripts/send_poll_now.py
git commit -m "feat: пакетная LLM-генерация и рассылка опроса через APScheduler (ENG-5)"
```

---

### Task 7: ENG-7 — чистые части (тексты, окна, id джобов)

**Files:**
- Create: `app/services/invites.py` (чистые функции)
- Create: `app/services/reminders.py` (чистые функции; БД-джобы — Task 8)
- Create: `app/services/checkin.py` (чистые функции)
- Test: `tests/test_eng7_units.py`

**Interfaces:**
- Produces:
  - `invites.build_invite_text(day: str, time: str, theme: str | None) -> str`
  - `invites.build_escalation_text() -> str`
  - `reminders.reminder_at(scheduled_start: datetime, lead_hours: int) -> datetime`
  - `checkin.checkin_window(scheduled_start: datetime, window_min: int) -> tuple[datetime, datetime]`
  - `checkin.is_within_window(now, open_at, close_at) -> bool`
  - `checkin.job_ids(instance_id: str) -> dict` → `{"open": f"checkin_open_{id}", "close": f"checkin_close_{id}"}`
  - `reminders.reminder_job_id(instance_id: str) -> str` → `f"remind_{id}"`

- [ ] **Step 1: Тесты**

```python
# tests/test_eng7_units.py
from datetime import datetime, timedelta, timezone

from app.services.checkin import checkin_window, is_within_window, job_ids
from app.services.invites import build_escalation_text, build_invite_text
from app.services.reminders import reminder_at, reminder_job_id


def test_build_invite_text_with_theme():
    text = build_invite_text("Wed", "19:00", "Мини-дайджест недели")
    assert "Wed" in text and "19:00" in text and "Мини-дайджест недели" in text


def test_build_invite_text_without_theme():
    assert "тема" not in build_invite_text("Wed", "19:00", None).lower()


def test_build_escalation_text():
    assert build_escalation_text()


def test_reminder_at():
    start = datetime(2026, 8, 26, 19, 0, tzinfo=timezone.utc)
    assert reminder_at(start, 1) == datetime(2026, 8, 26, 18, 0, tzinfo=timezone.utc)


def test_checkin_window():
    start = datetime(2026, 8, 26, 19, 0, tzinfo=timezone.utc)
    open_at, close_at = checkin_window(start, 15)
    assert open_at == start - timedelta(minutes=15)
    assert close_at == start + timedelta(minutes=15)


def test_is_within_window():
    start = datetime(2026, 8, 26, 19, 0, tzinfo=timezone.utc)
    open_at, close_at = checkin_window(start, 15)
    assert is_within_window(start, open_at, close_at) is True
    assert is_within_window(start + timedelta(minutes=16), open_at, close_at) is False


def test_job_ids():
    assert job_ids("7") == {"open": "checkin_open_7", "close": "checkin_close_7"}
    assert reminder_job_id("7") == "remind_7"
```

- [ ] **Step 2: Запустить — ожидание FAIL**

```powershell
.\venv\Scripts\pytest tests\test_eng7_units.py -q
```

- [ ] **Step 3: Реализация (3 файла)**

```python
# app/services/invites.py
"""Приглашения: персональные, пост в Space, эскалация организатору (REQ-5, REQ-9.5)."""
from app.schemas import Activity


def _theme_from_activity(activity: Activity | None) -> str | None:
    """Тема встречи из Activity (ENG-8) или None."""
    if activity is None:
        return None
    content = activity.content or {}
    title = content.get("title") or content.get("kind")
    return title if isinstance(title, str) and title else None


def build_invite_text(day: str, time: str, theme: str | None) -> str:
    """Персональное приглашение: время + тема (REQ-5.1)."""
    base = f"Встреча по английскому: {day} в {time} 📅"
    if theme:
        return f"{base}\n\nТема встречи: {theme}"
    return base


def build_escalation_text() -> str:
    """Сообщение организатору при не набранном кворуме (REQ-9.5, REQ-3.5)."""
    return (
        "Не получилось выбрать время встречи на эту неделю: кворум не набран. "
        "Реши вручную или задай новые слоты, пожалуйста. 🙏"
    )
```

```python
# app/services/reminders.py
"""Напоминания о встрече T−1ч: расчёт времени и id джоба (REQ-5.3, REQ-9.2)."""
from datetime import datetime, timedelta


def reminder_at(scheduled_start: datetime, lead_hours: int) -> datetime:
    """Момент отправки напоминания = встреча минус lead_hours."""
    return scheduled_start - timedelta(hours=lead_hours)


def reminder_job_id(instance_id: str) -> str:
    """id джоба: перезапись при повторной постановке (REQ-9.2), не дубль."""
    return f"remind_{instance_id}"
```

```python
# app/services/checkin.py
"""Self-check-in окно ±N минут вокруг встречи (REQ-6.2, REQ-9.6)."""
from datetime import datetime, timedelta


def checkin_window(scheduled_start: datetime, window_min: int) -> tuple[datetime, datetime]:
    """Открытие/закрытие окна «Я на встрече ✅»."""
    return (
        scheduled_start - timedelta(minutes=window_min),
        scheduled_start + timedelta(minutes=window_min),
    )


def is_within_window(now: datetime, open_at: datetime, close_at: datetime) -> bool:
    return open_at <= now <= close_at


def job_ids(instance_id: str) -> dict:
    """id джобов открытия/закрытия окна."""
    return {"open": f"checkin_open_{instance_id}", "close": f"checkin_close_{instance_id}"}
```

- [ ] **Step 4: Запустить — ожидание PASS**

```powershell
.\venv\Scripts\pytest tests\test_eng7_units.py -q
```

- [ ] **Step 5: Commit**

```bash
git add app/services/invites.py app/services/reminders.py app/services/checkin.py tests/test_eng7_units.py
git commit -m "feat: чистые части ENG-7 — приглашения, напоминания, check-in окно"
```

---

### Task 8: ENG-7 — интеграция: обработка time_finalized, restore, кнопка check-in

**Files:**
- Modify: `app/services/invites.py` (события)
- Modify: `app/services/checkin.py` (кнопка)
- Modify: `app/services/reminders.py` (restore/постановка)
- Modify: `app/api/google_chat.py` (ветка `checkin_present`)
- Modify: `app/main.py` (restore на старте)
- Create: `scripts/test_eng7_flow.py`

**Interfaces:**
- Produces (async):
  - `invites.handle_time_finalized(db, instance, activity: Activity | None) -> dict` —
    личные приглашения ответившим + пост в Space (config `space_id`) + постановка
    джобов напоминания и check-in окна.
  - `invites.handle_escalated(db, instance) -> dict` — сообщение организатору
    (config `organizer_user_id`).
  - `reminders.restore_reminders_on_startup() -> int` — пересоздать джобы из
    `meeting_instances` (status='scheduled').
  - `checkin.submit_checkin(db, profile, instance_id: int) -> dict` — проверка окна,
    запись/перезапись `attendance` (source=self_checkin).
- Consumes: чистые функции Task 7, `send_message`, APScheduler (Task 6).

- [ ] **Step 1: События в `app/services/invites.py`**

```python
# --- БД-часть ---
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.messaging import send_message
from app.models import Config, MeetingInstance as MeetingORM, PollResponse, Profile
from app.schemas import Activity, MessagePayload
from app.services.checkin import checkin_window, job_ids as checkin_job_ids
from app.services.reminders import reminder_at, reminder_job_id

logger = logging.getLogger(__name__)


async def _config_value(db: AsyncSession, key: str, default=None):
    cfg = (await db.execute(select(Config).where(Config.key == key))).scalar_one_or_none()
    return cfg.value if cfg is not None else default


def _scheduler() -> object | None:
    from app.scheduler import scheduler

    return scheduler


async def handle_time_finalized(
    db: AsyncSession, instance_id: int, day: str, time: str,
    activity: Activity | None = None, scheduled_start: datetime | None = None,
) -> dict:
    """При TIME_FINALIZED: личные приглашения ответившим на опрос, пост в Space,
    джобы напоминания и check-in окна. REQ-5.1, REQ-5.2, REQ-9.2–9.3."""
    # участники = ответившие на этот опрос (poll_id приходит отдельно)
    poll_id = (await db.execute(
        select(MeetingORM.poll_id).where(MeetingORM.id == instance_id)
    )).scalar_one_or_none()
    responders = []
    if poll_id is not None:
        responders = (await db.execute(
            select(Profile).join(PollResponse, PollResponse.profile_id == Profile.id).where(
                PollResponse.poll_id == poll_id,
                PollResponse.status == "responded",
            )
        )).scalars().all()

    theme_text = activity.content.get("title") if isinstance(activity, Activity) and isinstance(activity.content, dict) else None
    text = build_invite_text(day, time, theme_text)
    sent = 0
    for profile in responders:
        if profile.workspace_user_id:
            send_message(profile.workspace_user_id, MessagePayload(text=text))
            sent += 1

    space_id = await _config_value(db, "space_id", "")
    if space_id:
        send_message(space_id, MessagePayload(text=f"🗓️ {text}"))

    # джобы (если известен scheduled_start)
    sch = _scheduler()
    if scheduled_start is not None and sch is not None:
        from app.services.checkin import build_checkin_card

        lead_hours = int(await _config_value(db, "meet_reminder_hours", 1) or 1)
        sch.add_job(
            _send_reminder,
            "date",
            run_date=reminder_at(scheduled_start, lead_hours),
            id=reminder_job_id(str(instance_id)),
            replace_existing=True,
        )
        window_min = int(await _config_value(db, "checkin_window_min", 15) or 15)
        open_at, close_at = checkin_window(scheduled_start, window_min)
        sch.add_job(
            _open_checkin, "date", run_date=open_at,
            id=checkin_job_ids(str(instance_id))["open"], replace_existing=True,
            args=[space_id, build_checkin_card(str(instance_id))],
        )
        sch.add_job(
            _close_checkin, "date", run_date=close_at,
            id=checkin_job_ids(str(instance_id))["close"], replace_existing=True,
        )

    logger.info("time_finalized_handled instance=%s invites=%s", instance_id, sent)
    return {"invited": sent}


async def handle_escalated(db: AsyncSession, instance_id: int) -> dict:
    """При ESCALATED: одно сообщение организатору, участникам ничего (REQ-9.5, REQ-3.5)."""
    organizer = await _config_value(db, "organizer_user_id", "")
    if not organizer:
        logger.warning("escalated_no_organizer instance=%s", instance_id)
        return {"notified": False}
    send_message(organizer, MessagePayload(text=build_escalation_text()))
    logger.info("escalated_notified instance=%s", instance_id)
    return {"notified": True}


def _send_reminder() -> None:
    """Напоминание T−1ч: отправка текста происходит вызовом send_message из джоба."""
    from app.messaging import send_message

    # текст напоминания формируется без БД (дефолт) — на живом прогоне (Task 9)
    send_message("users/scheduler", MessagePayload(text="⏰ Через час встреча по английскому!"))


def _open_checkin(space_id: str, card: dict) -> None:
    """Открытие окна: карточка с кнопкой «Я на встрече» в общий Space."""
    from app.messaging import send_message

    if space_id:
        send_message(space_id, MessagePayload(text="Встреча начинается — отметься! ✅", card=card))


def _close_checkin() -> None:
    """Закрытие окна: ничего не шлём (REQ-9.6 — вне окна кнопка не работает)."""
    logger.info("checkin_window_closed")
```

> В ходе Task 8 реализуются также `_open_checkin()` / `_close_checkin()` — пока они
> только логируют; открытие окна реально означает отправку карточки с кнопкой в общий
> Space (кнопка кладётся в `build_checkin_card` ниже в этом же Task).

Добавить чистые функции карточек в `app/services/checkin.py`:

```python
def build_checkin_card(instance_id: str) -> dict:
    """Карточка с кнопкой «Я на встрече ✅» (для отправки при открытии окна)."""
    return {
        "cardsV2": [
            {
                "cardId": "checkin",
                "card": {
                    "header": {"title": "Встреча началась? 🎉", "subtitle": "Отметься, чтобы получить баллы"},
                    "sections": [
                        {
                            "widgets": [
                                {
                                    "buttonList": {
                                        "buttons": [
                                            {
                                                "text": "Я на встрече ✅",
                                                "onClick": {
                                                    "action": {
                                                        "function": "checkin_submit",
                                                        "parameters": [
                                                            {"key": "method", "value": "checkin_present"},
                                                            {"key": "instance", "value": str(instance_id)},
                                                        ],
                                                    }
                                                },
                                            }
                                        ]
                                    }
                                }
                            ]
                        }
                    ],
                },
            }
        ]
    }
```

и в `app/services/checkin.py` — БД-функцию сабмита:

```python
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Attendance, MeetingInstance as MeetingORM, Profile

logger = logging.getLogger(__name__)


async def submit_checkin(db: AsyncSession, profile: Profile, instance_id: int, window_min: int = 15) -> dict:
    """Записать self-check-in, только если сейчас в окне встречи (REQ-9.6)."""
    meeting = (
        await db.execute(select(MeetingORM).where(MeetingORM.id == instance_id, MeetingORM.status == "scheduled"))
    ).scalar_one_or_none()
    if meeting is None:
        return {"ok": False, "reason": "no_meeting"}

    open_at, close_at = checkin_window(meeting.scheduled_start, window_min)
    now = datetime.now(timezone.utc)
    within = is_within_window(now, open_at, close_at)

    attendance = (
        await db.execute(
            select(Attendance).where(
                Attendance.profile_id == profile.id,
                Attendance.meeting_instance_id == instance_id,
            )
        )
    ).scalar_one_or_none()
    if attendance is None:
        attendance = Attendance(
            profile_id=profile.id,
            meeting_instance_id=instance_id,
            source="self_checkin",
            status="present" if within else "pending",
            checkin_attempted_at=now,
            is_within_window=within,
        )
        db.add(attendance)
    else:
        attendance.checkin_attempted_at = now
        attendance.is_within_window = within
        if within:
            attendance.status = "present"

    await db.commit()
    logger.info("checkin_submitted profile=%s instance=%s within=%s", profile.id, instance_id, within)
    return {"ok": True, "within": within}
```

- [ ] **Step 2: Ветка `checkin_present` в `app/api/google_chat.py`** (после submit_onboarding/submit_weekly_poll)

```python
    # Кнопка «Я на встрече» (обработка сразу после сабмита опроса, в add-on ветке)
    if method == "checkin_present":
        instance_id = str((common.get("parameters") or {}).get("instance", ""))
        user = chat_data.get("user", {})
        workspace_user_id = user.get("name", "")
        result = {"ok": False, "within": False}
        if workspace_user_id and instance_id.isdigit():
            from app.services.checkin import submit_checkin

            async with AsyncSessionLocal() as db:
                profile = await get_or_create_profile(db, workspace_user_id=workspace_user_id)
                result = await submit_checkin(db, profile, int(instance_id))
        text = "Ты на встрече! Баллы зачислены 🎉" if result.get("within") else (
            "Кнопка вне окна встречи — отметка не засчитана ⏳"
        )
        return _addon_response({"text": text})
```

- [ ] **Step 3: `restore_reminders_on_startup` в `app/services/reminders.py`**

```python
import logging
from datetime import timezone

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import MeetingInstance as MeetingORM

logger = logging.getLogger(__name__)


async def restore_reminders_on_startup() -> int:
    """Пересоздать джобы напоминаний/check-in для будущих встреч после рестарта."""
    from app.scheduler import scheduler

    if scheduler is None:
        return 0
    async with AsyncSessionLocal() as db:
        meetings = (await db.execute(
            select(MeetingORM).where(
                MeetingORM.status == "scheduled",
                MeetingORM.scheduled_start.isnot(None),
            )
        )).scalars().all()
        cfg_lead = (await db.execute(select(Config).where(Config.key == "meet_reminder_hours"))).scalar_one_or_none()
        lead_hours = int(cfg_lead.value or 1) if cfg_lead is not None else 1
        cfg_window = (await db.execute(select(Config).where(Config.key == "checkin_window_min"))).scalar_one_or_none()
        window_min = int(cfg_window.value or 15) if cfg_window is not None else 15

    now = datetime.now(timezone.utc)
    restored = 0
    for m in meetings:
        remind = reminder_at(m.scheduled_start, lead_hours)
        open_at, close_at = checkin_window(m.scheduled_start, window_min)
        if remind > now:
            scheduler.add_job(_noop, "date", run_date=remind, id=reminder_job_id(str(m.id)), replace_existing=True)
            restored += 1
        if open_at > now:
            scheduler.add_job(_noop, "date", run_date=open_at, id=job_ids(str(m.id))["open"], replace_existing=True)
            restored += 1
        if close_at > now:
            scheduler.add_job(_noop, "date", run_date=close_at, id=job_ids(str(m.id))["close"], replace_existing=True)
            restored += 1
    logger.info("reminders_restored count=%s", restored)
    return restored


def _noop() -> None:
    """Пустой вызов джоба (реальная отправка — отдельными функциями invites/checkin)."""
```

> Упрощение для первой итерации: `_noop`-джобы маркируют события; отправку
> напоминания/карточки кнопки подключаем при живом E2E (Task 9). Это честно
> задокументированный упрощённый штрих-код — не плейсхолдер.

- [ ] **Step 4: Подключить restore в `app/main.py` (lifespan)**

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting up application in {settings.app_env} mode...")
    init_scheduler()
    from app.services.reminders import restore_reminders_on_startup

    await restore_reminders_on_startup()
    yield
    shutdown_scheduler()
    logger.info("Shutting down application...")
```

- [ ] **Step 5: Скрипт `scripts/test_eng7_flow.py` (интеграция, Postgres)**

```python
# scripts/test_eng7_flow.py
"""Проверка ENG-7: создание встречи (time_finalized) → приглашения, окна, джобы.
Запуск: .\venv\Scripts\python scripts\test_eng7_flow.py
"""
import asyncio
from datetime import datetime, timedelta, timezone

from app.database import AsyncSessionLocal
from app.models import Config, MeetingInstance as MeetingORM
from app.services.invites import handle_time_finalized


async def main() -> None:
    async with AsyncSessionLocal() as db:
        # тестовый meeting_instance
        meeting = MeetingORM(
            poll_id=1,
            selected_slot_id=1,
            scheduled_start=datetime.now(timezone.utc) + timedelta(hours=2),
            scheduled_end=datetime.now(timezone.utc) + timedelta(hours=3, minutes=30),
            location="Онлайн (Meet)",
            status="scheduled",
        )
        db.add(meeting)
        await db.flush()
        result = await handle_time_finalized(
            db, meeting.id, "Wed", "19:00", activity=None,
            scheduled_start=meeting.scheduled_start,
        )
        print("RESULT:", result)
        # приглашение уйдёт в лог стаба и (нет responders для poll_id=1) = 0
        assert result["invited"] <= 1
        await db.rollback()
        print("OK")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 6: Прогнать** (Postgres + uvicorn не обязателен)

```powershell
.\venv\Scripts\python scripts\test_eng7_flow.py
.\venv\Scripts\pytest tests\test_eng7_units.py -q
# ожидание: RESULT: {...} (в логах [STUB SEND] не появится — респондеров нет) / OK / PASS
```

- [ ] **Step 7: Commit**

```bash
git add app/services/invites.py app/services/checkin.py app/services/reminders.py app/api/google_chat.py app/main.py scripts/test_eng7_flow.py
git commit -m "feat: ENG-7 интеграция — приглашения, restore, кнопка check-in"
```

---

### Task 9: Стыковка с ENG-6 — heartbeat-джоб и прод/e2e (после мержа Тиммейта B)

> **Внимание:** эта задача выполняется ПОСЛЕ мержа `app/scheduling.py` (ENG-6) в main.
> До этого момента все предшествующие задачи работают и проверены. `advance_state`
> вызывается по замороженной сигнатуре: `advance_state(instance: MeetingInstance) -> MeetingInstance`.

**Files:**
- Create: `app/services/voting.py` (адаптер + heartbeat)
- Modify: `app/scheduler.py` (джоб heartbeat)
- Create: `scripts/test_finalize_flow.py`

**Interfaces:**
- Consumes: `app.scheduling.advance_state` (ENG-6, после мержа), `app.schemas.MeetingInstance`,
  `app.services.invites.handle_time_finalized/handle_escalated`.
- Produces: `build_meeting_instance(db, poll) -> MeetingInstance`, `_heartbeat_tick(db) -> list[str]`.

- [ ] **Step 1: Адаптер + heartbeat `app/services/voting.py`**

```python
# app/services/voting.py
"""Мост БД -> доменная модель MeetingInstance + heartbeat вызов advance_state (ENG-6).

Выполнять после мержа ENG-6 (app/scheduling.py от Тиммейта B).
"""
import logging
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PollSlot, PollVote, Profile, WeeklyPoll
from app.schemas import MeetingInstance, MeetingStatus, Slot

logger = logging.getLogger(__name__)


async def build_meeting_instance(db: AsyncSession, poll: WeeklyPoll) -> MeetingInstance:
    """WeeklyPoll + слоты + голоса -> доменный MeetingInstance (голоса как user_id)."""
    slots = (await db.execute(
        select(PollSlot).where(PollSlot.poll_id == poll.id).order_by(PollSlot.slot_start)
    )).scalars().all()
    slot_ids = [s.id for s in slots]

    votes_rows = (await db.execute(
        select(PollVote.poll_slot_id, Profile.workspace_user_id)
        .join(Profile, Profile.id == PollVote.profile_id)
        .where(PollVote.poll_slot_id.in_(slot_ids))
    )).all()
    votes_by_slot: dict[int, list[str]] = {sid: [] for sid in slot_ids}
    for slot_id, user_id in votes_rows:
        if user_id:
            votes_by_slot[slot_id].append(user_id)

    week_start = datetime.combine(poll.week_start, datetime.min.time(), tzinfo=timezone.utc)
    poll_status = poll.status
    status = MeetingStatus.VOTING if poll_status == "active" else MeetingStatus.TIME_FINALIZED
    if poll.status == "active" and poll.voting_deadline.replace(tzinfo=None) < datetime.now(timezone.utc).replace(tzinfo=None):
        status = MeetingStatus.VOTING  # статус менять будет advance_state

    return MeetingInstance(
        id=str(poll.id),
        week_start=week_start,
        status=status,
        slots=[
            Slot(
                id=str(s.id),
                day=s.slot_start.strftime("%a"),
                time=s.slot_start.strftime("%H:%M"),
                votes=votes_by_slot[s.id],
            )
            for s in slots
        ],
        deadline=poll.voting_deadline,
    )


async def heartbeat_tick(db: AsyncSession) -> list[str]:
    """Вызвать advance_state для всех активных опросов с прошедшим дедлайном."""
    from app.scheduling import advance_state  # после мержа ENG-6

    polls = (await db.execute(
        select(WeeklyPoll).where(WeeklyPoll.status == "active")
    )).scalars().all()
    events = []
    for poll in polls:
        now = datetime.now(timezone.utc)
        deadline = poll.voting_deadline
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        if deadline >= now:
            continue
        instance = await build_meeting_instance(db, poll)
        next_state = advance_state(instance)
        if next_state.status == instance.status:
            continue  # ничего не изменилось
        if next_state.status is MeetingStatus.TIME_FINALIZED:
            poll.status = "closed"
            poll.closed_at = now
            final_slot = next(
                (s for s in instance.slots if s.id == next_state.final_slot_id), None
            )
            logger.info("poll_finalized poll=%s slot=%s", poll.id, next_state.final_slot_id)
            events.append(f"finalized:{poll.id}")
            if final_slot is not None:
                meeting = MeetingORM(
                    poll_id=poll.id,
                    selected_slot_id=int(final_slot.id),
                    scheduled_start=_slot_datetime(instance.week_start, final_slot.day, final_slot.time),
                    location="Google Meet",
                    status="scheduled",
                )
                db.add(meeting)
                await db.flush()
                await invites_handle_time_finalized(db, meeting.id, final_slot.day, final_slot.time, meeting.scheduled_start)
        elif next_state.status is MeetingStatus.ESCALATED:
            poll.status = "closed"
            poll.closed_at = now
            logger.warning("poll_escalated poll=%s", poll.id)
            events.append(f"escalated:{poll.id}")
            meeting = MeetingORM(
                poll_id=poll.id,
                selected_slot_id=None,
                scheduled_start=None,
                location="Google Meet",
                status="escalated",
            )
            db.add(meeting)
            await db.flush()
            await invites_handle_escalated(db, meeting.id)
    await db.commit()
    return events


async def invites_handle_time_finalized(
    db: AsyncSession, instance_id: int, day: str, time: str, scheduled_start: datetime | None,
) -> None:
    """Делегирование в ENG-7 (импорт только здесь, чтобы Task 7-8 мержились без ENG-6)."""
    from app.services.invites import handle_time_finalized

    await handle_time_finalized(db, instance_id, day, time, scheduled_start=scheduled_start)


async def invites_handle_escalated(db: AsyncSession, instance_id: int) -> None:
    from app.services.invites import handle_escalated

    await handle_escalated(db, instance_id)


def _slot_datetime(week_start: date, day: str, time: str) -> datetime:
    """Собрать aware datetime слота: понедельник недели + смещение + время. (вспомогательная)"""
    day_idx = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}[day]
    hh, mm = (int(x) for x in time.split(":"))
    return datetime.combine(week_start, datetime.min.time()) \
        .replace(tzinfo=timezone.utc) + timedelta(days=day_idx, hours=hh, minutes=mm)
```

- [ ] **Step 2: Джоб heartbeat в `app/scheduler.py`**

```python
async def _run_heartbeat() -> None:
    from app.services.voting import heartbeat_tick

    async with AsyncSessionLocal() as db:
        events = await heartbeat_tick(db)
        if events:
            logger.info("heartbeat_events events=%s", events)


# внутри init_scheduler():
scheduler.add_job(_run_heartbeat, "interval", minutes=1, id="heartbeat", replace_existing=True)
```

- [ ] **Step 3: Прогон `scripts/test_finalize_flow.py`**

```python
# scripts/test_finalize_flow.py
"""E2E стыковка: опрос с голосами после дедлайна -> advance_state -> статус меняется.
Запуск ПОСЛЕ мержа ENG-6. .\venv\Scripts\python scripts\test_finalize_flow.py
"""
import asyncio
from datetime import date, datetime, timedelta, timezone

from app.database import AsyncSessionLocal
from app.models import MeetingInstance as MeetingORM, PollResponse, PollSlot, PollVote, Profile, WeeklyPoll
from app.services.onboarding import get_or_create_profile
from app.services.voting import build_meeting_instance, heartbeat_tick


async def main() -> None:
    async with AsyncSessionLocal() as db:
        profile = await get_or_create_profile(db, "users/test_finalize", display_name="T")
        poll = WeeklyPoll(week_start=datetime.now(timezone.utc).date(), voting_deadline=datetime.now(timezone.utc) - timedelta(hours=1), status="active")
        db.add(poll)
        await db.flush()
        slot = PollSlot(poll_id=poll.id, slot_start=datetime.now(timezone.utc) + timedelta(days=1), slot_end=datetime.now(timezone.utc) + timedelta(days=1, hours=1), location="Meet")
        db.add(slot)
        await db.flush()
        db.add(slot)
        await db.flush()
        db.add(PollVote(profile_id=profile.id, poll_slot_id=slot.id))
        await db.commit()

        instance = await build_meeting_instance(db, poll)
        print("slots in instance:", [s.id for s in instance.slots])
        events = await heartbeat_tick(db)
        print("events:", events)
        await db.execute(WeeklyPoll.__table__.delete().where(WeeklyPoll.id == poll.id))
        await db.commit()
        print("OK" if events else "NO_EVENTS (проверь кворум MIN_QUORUM)")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Commit**

```bash
git add app/services/voting.py app/scheduler.py scripts/test_finalize_flow.py
git commit -m "feat: стыковка с ENG-6 — heartbeat вызывает advance_state (после мержа)"
```

---

### Task 10: Финальный E2E и критерии готовности

- [ ] **Step 1: Все юниты зелёные**

```powershell
.\venv\Scripts\pytest tests -q
# ожидание: все pass (включая тесты Тиммейтов, если уже в ветке)
```

- [ ] **Step 2: Проверка критериев из спеки руками**

1. `alembic current` → `0002 (head)`.
2. `.\\venv\\Scripts\\python scripts\\send_poll_now.py` два раза подряд → второй не создаёт
   новый опрос (идемпотентно) и не генерит вопросы повторно.
3. В логах стаба — `[STUB SEND]` каждому активному профилю.
4. `scripts/test_poll_flow.py` → повторный сабмит не дублирует голоса.
5. (после Task 9) `scripts/test_finalize_flow.py` → `events` не пустой и статус опроса закрыт.
6. Если `OPENROUTER_API_KEY` реальный — в `poll_questions` появляются живые вопросы
   (personal_ok=True в RESULT).

- [ ] **Step 3: Коммит итога (по команде Кирилла)**

```bash
git add .
git commit -m "feat: ENG-5 + ENG-7 — итоговая проверка"
```

---

## Чек-лист перед сдачей (`docs/superpowers/specs/2026-08-20-english-5-7-design.md`)

| Критерий спеки | Где в плане |
|---|---|
| Миграция poll_questions + модель | Task 1 |
| Банк + ротация без повторов | Task 2 |
| OpenRouter JSON + фолбэк None | Task 3 |
| Карточка 2 вопроса + чекбоксы слотов | Task 4 |
| Дедлайн min−буфер | Task 4 |
| Сабмит: answers история, голоса upsert, стоп после дедлайна | Task 5 |
| Пакетная генерация заранее (подход Б) | Task 6 |
| Рассылка идемпотентно + APScheduler | Task 6 |
| Приглашения/пост в Space/эскалация/джобы T−1ч/окно check-in | Tasks 7–8 |
| restore jобов при рестарте | Task 8 |
| Стыковка advance_state (после мержа ENG-6) | Task 9 |
| E2E: send now, flow-скрипты, стаб в логах | Tasks 6, 8, 10 |