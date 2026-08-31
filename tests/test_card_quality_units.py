import math

from app.cards.quality import (
    EMAIL_PII_ERROR,
    MISSING_TOPIC_ERROR,
    NEAR_DUPLICATE_TOPIC_ERROR,
    PHONE_PII_ERROR,
    SOURCE_PHRASE_COPY_ERROR,
    check_generated_card_quality,
    contains_pii,
    detect_pii,
    find_exact_phrase_duplicates,
    find_near_duplicate_topic,
    is_near_duplicate_topic,
    normalize_topic,
    token_jaccard,
)


def test_normalize_topic_is_unicode_case_and_punctuation_insensitive():
    assert normalize_topic("  Future—of WORK!!! ") == "future of work"
    assert normalize_topic("Traveler's Café") == "traveler's café"
    assert normalize_topic(None) == ""
    assert normalize_topic({"topic": "ignored"}) == ""


def test_token_jaccard_uses_unique_normalized_tokens():
    assert token_jaccard("Food, food & Cooking", "cooking food") == 1.0
    assert token_jaccard("future of work", "future work") == 2 / 3
    assert token_jaccard("", "") == 0.0
    assert token_jaccard([], "travel") == 0.0


def test_near_duplicate_topic_handles_single_string_nested_and_malformed_history():
    assert find_near_duplicate_topic("The Future of Work", "future work") == "future work"
    assert is_near_duplicate_topic(
        "Remote Work Habits",
        [None, {"old": "Habits of remote work"}, 42],
    )
    assert not is_near_duplicate_topic("Food traditions", ["Travel mishaps", None])
    assert not is_near_duplicate_topic(None, [None, ""])
    # Non-finite configuration is sanitized rather than leaking NaN semantics.
    assert is_near_duplicate_topic("Future work", ["The future of work"], threshold=math.nan)


def test_detect_pii_searches_nested_content_without_returning_values():
    content = {
        "topic": "Keeping in touch",
        "sub_questions": [
            {"text": "Write to Alex.Person+club@example.co.uk."},
            {"text": "Or call +48 123 456 789."},
        ],
    }
    assert detect_pii(content) == ["email", "phone"]
    assert contains_pii(content)
    assert not contains_pii({"text": "The meetup is on 2026-08-31 at 18:00."})


def test_pii_detection_is_cycle_safe():
    malformed: list[object] = ["hello@example.com"]
    malformed.append(malformed)
    assert detect_pii(malformed) == ["email"]


def test_find_exact_phrase_duplicates_is_case_and_punctuation_insensitive():
    generated = {
        "topic": "Weekend rituals",
        "sub_questions": [
            {"text": "Why is BAKING sourdough with my sister so memorable?"},
        ],
    }
    source = ["My favorite weekend ritual is baking sourdough with my sister."]
    assert find_exact_phrase_duplicates(generated, source) == [
        "is baking sourdough with my sister",
    ]


def test_exact_phrase_duplicate_ignores_paraphrase_and_short_overlap():
    generated = "Tell us why you enjoy making bread together."
    source = "I enjoy baking sourdough with my sister every Sunday."
    assert find_exact_phrase_duplicates(generated, source) == []
    assert find_exact_phrase_duplicates("one two three four", "one two three four") == []


def test_exact_phrase_duplicate_does_not_cross_field_or_answer_boundaries():
    generated = ["one two three", "four five six"]
    source = ["one two three four", "five six seven eight"]
    assert find_exact_phrase_duplicates(generated, source) == []


def test_exact_phrase_duplicate_tolerates_bad_options_and_malformed_inputs():
    assert find_exact_phrase_duplicates(None, {"answer": None}) == []
    assert find_exact_phrase_duplicates(
        "one two three four five",
        "one two three four five",
        min_words="bad",  # type: ignore[arg-type]
        max_matches="bad",  # type: ignore[arg-type]
    ) == ["one two three four five"]


def test_quality_check_reports_each_quality_class_once():
    content = {
        "topic": "Remote Work Habits",
        "sub_questions": [
            {"text": "I spend every Sunday baking sourdough with my sister."},
            {"text": "Share answers with club@example.com or +48 123 456 789."},
        ],
    }
    errors = check_generated_card_quality(
        content,
        recent_topics=["Habits of remote work"],
        source_answers=["Every Sunday I enjoy baking sourdough with my sister."],
    )
    assert errors == [
        NEAR_DUPLICATE_TOPIC_ERROR,
        EMAIL_PII_ERROR,
        PHONE_PII_ERROR,
        SOURCE_PHRASE_COPY_ERROR,
    ]


def test_quality_check_accepts_complete_card_shape():
    content = {
        "main_content": {
            "topic": "Unexpected museum adventures",
            "sub_questions": [{"text": "What exhibit surprised you most?"}],
        },
        "vocab_box": [],
    }
    assert check_generated_card_quality(content, ["Cooking together"], []) == []


def test_quality_check_is_stable_for_malformed_content():
    assert check_generated_card_quality(None, None, None) == [MISSING_TOPIC_ERROR]
    assert check_generated_card_quality("club@example.com", {}, {}) == [
        MISSING_TOPIC_ERROR,
        EMAIL_PII_ERROR,
    ]
