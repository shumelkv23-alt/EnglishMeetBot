"""Брифинг встречи: сбор ответов участников, генерация и отправка в группу за час.

Кто придёт = профили, проголосовавшие за выбранный слот встречи (PollVote по
selected_slot_id). Их ответы на вопросы недели (таблица answers за последние 7
дней, без анкеты онбординга) скармливаются LLM, который возвращает тему +
2 дискуссионных утверждения + свежие новости на английском. За час до встречи
(config['briefing_lead_minutes'], по умолчанию 60) карточка уходит в общую
группу (config['space_id']).

Джобы: schedule_briefing_for_meeting() ставит задачу при финализации опроса;
restore_briefings_on_startup() пересоздаёт их для будущих встреч после рестарта.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import Answer, Config, MeetingInstance, PollVote, Profile
from app.services.briefing.generator import generate_briefing
from app.services.chat_sender import send_message
from app.services.onboarding import ONBOARDING_QUESTION
from app.services.onboarding_answers import QUESTIONS as ONBOARDING_QUESTIONS

logger = logging.getLogger(__name__)

# Ответы на анкету онбординга не считаем «ответами на вопросы недели».
_EXCLUDED_QUESTIONS = frozenset([ONBOARDING_QUESTION, *ONBOARDING_QUESTIONS.values()])

DEFAULT_LEAD_MINUTES = 60
_RECENT_DAYS = 7
_MAX_CONTEXT_CHARS = 8000
_MAX_ANSWER_CHARS = 500


def briefing_at(scheduled_start: datetime, lead_minutes: int) -> datetime:
    """Момент отправки брифинга = встреча минус lead_minutes."""
    return scheduled_start - timedelta(minutes=lead_minutes)


def briefing_job_id(instance_id: str) -> str:
    """id джоба: перезапись при повторной постановке, не дубль."""
    return f"briefing_{instance_id}"


# Иконка в шапке карточки (материал-иконка Google; путь проверен в onboarding-карточке).
_HEADER_ICON_URL = "https://fonts.gstatic.com/s/i/googlematerialicons/spark/v1/24px.svg"

def build_briefing_card(briefing: dict, scheduled_start: datetime | None = None) -> dict:
    """Карточка брифинга: тема, тезисы, фразы и новости. Содержимое — на английском."""
    topic = str(briefing.get("topic") or "Conversation").strip()
    statements = [str(s).strip() for s in (briefing.get("statements") or []) if str(s).strip()]
    phrases = [str(p).strip() for p in (briefing.get("phrases") or []) if str(p).strip()]
    news = [str(n).strip() for n in (briefing.get("news") or []) if str(n).strip()]

    subtitle = ""
    if scheduled_start is not None:
        tz = ZoneInfo(get_settings().app_timezone)
        if scheduled_start.tzinfo is None:
            scheduled_start = scheduled_start.replace(tzinfo=tz)
        subtitle = "See you at " + scheduled_start.astimezone(tz).strftime("%a %H:%M")

    header: dict = {
        "title": "Meeting brief",
        "imageUrl": _HEADER_ICON_URL,
        "imageType": "CIRCLE",
        "imageAltText": "Meeting brief",
    }
    if subtitle:
        header["subtitle"] = subtitle

    sections = [
        {
            "header": "🎯 Topic",
            "widgets": [
                {"decoratedText": {"topLabel": "Today's theme", "text": topic, "wrapText": True}},
            ],
        },
    ]

    if statements:
        sections.append({
            "header": "💬 Discussion statements",
            "widgets": [
                {"decoratedText": {"topLabel": f"Statement {i}", "text": s, "wrapText": True}}
                for i, s in enumerate(statements, 1)
            ],
        })

    if phrases:
        sections.append({
            "header": "💡 Useful phrases",
            "widgets": [
                {"decoratedText": {"text": f"💬 {p}", "wrapText": True}}
                for p in phrases
            ],
        })

    if news:
        sections.append({
            "header": "📰 In the news",
            "widgets": [
                {"decoratedText": {"text": f"📌 {n}", "wrapText": True}}
                for n in news
            ],
        })

    sections.append({
        "widgets": [
            {"divider": {}},
            {"textParagraph": {"text": "Have a great conversation! 🚀"}},
        ],
    })

    return {
        "cardsV2": [{
            "cardId": "meetingBriefing",
            "card": {"header": header, "sections": sections},
        }]
    }


async def _config_value(db: AsyncSession, key: str, default=None):
    cfg = (await db.execute(select(Config).where(Config.key == key))).scalar_one_or_none()
    return cfg.value if cfg is not None else default


async def _attendee_profiles(db: AsyncSession, meeting: MeetingInstance) -> list[Profile]:
    """Профили, проголосовавшие за выбранный слот встречи."""
    rows = (
        await db.execute(
            select(Profile)
            .join(PollVote, PollVote.profile_id == Profile.id)
            .where(PollVote.poll_slot_id == meeting.selected_slot_id)
        )
    ).scalars().all()
    return list(rows)


async def _recent_answers(
    db: AsyncSession, profile_ids: list[int], within_days: int = _RECENT_DAYS
) -> list[Answer]:
    """Публичные (с согласия) ответы на вопросы недели за последние N дней (без анкеты онбординга)."""
    if not profile_ids:
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=within_days)
    rows = (
        await db.execute(
            select(Answer).where(
                Answer.profile_id.in_(profile_ids),
                Answer.is_public.is_(True),
                Answer.answered_at >= cutoff,
                Answer.answer_text.isnot(None),
                Answer.question_text.isnot(None),
                Answer.question_text.notin_(_EXCLUDED_QUESTIONS),
            )
            .order_by(Answer.profile_id, Answer.answered_at)
        )
    ).scalars().all()
    return list(rows)


def _build_context(profiles_by_id: dict[int, Profile], answers: list[Answer]) -> str:
    """Строковый контекст участников для LLM: «Имя (уровень): ответ».

    При анонимизации имя не раскрываем во внешний LLM (согласие q6);
    контекст ограничен по длине, чтобы не выйти за окно модели.
    """
    lines: list[str] = []
    total = 0
    for idx, a in enumerate(answers, 1):
        p = profiles_by_id.get(a.profile_id)
        if p is None:
            continue
        if p.anonymize_answers:
            name = f"participant {idx}"
        else:
            name = p.user_name or f"participant {idx}"
        level = f" ({p.english_level})" if p.english_level else ""
        text = (a.answer_text or "").strip()[:_MAX_ANSWER_CHARS]
        line = f"{name}{level}: {text}"
        if total + len(line) > _MAX_CONTEXT_CHARS:
            break
        lines.append(line)
        total += len(line)
    return "\n".join(lines) or "no participant answers"


async def send_briefing(instance_id: str) -> None:
    """Джоб: сгенерировать и отправить брифинг в группу (за час до встречи)."""
    async with AsyncSessionLocal() as db:
        meeting = await db.get(MeetingInstance, int(instance_id))
        if meeting is None:
            logger.warning("briefing_no_meeting instance=%s", instance_id)
            return
        if meeting.status != "scheduled":
            logger.info(
                "briefing_skipped_status instance=%s status=%s", instance_id, meeting.status
            )
            return

        space_id = await _config_value(db, "space_id", "") or ""
        if not space_id:
            logger.warning("briefing_no_space instance=%s", instance_id)
            return

        profiles = await _attendee_profiles(db, meeting)
        answers = await _recent_answers(db, [p.id for p in profiles])
        context = _build_context({p.id: p for p in profiles}, answers)
        briefing = await generate_briefing(context)
        card = build_briefing_card(briefing, meeting.scheduled_start)

        await asyncio.to_thread(
            send_message,
            space_id,
            text="📚 Today's meeting brief — topic, discussion points and news:",
            cards_v2=card["cardsV2"],
        )
        logger.info(
            "briefing_sent instance=%s attendees=%s answers=%s",
            instance_id, len(profiles), len(answers),
        )


async def schedule_briefing_for_meeting(
    db: AsyncSession, instance_id: int, scheduled_start: datetime
) -> None:
    """Поставить джоб брифинга на запланированное время встречи (при финализации)."""
    from app.scheduler import scheduler

    if scheduler is None or scheduled_start is None:
        return
    lead = int(await _config_value(db, "briefing_lead_minutes", DEFAULT_LEAD_MINUTES) or DEFAULT_LEAD_MINUTES)
    run_at = briefing_at(scheduled_start, lead)
    scheduler.add_job(
        send_briefing,
        "date",
        run_date=run_at,
        id=briefing_job_id(str(instance_id)),
        replace_existing=True,
        # Если уже опаздываем (встреча раньше, чем через lead минут) — отправить сразу,
        # а не потерять из-за misfire.
        misfire_grace_time=lead * 60,
        args=[str(instance_id)],
    )
    logger.info("briefing_scheduled instance=%s at=%s", instance_id, run_at)


async def restore_briefings_on_startup() -> int:
    """Пересоздать джобы брифинга для будущих встреч после рестарта приложения."""
    from app.scheduler import scheduler

    if scheduler is None:
        return 0
    async with AsyncSessionLocal() as db:
        meetings = (
            await db.execute(
                select(MeetingInstance).where(
                    MeetingInstance.status == "scheduled",
                    MeetingInstance.scheduled_start.isnot(None),
                )
            )
        ).scalars().all()
        lead = int(await _config_value(db, "briefing_lead_minutes", DEFAULT_LEAD_MINUTES) or DEFAULT_LEAD_MINUTES)

    now = datetime.now(timezone.utc)
    restored = 0
    for m in meetings:
        run_at = briefing_at(m.scheduled_start, lead)
        if run_at > now:
            scheduler.add_job(
                send_briefing,
                "date",
                run_date=run_at,
                id=briefing_job_id(str(m.id)),
                replace_existing=True,
                args=[str(m.id)],
            )
            restored += 1
    logger.info("briefings_restored count=%s", restored)
    return restored
