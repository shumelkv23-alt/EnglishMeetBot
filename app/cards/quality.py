"""Pure quality checks for LLM-generated lesson cards.

The module deliberately has no knowledge of an LLM provider and performs no
I/O.  Its helpers accept ``object`` rather than trusting JSON-shaped input so a
malformed model response can be rejected without raising an exception.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from typing import Iterator


NEAR_DUPLICATE_THRESHOLD = 0.5
MIN_SOURCE_PHRASE_WORDS = 5
MAX_DUPLICATE_MATCHES = 5

MISSING_TOPIC_ERROR = "quality:missing_topic"
NEAR_DUPLICATE_TOPIC_ERROR = "quality:near_duplicate_topic"
EMAIL_PII_ERROR = "quality:pii_email"
PHONE_PII_ERROR = "quality:pii_phone"
SOURCE_PHRASE_COPY_ERROR = "quality:source_phrase_copy"

_TOKEN_RE = re.compile(r"[^\W_]+(?:['\u2019][^\W_]+)*", re.UNICODE)
_EMAIL_RE = re.compile(
    r"(?<![\w.+-])"
    r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+"
    r"@[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+"
    # A full stop is normal sentence punctuation after an address; disallow a
    # following word/hyphen but let the match end before that punctuation.
    r"(?![\w-])",
    re.IGNORECASE,
)
_PHONE_CANDIDATE_RE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{6,}\d(?!\w)")

# Bounds are a safety net for accidental giant or adversarial Python objects.
# Real card fields and participant answers are far smaller than these values.
_MAX_DEPTH = 12
_MAX_SEGMENT_CHARS = 20_000
_MAX_TOTAL_SEGMENTS = 500
_MAX_TOTAL_TOKENS = 20_000


def _tokens(value: object) -> list[str]:
    """Return normalized Unicode word tokens for a scalar string."""
    if not isinstance(value, str):
        return []
    return [token.replace("\u2019", "'").casefold() for token in _TOKEN_RE.findall(value)]


def normalize_topic(topic: object) -> str:
    """Normalize a topic for comparisons: case-fold and collapse punctuation.

    Non-string and tokenless values normalize to an empty string.  The output
    is intended for comparison, not for display.
    """
    return " ".join(_tokens(topic))


def token_jaccard(left: object, right: object) -> float:
    """Return Jaccard similarity between the unique normalized word tokens.

    Empty or malformed operands return ``0.0``.  Returning zero for two empty
    values prevents missing topics from being classified as duplicates.
    """
    left_tokens = set(_tokens(left))
    right_tokens = set(_tokens(right))
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _safe_threshold(value: object) -> float:
    try:
        threshold = float(value)
    except (TypeError, ValueError, OverflowError):
        return NEAR_DUPLICATE_THRESHOLD
    if not math.isfinite(threshold):
        return NEAR_DUPLICATE_THRESHOLD
    return min(1.0, max(0.0, threshold))


def _iter_text(value: object, *, _seen: set[int] | None = None, _depth: int = 0) -> Iterator[str]:
    """Yield string leaves from nested JSON-like input, safely and finitely."""
    if isinstance(value, str):
        if value:
            yield value[:_MAX_SEGMENT_CHARS]
        return
    if value is None or isinstance(value, (bytes, bytearray)) or _depth >= _MAX_DEPTH:
        return

    seen = _seen if _seen is not None else set()
    value_id = id(value)
    if value_id in seen:
        return

    if isinstance(value, Mapping):
        seen.add(value_id)
        try:
            for child in value.values():
                yield from _iter_text(child, _seen=seen, _depth=_depth + 1)
        except (RuntimeError, TypeError, ValueError):
            return
        finally:
            seen.discard(value_id)
        return

    if isinstance(value, Iterable):
        seen.add(value_id)
        try:
            for child in value:
                yield from _iter_text(child, _seen=seen, _depth=_depth + 1)
        except (RuntimeError, TypeError, ValueError):
            return
        finally:
            seen.discard(value_id)


def _text_segments(value: object) -> list[str]:
    """Collect non-empty lines while retaining boundaries between JSON fields."""
    out: list[str] = []
    for text in _iter_text(value):
        for line in text.splitlines() or [text]:
            line = line.strip()
            if line:
                out.append(line)
                if len(out) >= _MAX_TOTAL_SEGMENTS:
                    return out
    return out


def find_near_duplicate_topic(
    topic: object,
    recent_topics: object,
    *,
    threshold: float = NEAR_DUPLICATE_THRESHOLD,
) -> str | None:
    """Return the first recent topic too similar to ``topic``, else ``None``.

    Similarity is exact normalized equality or token Jaccard greater than or
    equal to ``threshold``.  A single string is treated as one history item;
    nested/malformed history is flattened safely.
    """
    normalized = normalize_topic(topic)
    if not normalized:
        return None
    cutoff = _safe_threshold(threshold)
    for candidate in _text_segments(recent_topics):
        candidate_normalized = normalize_topic(candidate)
        if not candidate_normalized:
            continue
        if candidate_normalized == normalized or token_jaccard(normalized, candidate_normalized) >= cutoff:
            return candidate
    return None


def is_near_duplicate_topic(
    topic: object,
    recent_topics: object,
    *,
    threshold: float = NEAR_DUPLICATE_THRESHOLD,
) -> bool:
    """Return whether ``topic`` is a near duplicate of the supplied history."""
    return find_near_duplicate_topic(topic, recent_topics, threshold=threshold) is not None


def _looks_like_phone(candidate: str) -> bool:
    digits = sum(character.isdigit() for character in candidate)
    # Nine digits covers common local numbers while excluding ISO dates such as
    # 2026-08-31.  More than fifteen digits is outside the E.164 maximum.
    return 9 <= digits <= 15


def detect_pii(value: object) -> list[str]:
    """Return detected PII kinds (currently ``email`` and ``phone``).

    Detection runs over all string leaves of nested JSON-like input.  The
    function returns kinds rather than matched values so callers do not leak
    personal data into logs or validation messages.
    """
    email = False
    phone = False
    for segment in _text_segments(value):
        if not email and _EMAIL_RE.search(segment):
            email = True
        if not phone and any(_looks_like_phone(match.group(0)) for match in _PHONE_CANDIDATE_RE.finditer(segment)):
            phone = True
        if email and phone:
            break
    kinds: list[str] = []
    if email:
        kinds.append("email")
    if phone:
        kinds.append("phone")
    return kinds


def contains_pii(value: object) -> bool:
    """Return whether nested generated content appears to contain PII."""
    return bool(detect_pii(value))


def _bounded_token_segments(value: object) -> list[list[str]]:
    segments: list[list[str]] = []
    remaining = _MAX_TOTAL_TOKENS
    for text in _text_segments(value):
        if remaining <= 0:
            break
        tokens = _tokens(text)[:remaining]
        if tokens:
            segments.append(tokens)
            remaining -= len(tokens)
    return segments


def find_exact_phrase_duplicates(
    generated_content: object,
    source_answers: object,
    *,
    min_words: int = MIN_SOURCE_PHRASE_WORDS,
    max_matches: int = MAX_DUPLICATE_MATCHES,
) -> list[str]:
    """Find normalized verbatim phrases copied from participant answers.

    Matching is case- and punctuation-insensitive but preserves word order. A
    match contains at least ``min_words`` consecutive tokens.  Results contain
    normalized phrases and are capped to keep validation output bounded.
    """
    try:
        phrase_size = max(2, int(min_words))
    except (TypeError, ValueError, OverflowError):
        phrase_size = MIN_SOURCE_PHRASE_WORDS
    try:
        result_limit = max(0, int(max_matches))
    except (TypeError, ValueError, OverflowError):
        result_limit = MAX_DUPLICATE_MATCHES
    if result_limit == 0:
        return []

    source_segments = _bounded_token_segments(source_answers)
    source_positions: dict[tuple[str, ...], list[tuple[int, int]]] = {}
    for segment_index, tokens in enumerate(source_segments):
        if len(tokens) < phrase_size:
            continue
        for index in range(len(tokens) - phrase_size + 1):
            ngram = tuple(tokens[index : index + phrase_size])
            positions = source_positions.setdefault(ngram, [])
            # Repeated boilerplate must not make work grow without bound.
            if len(positions) < MAX_DUPLICATE_MATCHES * 4:
                positions.append((segment_index, index))
    if not source_positions:
        return []

    matches: list[str] = []
    seen: set[tuple[str, ...]] = set()
    for generated_tokens in _bounded_token_segments(generated_content):
        if len(generated_tokens) < phrase_size:
            continue
        for generated_index in range(len(generated_tokens) - phrase_size + 1):
            ngram = tuple(generated_tokens[generated_index : generated_index + phrase_size])
            for source_segment_index, source_index in source_positions.get(ngram, []):
                source_tokens = source_segments[source_segment_index]
                # Only process the start of a common run.  Otherwise a six-word
                # copy would be reported as two overlapping five-word copies.
                if (
                    generated_index > 0
                    and source_index > 0
                    and generated_tokens[generated_index - 1] == source_tokens[source_index - 1]
                ):
                    continue
                run_size = phrase_size
                while (
                    generated_index + run_size < len(generated_tokens)
                    and source_index + run_size < len(source_tokens)
                    and generated_tokens[generated_index + run_size] == source_tokens[source_index + run_size]
                ):
                    run_size += 1
                phrase = tuple(generated_tokens[generated_index : generated_index + run_size])
                if phrase in seen:
                    continue
                seen.add(phrase)
                matches.append(" ".join(phrase))
                if len(matches) >= result_limit:
                    return matches
    return matches


def copies_source_phrase(
    generated_content: object,
    source_answers: object,
    *,
    min_words: int = MIN_SOURCE_PHRASE_WORDS,
) -> bool:
    """Return whether generated content copies participant wording verbatim."""
    return bool(
        find_exact_phrase_duplicates(
            generated_content,
            source_answers,
            min_words=min_words,
            max_matches=1,
        )
    )


def _content_topic(content: object) -> object:
    if not isinstance(content, Mapping):
        return None
    try:
        direct = content.get("topic")
        if normalize_topic(direct):
            return direct
        main = content.get("main_content")
        return main.get("topic") if isinstance(main, Mapping) else None
    except (AttributeError, KeyError, RuntimeError, TypeError, ValueError):
        return None


def check_generated_card_quality(
    content: object,
    recent_topics: object = None,
    source_answers: object = None,
) -> list[str]:
    """Return stable quality error codes for generated card content.

    The check accepts both an LLM draft (top-level ``topic``) and a complete
    persisted card (``main_content.topic``).  It never includes matched PII or
    participant wording in returned errors.
    """
    errors: list[str] = []
    topic = _content_topic(content)
    if not normalize_topic(topic):
        errors.append(MISSING_TOPIC_ERROR)
    elif is_near_duplicate_topic(topic, recent_topics):
        errors.append(NEAR_DUPLICATE_TOPIC_ERROR)

    pii_kinds = detect_pii(content)
    if "email" in pii_kinds:
        errors.append(EMAIL_PII_ERROR)
    if "phone" in pii_kinds:
        errors.append(PHONE_PII_ERROR)

    if copies_source_phrase(content, source_answers):
        errors.append(SOURCE_PHRASE_COPY_ERROR)
    return errors


__all__ = [
    "EMAIL_PII_ERROR",
    "MAX_DUPLICATE_MATCHES",
    "MIN_SOURCE_PHRASE_WORDS",
    "MISSING_TOPIC_ERROR",
    "NEAR_DUPLICATE_THRESHOLD",
    "NEAR_DUPLICATE_TOPIC_ERROR",
    "PHONE_PII_ERROR",
    "SOURCE_PHRASE_COPY_ERROR",
    "check_generated_card_quality",
    "contains_pii",
    "copies_source_phrase",
    "detect_pii",
    "find_exact_phrase_duplicates",
    "find_near_duplicate_topic",
    "is_near_duplicate_topic",
    "normalize_topic",
    "token_jaccard",
]
