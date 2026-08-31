"""Оркестрация пайплайна карточек (ТЗ §6.1) + рендер + планирование джобов.

Пайплайн: собрать контекст → ротация типа → сложность → контент (шаблон/LLM)
→ подбор активности → валидация → сохранение → рендер → отправка в группу.
"""
import asyncio
import html
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cards.activity_matcher import game_by_id, match_activity
from app.cards.catalog import BANK_ONLY_TYPES
from app.cards.generator.llm import generate_llm_content
from app.cards.generator.template import build_template_content, pick_bank_payload
from app.cards.models import Card, CardType
from app.cards.quality import check_generated_card_quality
from app.cards.rotation import select_card_type
from app.cards.validator import validate_card
from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import Answer, Config, MeetingInstance, PollVote, Profile
from app.services.chat_sender import send_message
from app.services.onboarding import ONBOARDING_QUESTION
from app.services.onboarding_answers import QUESTIONS as ONBOARDING_QUESTIONS

logger = logging.getLogger(__name__)

_EXCLUDED_QUESTIONS = frozenset([ONBOARDING_QUESTION, *ONBOARDING_QUESTIONS.values()])
_RECENT_DAYS = 7
_MAX_CONTEXT_ANSWERS = 12
_MAX_CONTEXT_TEXT = 280
DEFAULT_LEAD_MINUTES = 60

CEFR_ORDER = {"A1": 0, "A2": 1, "B1": 2, "B2": 3, "C1": 4, "C2": 5}

TYPE_TITLES = {
    "topic": "Topic Discussion",
    "debate": "Debate",
    "storytelling": "Storytelling Chain",
    "would_you_rather": "Would You Rather",
    "roleplay": "Roleplay",
    "culture": "Culture & Idiom",
    "hot_seat": "Hot Seat",
    "game_day": "Game Day",
    "two_truths": "Two Truths & a Lie",
    "mystery": "Mystery Topic",
    "news_reaction": "News Reaction",
    "time_capsule": "Time Capsule",
}

_HEADER_ICON_URL = "https://fonts.gstatic.com/s/i/googlematerialicons/spark/v1/24px.svg"


def card_at(scheduled_start: datetime, lead_minutes: int) -> datetime:
    """Момент отправки карточки = встреча минус lead_minutes."""
    return scheduled_start - timedelta(minutes=lead_minutes)


def card_job_id(instance_id: str) -> str:
    """id джоба карточки (перезапись при повторной постановке)."""
    return f"card_{instance_id}"


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


async def _recent_answers(db: AsyncSession, profile_ids: list[int]) -> list[Answer]:
    """Публичные (с согласия) ответы на вопросы недели за последние 7 дней."""
    if not profile_ids:
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=_RECENT_DAYS)
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


def _clean_context_text(value: str | None, limit: int = _MAX_CONTEXT_TEXT) -> str:
    text = " ".join(str(value or "").split())
    text = html.escape(text, quote=False)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def _build_context(profiles: list[Profile], answers: list[Answer]) -> str:
    """Анонимный и ограниченный контекст участников для LLM."""
    aliases = {p.id: f"Participant {i}" for i, p in enumerate(profiles, 1)}
    lines: list[str] = []

    profile_lines: list[str] = []
    for p in profiles:
        parts: list[str] = []
        if p.english_level:
            parts.append(f"level {p.english_level}")
        interests = [_clean_context_text(item, 60) for item in (p.interests or []) if str(item or "").strip()]
        if interests:
            parts.append("interests: " + ", ".join(interests[:5]))
        if parts:
            profile_lines.append(f"{aliases.get(p.id, 'Participant')}: " + "; ".join(parts))
    if profile_lines:
        lines.append("Group profile:")
        lines.extend(profile_lines[:8])

    answer_lines: list[str] = []
    for a in answers[:_MAX_CONTEXT_ANSWERS]:
        alias = aliases.get(a.profile_id)
        if not alias:
            continue
        question = _clean_context_text(a.question_text)
        answer = _clean_context_text(a.answer_text)
        if answer:
            answer_lines.append(f"{alias} answered: Q: {question} A: {answer}")
    if answer_lines:
        lines.append("Recent public answers:")
        lines.extend(answer_lines)

    return "\n".join(lines) or "no participant answers"


def _source_answer_texts(answers: list[Answer]) -> list[str]:
    return [str(a.answer_text or "").strip() for a in answers if str(a.answer_text or "").strip()]


async def _active_card_types(db: AsyncSession) -> list[CardType]:
    rows = (
        await db.execute(select(CardType).where(CardType.is_active.is_(True)))
    ).scalars().all()
    return list(rows)


async def _history(db: AsyncSession, space_id: str) -> list[tuple[str, datetime]]:
    """История (card_type_name, created_at) для ротации."""
    rows = (
        await db.execute(
            select(CardType.name, Card.created_at)
            .join(Card, Card.card_type_id == CardType.id)
            .where(Card.space_id == space_id)
            .order_by(Card.created_at)
        )
    ).all()
    return [(name, ts) for name, ts in rows]


async def _recent_topics(db: AsyncSession, space_id: str, limit: int = 20) -> list[str]:
    """Темы последних карточек space — LLM просят их не повторять."""
    rows = (
        await db.execute(
            select(Card.content)
            .where(Card.space_id == space_id)
            .order_by(Card.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    topics = []
    for content in rows:
        topic = str(((content or {}).get("main_content") or {}).get("topic") or "").strip()
        if topic:
            topics.append(topic)
    return topics


def _group_difficulty(profiles: list[Profile], card_type: CardType) -> str:
    """Уровень группы = минимальный CEFR участников, клампится в диапазон типа."""
    levels = [p.english_level for p in profiles if p.english_level in CEFR_ORDER]
    if not levels:
        return card_type.cefr_min or "A2"
    level = min(levels, key=CEFR_ORDER.get)
    if CEFR_ORDER[level] < CEFR_ORDER.get(card_type.cefr_min, "A2"):
        return card_type.cefr_min
    if CEFR_ORDER[level] > CEFR_ORDER.get(card_type.cefr_max, "C1"):
        return card_type.cefr_max
    return level


def _lowest_group_level(profiles: list[Profile]) -> str | None:
    levels = [p.english_level for p in profiles if p.english_level in CEFR_ORDER]
    return min(levels, key=CEFR_ORDER.get) if levels else None


def _eligible_card_types(card_types: list[CardType], profiles: list[Profile]) -> list[CardType]:
    group_size = len(profiles) or 2
    level = _lowest_group_level(profiles)
    eligible: list[CardType] = []
    for card_type in card_types:
        min_size = int(getattr(card_type, "min_group_size", 2) or 2)
        max_size = getattr(card_type, "max_group_size", None)
        if group_size < min_size:
            continue
        if max_size is not None and group_size > int(max_size):
            continue
        if level:
            low = CEFR_ORDER.get(getattr(card_type, "cefr_min", "A2"), 0)
            high = CEFR_ORDER.get(getattr(card_type, "cefr_max", "C1"), 5)
            if not (low <= CEFR_ORDER[level] <= high):
                continue
        eligible.append(card_type)
    return eligible or card_types


def _activity_from_id(activity_id: str | None, reason: str) -> dict | None:
    game = game_by_id(activity_id or "")
    if not game:
        return None
    return {
        "activity_id": game["activity_id"],
        "activity_type": game["activity_type"],
        "relevance_reason": reason,
    }


def _assemble_card(
    card_type: CardType,
    difficulty: str,
    content: dict,
    generated_by: str,
    generation_meta: dict | None = None,
) -> dict:
    """Собрать полный card_content из контента + suggested_activity."""
    topic = content["main_content"].get("topic", "")
    suggested = None
    if card_type.name == "game_day":
        aid = (content["main_content"].get("type_specific_payload") or {}).get("activity_id")
        suggested = _activity_from_id(aid, "the game is the center of this card")
    if suggested is None:
        suggested = _activity_from_id(content.get("suggested_activity_id"), "suggested by the card LLM")
    if suggested is None:
        suggested = match_activity(topic)
    meta = {
        "generated_by": generated_by,
        "safety_tier": card_type.safety_tier,
        "rotation_tag": card_type.name,
    }
    if generation_meta:
        meta["llm"] = generation_meta
    return {
        "card_type": card_type.name,
        "difficulty_level": difficulty,
        "warm_up": content.get("warm_up"),
        "main_content": content["main_content"],
        "vocab_box": content.get("vocab_box", []),
        "suggested_activity": suggested,
        "stretch_challenge": content.get("stretch_challenge"),
        "wrap_up_question": content.get("wrap_up_question"),
        "meta": meta,
    }


async def generate_card_content(
    db: AsyncSession, meeting: MeetingInstance, space_id: str,
    theme_override: str | None = None,
) -> tuple[CardType, dict]:
    """Полный пайплайн генерации карточки. Возвращает (тип, content-словарь)."""
    profiles = await _attendee_profiles(db, meeting)
    answers = await _recent_answers(db, [p.id for p in profiles])
    context = _build_context(profiles, answers)

    active_types = await _active_card_types(db)
    card_type = select_card_type(_eligible_card_types(active_types, profiles), await _history(db, space_id))
    if card_type is None:
        raise RuntimeError("no active card types")

    difficulty = _group_difficulty(profiles, card_type)

    from app.services.week_theme import week_theme
    from app.services.weekly_poll import week_monday

    theme = theme_override or week_theme(week_monday(meeting.scheduled_start.date()))

    bank_payload = await pick_bank_payload(db, card_type.id)
    content = build_template_content(card_type.name, bank_payload, difficulty)
    generated_by = "template"
    generation_meta = None
    recent_topics = await _recent_topics(db, space_id)
    source_answers = _source_answer_texts(answers)

    llm = await generate_llm_content(
        card_type.name,
        difficulty,
        context,
        theme=theme,
        recent_topics=recent_topics,
        bank_payload=bank_payload,
        group_size=len(profiles),
        source_answers=source_answers,
    )
    if llm:
        generation_meta = llm.pop("_generation_meta", None)
        content = llm
        generated_by = "llm_grounded" if card_type.name in BANK_ONLY_TYPES else "llm"

    card_content = _assemble_card(card_type, difficulty, content, generated_by, generation_meta)

    errors = validate_card(card_content)
    if generated_by.startswith("llm"):
        errors.extend(check_generated_card_quality(card_content, recent_topics, source_answers))
    if errors:
        # Не прошло валидацию — откатываемся на чистый шаблон (LLM-контент не должен протечь).
        logger.warning("card_validation_failed type=%s errors=%s", card_type.name, errors)
        content = build_template_content(card_type.name, bank_payload, difficulty)
        card_content = _assemble_card(card_type, difficulty, content, "template")

    db.add(Card(
        space_id=space_id,
        meeting_id=meeting.id,
        card_type_id=card_type.id,
        difficulty_level=difficulty,
        content=card_content,
        generated_by=card_content["meta"]["generated_by"],
    ))
    await db.commit()
    logger.info(
        "card_generated meeting=%s type=%s generated_by=%s",
        meeting.id, card_type.name, card_content["meta"]["generated_by"],
    )
    return card_type, card_content


async def regenerate_card_for_topic(
    db: AsyncSession, meeting: MeetingInstance, space_id: str, new_topic: str
) -> None:
    """Перегенерировать карточку занятия под новую тему и разослать (проактивно).

    Отправляет карточку в группу + обновлённую лексику в личку участникам.
    Новый Card сохраняется в историю — запрос «topic» потом покажет новую тему.
    """
    _, content = await generate_card_content(db, meeting, space_id, theme_override=new_topic)

    topic = str((content.get("main_content") or {}).get("topic") or new_topic)
    card = build_card_message(content, meeting.scheduled_start)

    from app.services.chat_sender import send_message as send_space_message

    await asyncio.to_thread(
        send_space_message, space_id, text=f"📚 New topic: {topic}", cards_v2=card["cardsV2"]
    )

    # Обновлённую лексику шлём в личку тем, кто на этой встрече.
    from app.services.vocab import send_vocab_dms

    profiles = await _attendee_profiles(db, meeting)
    await send_vocab_dms(db, meeting, topic, profiles)


def build_card_message(content: dict, scheduled_start: datetime | None = None) -> dict:
    """Рендер карточки в формат Google Chat (cardsV2)."""
    topic = str((content.get("main_content") or {}).get("topic") or "Conversation").strip()
    card_type = content.get("card_type", "topic")

    subtitle = ""
    if scheduled_start is not None:
        tz = ZoneInfo(get_settings().app_timezone)
        if scheduled_start.tzinfo is None:
            scheduled_start = scheduled_start.replace(tzinfo=tz)
        subtitle = "See you at " + scheduled_start.astimezone(tz).strftime("%a %H:%M")

    header: dict = {
        "title": f"{TYPE_TITLES.get(card_type, 'Activity')} · {topic}",
        "imageUrl": _HEADER_ICON_URL,
        "imageType": "CIRCLE",
        "imageAltText": TYPE_TITLES.get(card_type, "Activity"),
    }
    if subtitle:
        header["subtitle"] = subtitle

    sections: list[dict] = []

    warm = content.get("warm_up") or {}
    if warm.get("question"):
        sections.append({
            "header": "🔥 Warm-up (~5 min)",
            "widgets": [{"decoratedText": {"text": warm["question"], "wrapText": True}}],
        })

    main = content.get("main_content") or {}
    sections.extend(_main_sections(main))

    vocab = content.get("vocab_box") or []
    if vocab:
        sections.append({
            "header": "💡 Useful phrases",
            "widgets": [
                {"decoratedText": {"topLabel": v.get("phrase", ""),
                                   "text": v.get("example") or v.get("translation") or "", "wrapText": True}}
                for v in vocab
            ],
        })

    suggested = content.get("suggested_activity") or {}
    if suggested.get("activity_id"):
        name = suggested["activity_id"].replace("_", " ").title()
        sections.append({
            "header": "🎮 Suggested activity",
            "widgets": [{"decoratedText": {"text": name, "wrapText": True}}],
        })

    stretch = content.get("stretch_challenge")
    if stretch:
        sections.append({
            "header": "🚀 Stretch (~10 min)",
            "widgets": [{"decoratedText": {"text": stretch, "wrapText": True}}],
        })

    wrap = content.get("wrap_up_question")
    if wrap:
        sections.append({
            "header": "🧭 Wrap-up (~5 min)",
            "widgets": [{"decoratedText": {"text": wrap, "wrapText": True}}],
        })

    sections.append({"widgets": [{"divider": {}}, {"textParagraph": {"text": "Have a great conversation! 🚀"}}]})

    return {
        "cardsV2": [{
            "cardId": "activityCard",
            "card": {"header": header, "sections": sections},
        }]
    }


def _main_sections(main: dict) -> list[dict]:
    """Секции основного контента в зависимости от type_specific_payload."""
    sections: list[dict] = []
    payload = main.get("type_specific_payload") or {}

    if payload.get("option_a") and payload.get("option_b"):
        sections.append({
            "header": "A or B?",
            "widgets": [
                {"decoratedText": {"topLabel": "A", "text": payload["option_a"], "wrapText": True}},
                {"decoratedText": {"topLabel": "B", "text": payload["option_b"], "wrapText": True}},
            ],
        })
    if payload.get("scenario"):
        roles = payload.get("roles")
        roles = ", ".join(roles) if isinstance(roles, list) else (roles or "two roles")
        sections.append({
            "header": "🎭 Scenario",
            "widgets": [
                {"decoratedText": {"text": payload["scenario"], "wrapText": True}},
                {"decoratedText": {"topLabel": "Roles", "text": roles, "wrapText": True}},
            ],
        })
    if payload.get("statement"):
        sides = payload.get("sides")
        sides = " vs ".join(sides) if isinstance(sides, list) else (sides or "For / Against")
        sections.append({
            "header": "⚖️ Statement",
            "widgets": [
                {"decoratedText": {"text": payload["statement"], "wrapText": True}},
                {"decoratedText": {"topLabel": "Sides", "text": sides, "wrapText": True}},
            ],
        })
    if payload.get("headline"):
        summary = payload.get("summary") or ""
        sections.append({
            "header": "📰 In the news",
            "widgets": [
                {"decoratedText": {"topLabel": "Headline", "text": payload["headline"], "wrapText": True}},
                {"decoratedText": {"text": summary, "wrapText": True}},
            ],
        })
    if payload.get("starter_sentence"):
        sections.append({
            "header": "📖 Story starter",
            "widgets": [{"decoratedText": {"text": payload["starter_sentence"], "wrapText": True}}],
        })
    if payload.get("idiom"):
        sections.append({
            "header": "🗣️ Idiom",
            "widgets": [
                {"decoratedText": {"topLabel": "Expression", "text": payload["idiom"], "wrapText": True}},
                {"decoratedText": {"topLabel": "Meaning", "text": payload.get("meaning", ""), "wrapText": True}},
                {"decoratedText": {"text": f"“{payload.get('example', '')}”", "wrapText": True}},
            ],
        })
    if payload.get("prompt"):
        sections.append({
            "header": "⏳ Prompt",
            "widgets": [{"decoratedText": {"text": payload["prompt"], "wrapText": True}}],
        })

    sub = main.get("sub_questions") or []
    if sub:
        sections.append({
            "header": "💬 Questions",
            "widgets": [
                {"decoratedText": {"topLabel": f"{i}. {q.get('level', '')}".strip(" ."),
                                   "text": q.get("text", ""), "wrapText": True}}
                for i, q in enumerate(sub, 1)
            ],
        })
    return sections


async def send_card(instance_id: str) -> None:
    """Джоб: сгенерировать и отправить карточку занятия в группу."""
    async with AsyncSessionLocal() as db:
        meeting = await db.get(MeetingInstance, int(instance_id))
        if meeting is None:
            logger.warning("card_no_meeting instance=%s", instance_id)
            return
        if meeting.status != "scheduled":
            logger.info("card_skipped_status instance=%s status=%s", instance_id, meeting.status)
            return
        existing = (
            await db.execute(select(Card).where(Card.meeting_id == meeting.id))
        ).scalars().first()
        if existing is not None:
            logger.info("card_skip_exists instance=%s", instance_id)
            return
        space_id = await _config_value(db, "space_id", "") or ""
        if not space_id:
            logger.warning("card_no_space instance=%s", instance_id)
            return

        card_type, content = await generate_card_content(db, meeting, space_id)
        card = build_card_message(content, meeting.scheduled_start)
        await asyncio.to_thread(
            send_message,
            space_id,
            text=f"📚 Today's activity — {TYPE_TITLES.get(card_type.name, 'Activity')}:",
            cards_v2=card["cardsV2"],
        )
        logger.info("card_sent instance=%s type=%s", instance_id, card_type.name)

        # Персональная лексика в личку участникам (по уровню).
        from app.services.vocab import send_vocab_dms

        profiles = await _attendee_profiles(db, meeting)
        topic = str((content.get("main_content") or {}).get("topic") or "today's topic")
        await send_vocab_dms(db, meeting, topic, profiles)


async def schedule_card_for_meeting(
    db: AsyncSession, instance_id: int, scheduled_start: datetime
) -> None:
    """Поставить джоб карточки на время встречи (при финализации)."""
    from app.scheduler import scheduler

    if scheduler is None or scheduled_start is None:
        return
    lead = int(await _config_value(db, "card_lead_minutes", DEFAULT_LEAD_MINUTES) or DEFAULT_LEAD_MINUTES)
    run_at = card_at(scheduled_start, lead)
    scheduler.add_job(
        send_card,
        "date",
        run_date=run_at,
        id=card_job_id(str(instance_id)),
        replace_existing=True,
        misfire_grace_time=lead * 60,
        args=[str(instance_id)],
    )
    logger.info("card_scheduled instance=%s at=%s", instance_id, run_at)


async def restore_cards_on_startup() -> int:
    """Пересоздать джобы карточек для будущих встреч после рестарта."""
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
        lead = int(await _config_value(db, "card_lead_minutes", DEFAULT_LEAD_MINUTES) or DEFAULT_LEAD_MINUTES)

    now = datetime.now(timezone.utc)
    restored = 0
    for m in meetings:
        if m.scheduled_start <= now:
            continue  # встреча уже прошла
        run_at = card_at(m.scheduled_start, lead)
        if run_at <= now:
            run_at = now + timedelta(seconds=10)  # карточка должна была уйти — шлём сразу
        scheduler.add_job(
            send_card, "date", run_date=run_at,
            id=card_job_id(str(m.id)), replace_existing=True,
            args=[str(m.id)],
        )
        restored += 1
    logger.info("cards_restored count=%s", restored)
    return restored
