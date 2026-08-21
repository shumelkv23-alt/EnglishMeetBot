# app/services/onboarding.py
"""Онбординг участников: upsert профиля, сохранение ответов (схема profiles/answers)."""
import logging
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Answer, Profile

logger = logging.getLogger(__name__)

# question_text для свободных ответов на карточку онбординга (7 вопросов)
ONBOARDING_QUESTION = "Онбординг-анкета участника (7 вопросов)"


def current_week_start() -> date:
    """Понедельник текущей недели (answers.week_start)."""
    today = date.today()
    return today - timedelta(days=today.weekday())


async def get_or_create_profile(
    db: AsyncSession,
    workspace_user_id: str,
    email: str | None = None,
    display_name: str | None = None,
    chat_space_id: str | None = None,
) -> Profile:
    """Получить профиль по workspace_user_id или создать новый."""
    profile = (
        await db.execute(
            select(Profile).where(Profile.workspace_user_id == workspace_user_id)
        )
    ).scalar_one_or_none()
    if profile is None:
        # user_email NOT NULL по спеке; если в событии email не пришёл,
        # ставим плейсхолдер — заменится реальным в следующем событии.
        profile = Profile(
            workspace_user_id=workspace_user_id,
            user_email=email or f"{workspace_user_id.replace('/', '_')}@placeholder.local",
            user_name=display_name,
            chat_space_id=chat_space_id,
        )
        db.add(profile)
        logger.info("profile_created workspace_user_id=%s", workspace_user_id)
    else:
        # Обновляем актуальные данные из события
        if email and email != profile.user_email:
            profile.user_email = email
        if display_name and display_name != profile.user_name:
            profile.user_name = display_name
        if chat_space_id and chat_space_id != profile.chat_space_id:
            profile.chat_space_id = chat_space_id
    await db.commit()
    await db.refresh(profile)
    return profile


async def save_answer(
    db: AsyncSession,
    profile: Profile,
    question_text: str,
    answer_text: str,
) -> Answer:
    """Сохранить ответ (append-only история)."""
    answer = Answer(
        profile_id=profile.id,
        question_text=question_text,
        answer_text=answer_text,
        week_start=current_week_start(),
    )
    db.add(answer)
    await db.commit()
    await db.refresh(answer)
    logger.info("answer_saved profile_id=%s len=%d", profile.id, len(answer_text))
    return answer


async def mark_onboarded(db: AsyncSession, profile: Profile) -> None:
    """Отметить онбординг пройденным."""
    if not profile.onboarding_completed:
        profile.onboarding_completed = True
        await db.commit()
        logger.info("profile_onboarded workspace_user_id=%s", profile.workspace_user_id)
