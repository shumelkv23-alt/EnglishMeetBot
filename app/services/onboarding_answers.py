# app/services/onboarding_answers.py
"""Парсинг и сохранение ответов интерактивной анкеты онбординга."""
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Answer, Profile
from app.services.form_parsing import parse_form_inputs
from app.services.onboarding import current_week_start, mark_onboarded

logger = logging.getLogger(__name__)

# Мета-описание вопросов: имя поля формы -> человекочитаемый текст
QUESTIONS = {
    "q1": "1. What could you talk about for hours?",
    "q2": "2. What meeting vibe suits you best?",
    "q3": "3. Name ONE topic you're ready to discuss right now",
    "q4": "4. Which days can you spare 30–40 minutes?",
    "q5": "5. Why do you usually lose interest or miss activities?",
    "q6": "6. May we use your answers?",
    "q7": "7. Which communication style do you prefer?",
}

# Вопросы, у которых есть поле «Свой вариант»
OTHER_FIELDS = {
    "q1": "q1_other",
    "q2": "q2_other",
    "q4": "q4_other",
    "q5": "q5_other",
}


def _get_values(form_inputs: dict, name: str) -> list[str]:
    """Все значения поля формы (чекбоксы вернут список, радио — один элемент).

    Принимает оба формата:
    классический {name: {"stringInputs": {...}}} и
    add-on       {name: {"": {"stringInputs": {...}}}}.
    """
    return parse_form_inputs(form_inputs).get(name, [])


def _get_single(form_inputs: dict, name: str) -> str:
    """Первое значение поля формы (для радио и текстовых инпутов)."""
    values = _get_values(form_inputs, name)
    return values[0] if values else ""


def parse_onboarding_form(form_inputs: dict) -> list[dict]:
    """Превратить raw formInputs из CARD_CLICKED в список ответов.

    Каждый элемент: {"question": str, "choice": str, "text": str}.
    choice — выбранные варианты через запятую.
    text — либо свободный ответ (q3), либо поле «Свой вариант».
    """
    parsed = []
    for key, question_text in QUESTIONS.items():
        selected = _get_values(form_inputs, key)
        choice = ", ".join(selected)

        text = ""
        if key == "q3":
            text = _get_single(form_inputs, key)
        elif key in OTHER_FIELDS:
            text = _get_single(form_inputs, OTHER_FIELDS[key])

        parsed.append({
            "question": question_text,
            "choice": choice,
            "text": text,
        })
    return parsed


def _apply_consent(profile: Profile, consent_value: str) -> None:
    """Обновить флаги согласия на основе ответа q6."""
    if consent_value == "yes":
        profile.public_consent = True
        profile.anonymize_answers = False
    elif consent_value == "anonymous":
        profile.public_consent = True
        profile.anonymize_answers = True
    else:  # "no" или пусто
        profile.public_consent = False
        profile.anonymize_answers = True


async def update_profile_from_onboarding(
    db: AsyncSession, profile: Profile, parsed: list[dict]
) -> None:
    """Обновить денормализованные поля профиля из ответов анкеты."""
    by_question = {item["question"]: item for item in parsed}

    # q1 -> interests
    q1 = by_question.get(QUESTIONS["q1"], {})
    interests = []
    if q1.get("choice"):
        interests.extend([v.strip() for v in q1["choice"].split(",") if v.strip()])
    if q1.get("text"):
        interests.append(q1["text"].strip())
    if interests:
        profile.interests = interests

    # q4 -> preferred_days
    q4 = by_question.get(QUESTIONS["q4"], {})
    days = []
    if q4.get("choice"):
        days.extend([v.strip() for v in q4["choice"].split(",") if v.strip()])
    if q4.get("text"):
        days.append(q4["text"].strip())
    if days:
        profile.preferred_days = days

    # q6 -> public_consent / anonymize_answers
    q6_value = by_question.get(QUESTIONS["q6"], {}).get("choice", "")
    _apply_consent(profile, q6_value)

    # Сохраняем всю анкету как JSON для быстрого доступа
    profile.onboarding_answers = {
        item["question"]: {"choice": item["choice"], "text": item["text"]}
        for item in parsed
    }

    # Коммит НЕ здесь: вызывающий (save_onboarding_answers) делает один commit
    # после добавления всех Answer, иначе ответы остаются без коммита и
    # откатываются при закрытии сессии.


async def save_onboarding_answers(
    db: AsyncSession, profile: Profile, form_inputs: dict
) -> list[Answer]:
    """Сохранить ответы анкеты в таблицу answers + обновить профиль.

    answers — история: каждое прохождение анкеты добавляет новый батч
    записей (отличие — по answered_at/week_start).
    profiles — актуальная версия: поля обновляет update_profile_from_onboarding.

    Возвращает список созданных Answer.
    """
    parsed = parse_onboarding_form(form_inputs)

    # Сначала обновляем профиль (согласие, interests, days, JSON анкеты),
    # чтобы answer.is_public брался из актуального public_consent.
    await update_profile_from_onboarding(db, profile, parsed)

    week_start = current_week_start()
    answers = []

    for item in parsed:
        # Если и choice, и text пустые — пропускаем (вопрос не отвечен)
        if not item["choice"] and not item["text"]:
            continue

        answer = Answer(
            profile_id=profile.id,
            question_text=item["question"],
            answer_text=item["text"] or None,
            answer_choice=item["choice"] or None,
            is_public=profile.public_consent,
            week_start=week_start,
        )
        db.add(answer)
        answers.append(answer)

    await db.flush()
    await mark_onboarded(db, profile)
    await db.commit()
    logger.info("onboarding_answers_saved profile_id=%s count=%s", profile.id, len(answers))
    return answers
