"""LLM generation for full lesson cards.

The generator is intentionally strict: the model creates the complete lesson
plan, but server-owned data (suggested activity, metadata, persistence fields)
is still added by ``app.cards.service``.  Invalid or risky responses return
``None`` so the template fallback can safely take over.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Mapping, Sequence
from typing import Any

import requests
from pydantic import ValidationError

from app.cards.activity_matcher import GAMES
from app.cards.generator.recipes import TYPE_RECIPES, type_payload_errors
from app.cards.quality import (
    check_generated_card_quality,
    is_near_duplicate_topic,
)
from app.cards.schemas import LLMCardDraft
from app.config import get_settings

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://llm.azati.ai"
ANTHROPIC_VERSION = "2023-06-01"
PROMPT_VERSION = "cards-v2"
MAX_CONTEXT_CHARS = 4000
MAX_REPAIR_JSON_CHARS = 5000
GROUNDED_TYPES = frozenset({"debate", "news_reaction", "culture"})
SUPPORTED_ACTIVITY_IDS = tuple(game["activity_id"] for game in GAMES)

_JSON_SHAPE = """{
  "warm_up": {"question": "...", "based_on_profile_field": null},
  "main_content": {
    "topic": "...",
    "sub_questions": [
      {"text": "...", "level": "easy"},
      {"text": "...", "level": "medium"},
      {"text": "...", "level": "hard"}
    ],
    "type_specific_payload": {}
  },
  "vocab_box": [
    {"phrase": "...", "translation": "...", "example": "..."},
    {"phrase": "...", "translation": "...", "example": "..."}
  ],
  "stretch_challenge": "...",
  "wrap_up_question": "...",
  "suggested_activity_id": "alias"
}"""


def _extract_text(payload: dict) -> str:
    """Extract text from an Anthropic Messages-style response."""
    content = payload.get("content") or []
    parts: list[str] = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(str(item.get("text") or ""))
    return "\n".join(parts).strip()


def _parse_json(text: str | None) -> dict:
    """Parse a JSON object from a model response."""
    if not text:
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return {}
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _post_messages(
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict],
    max_tokens: int,
    temperature: float,
    timeout: float,
) -> dict | None:
    response = requests.post(
        f"{base_url.rstrip('/')}/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    parsed = response.json()
    return parsed if isinstance(parsed, dict) else None


def _post_legacy_messages(payload: dict, timeout: float) -> str:
    settings = get_settings()
    response = requests.post(
        f"{str(getattr(settings, 'llm_base_url', '') or DEFAULT_BASE_URL).rstrip('/')}/v1/messages",
        headers={
            "x-api-key": str(getattr(settings, "llm_api_key", "") or ""),
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
        json=payload,
        timeout=timeout,
    )
    response.raise_for_status()
    return _extract_text(response.json())


def _cards_model(settings: object) -> str:
    model = str(getattr(settings, "llm_cards_model", "") or "").strip()
    if model:
        return model
    return str(getattr(settings, "llm_games_model", "") or "").strip()


async def _call_llm(
    prompt: str | Mapping[str, Any],
    *,
    max_tokens: int = 1200,
    temperature: float = 0.7,
    timeout: float | None = None,
) -> dict | str | None:
    """Call the configured Anthropic-compatible LLM endpoint.

    ``str`` input is the card-generator API and returns parsed JSON. ``dict``
    input preserves the older helper contract used by vocab/wordle and returns
    raw text.
    """
    settings = get_settings()
    api_key = str(getattr(settings, "llm_api_key", "") or "").strip()
    if isinstance(prompt, Mapping):
        if not api_key:
            return None
        try:
            return await asyncio.to_thread(_post_legacy_messages, dict(prompt), timeout or 20.0)
        except (requests.RequestException, ValueError, TypeError):
            logger.warning("cards_llm_call_failed", exc_info=True)
            return None

    model = _cards_model(settings)
    if not api_key or not model:
        return None

    base_url = str(getattr(settings, "llm_base_url", "") or DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL
    try:
        payload = await asyncio.to_thread(
            _post_messages,
            base_url=base_url,
            api_key=api_key,
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=20.0,
        )
    except (requests.RequestException, ValueError, TypeError):
        logger.warning("cards_llm_call_failed", exc_info=True)
        return None
    if not payload:
        return None
    return _parse_json(_extract_text(payload))


def _clip(value: object, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def _json_block(value: object, limit: int = 2000) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
    except (TypeError, ValueError):
        text = str(value)
    return _clip(text, limit)


def _recent_topics_block(recent_topics: Sequence[str] | None) -> str:
    topics = [_clip(topic, 180) for topic in (recent_topics or []) if str(topic or "").strip()]
    if not topics:
        return ""
    lines = ["Recent card topics; do NOT repeat these or make a near-duplicate:"]
    lines.extend(f"- {topic}" for topic in topics[:20])
    return "\n".join(lines)


def _bank_payload_block(card_type_name: str, bank_payload: Mapping[str, Any] | None) -> str:
    if not bank_payload:
        return ""
    text = _json_block(bank_payload, 1800)
    if card_type_name in GROUNDED_TYPES:
        return (
            "Approved source payload for this card type. Keep the required type_specific_payload "
            "fields faithful to this data; do not invent different facts or premises:\n"
            f"{text}"
        )
    return f"Optional seed payload you may adapt safely:\n{text}"


def _activity_instruction(card_type_name: str) -> str:
    ids = ", ".join(SUPPORTED_ACTIVITY_IDS)
    if card_type_name == "game_day":
        return f"Choose one supported game id for type_specific_payload.activity_id: {ids}."
    return f"Optionally suggest one supported activity id in suggested_activity_id: {ids}."


def _build_idea_prompt(
    card_type_name: str,
    difficulty: str,
    context: str,
    *,
    theme: str | None = None,
    recent_topics: Sequence[str] | None = None,
) -> str:
    theme_line = f"\nTheme: {_clip(theme, 160)}" if theme else ""
    recent_block = _recent_topics_block(recent_topics)
    return f"""You are designing English speaking lesson cards.
Generate 3 fresh candidate ideas before the full card.

Card type: {card_type_name}
Group level: {difficulty}{theme_line}

Participant signals, anonymized:
{_clip(context, MAX_CONTEXT_CHARS)}

{recent_block}

Return JSON only:
{{"ideas":[{{"topic":"...","angle":"..."}}]}}
"""


def _build_card_prompt(
    card_type_name: str,
    difficulty: str,
    context: str,
    *,
    theme: str | None = None,
    recent_topics: Sequence[str] | None = None,
    bank_payload: Mapping[str, Any] | None = None,
    group_size: int | None = None,
    creative_angle: Mapping[str, Any] | None = None,
) -> str:
    """Build the full-card prompt; kept public for existing unit tests."""
    recipe = TYPE_RECIPES.get(card_type_name, TYPE_RECIPES["topic"])
    theme_line = f"\nThis week's theme: {_clip(theme, 160)}" if theme else ""
    group_line = f"\nGroup size: {group_size}" if group_size else ""
    recent_block = _recent_topics_block(recent_topics)
    bank_block = _bank_payload_block(card_type_name, bank_payload)
    angle_block = f"Chosen creative angle:\n{_json_block(creative_angle, 800)}" if creative_angle else ""

    return f"""You create vivid, safe English speaking lesson cards for a small group.
Return JSON only. No Markdown, no commentary.

Card type: {card_type_name}
Group level: {difficulty}{group_line}{theme_line}
Prompt version: {PROMPT_VERSION}

Card-type recipe:
{recipe["instructions"]}

{_activity_instruction(card_type_name)}

Participant signals, anonymized. Use them as inspiration, but do not quote names,
contacts, or exact private wording:
{_clip(context, MAX_CONTEXT_CHARS)}

{recent_block}

{bank_block}

{angle_block}

Rules:
- Generate all four phases: warm_up, main_content, stretch_challenge, wrap_up_question.
- Use exactly 3 sub_questions ordered easy, medium, hard.
- Make questions specific, social, and fun enough for a live speaking club.
- vocab_box must contain 2 or 3 useful English phrases.
- Each vocab translation must be in Russian; examples must be natural English.
- Keep the topic safe: no politics, religion, salary, debt, illness, tragedy, or adult content.
- Avoid personal data and avoid copying participant answers verbatim.
- type_specific_payload must match the card type and include required fields.

JSON shape:
{_JSON_SHAPE}
"""


def _payload_from_bank(card_type_name: str, payload: dict, bank_payload: Mapping[str, Any] | None) -> dict:
    if not bank_payload or card_type_name not in GROUNDED_TYPES:
        return payload
    recipe = TYPE_RECIPES.get(card_type_name, TYPE_RECIPES["topic"])
    grounded = dict(payload)
    for field in recipe["required_payload_fields"]:
        if field in bank_payload:
            grounded[field] = bank_payload[field]
    return grounded


def _valid_activity_id(value: object) -> str | None:
    activity_id = str(value or "").strip()
    return activity_id if activity_id in SUPPORTED_ACTIVITY_IDS else None


def _normalise_card_draft(
    data: Mapping[str, Any],
    card_type_name: str,
    *,
    bank_payload: Mapping[str, Any] | None = None,
) -> tuple[dict | None, list[str]]:
    if not isinstance(data, Mapping):
        return None, ["draft must be an object"]

    draft_data = {
        "warm_up": data.get("warm_up"),
        "main_content": data.get("main_content"),
        "vocab_box": data.get("vocab_box"),
        "stretch_challenge": data.get("stretch_challenge"),
        "wrap_up_question": data.get("wrap_up_question"),
    }

    main = draft_data.get("main_content")
    if isinstance(main, Mapping):
        main = dict(main)
        payload = main.get("type_specific_payload")
        payload = dict(payload) if isinstance(payload, Mapping) else {}
        main["type_specific_payload"] = _payload_from_bank(card_type_name, payload, bank_payload)
        draft_data["main_content"] = main

    try:
        draft = LLMCardDraft.model_validate(draft_data)
    except ValidationError as exc:
        return None, [f"schema:{'.'.join(str(part) for part in error['loc'])}" for error in exc.errors()]

    normalised = draft.model_dump()
    payload = (normalised.get("main_content") or {}).get("type_specific_payload") or {}
    payload_errors = type_payload_errors(card_type_name, payload)
    if payload_errors:
        return None, payload_errors

    if card_type_name == "game_day" and not _valid_activity_id(payload.get("activity_id")):
        return None, ["invalid type_specific_payload.activity_id"]

    suggested_activity_id = _valid_activity_id(data.get("suggested_activity_id"))
    if suggested_activity_id:
        normalised["suggested_activity_id"] = suggested_activity_id
    return normalised, []


def _choose_idea(data: Mapping[str, Any] | None, recent_topics: Sequence[str] | None) -> Mapping[str, Any] | None:
    if not isinstance(data, Mapping):
        return None
    ideas = data.get("ideas")
    if not isinstance(ideas, list):
        return None
    first_valid: Mapping[str, Any] | None = None
    for idea in ideas:
        if not isinstance(idea, Mapping):
            continue
        topic = str(idea.get("topic") or "").strip()
        if not topic:
            continue
        if first_valid is None:
            first_valid = idea
        if not is_near_duplicate_topic(topic, recent_topics):
            return idea
    return first_valid


def _repair_prompt(
    original_prompt: str,
    bad_response: Mapping[str, Any] | None,
    errors: Sequence[str],
) -> str:
    return f"""{original_prompt}

Your previous JSON failed validation. Fix only the JSON and return JSON only.
Validation errors:
{_json_block(list(errors), 1200)}

Previous JSON:
{_json_block(bad_response, MAX_REPAIR_JSON_CHARS)}
"""


async def generate_llm_content(
    card_type_name: str,
    difficulty: str,
    context: str,
    *,
    theme: str | None = None,
    recent_topics: Sequence[str] | None = None,
    bank_payload: Mapping[str, Any] | None = None,
    group_size: int | None = None,
    source_answers: Sequence[str] | None = None,
) -> dict | None:
    """Generate a complete LLM card draft, or ``None`` for fallback."""
    if card_type_name in GROUNDED_TYPES:
        required = TYPE_RECIPES.get(card_type_name, TYPE_RECIPES["topic"])["required_payload_fields"]
        if required and type_payload_errors(card_type_name, bank_payload):
            return None

    started = time.perf_counter()
    settings = get_settings()
    model = _cards_model(settings)

    idea_response = await _call_llm(
        _build_idea_prompt(
            card_type_name,
            difficulty,
            context,
            theme=theme,
            recent_topics=recent_topics,
        ),
        max_tokens=500,
        temperature=0.9,
    )
    creative_angle = _choose_idea(idea_response, recent_topics)

    prompt = _build_card_prompt(
        card_type_name,
        difficulty,
        context,
        theme=theme,
        recent_topics=recent_topics,
        bank_payload=bank_payload,
        group_size=group_size,
        creative_angle=creative_angle,
    )

    last_errors: list[str] = []
    last_response: Mapping[str, Any] | None = None
    for attempt in range(1, 3):
        response = await _call_llm(
            prompt if attempt == 1 else _repair_prompt(prompt, last_response, last_errors),
            max_tokens=1800,
            temperature=0.75 if attempt == 1 else 0.35,
        )
        if not isinstance(response, Mapping):
            last_response = response
            last_errors = ["invalid_json"]
        else:
            last_response = response
            draft, errors = _normalise_card_draft(response, card_type_name, bank_payload=bank_payload)
            if draft is not None:
                quality_errors = check_generated_card_quality(draft, recent_topics, source_answers)
                if not quality_errors:
                    draft["_generation_meta"] = {
                        "prompt_version": PROMPT_VERSION,
                        "model": model,
                        "attempts": attempt,
                        "duration_ms": int((time.perf_counter() - started) * 1000),
                        "outcome": "success",
                        "creative_angle": dict(creative_angle) if isinstance(creative_angle, Mapping) else None,
                    }
                    return draft
                errors = [*errors, *quality_errors]
            last_errors = list(errors)
        if attempt == 1:
            await asyncio.sleep(0.5)

    logger.warning(
        "cards_llm_validation_failed type=%s errors=%s",
        card_type_name,
        last_errors[:8],
    )
    return None


__all__ = [
    "PROMPT_VERSION",
    "_build_card_prompt",
    "_call_llm",
    "_normalise_card_draft",
    "_parse_json",
    "generate_llm_content",
]
