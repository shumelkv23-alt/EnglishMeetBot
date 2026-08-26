"""Тесты банка и чистых хелперов раздела «English by level» (A/B/C)."""

from app.services import leveled
from app.services import leveled_bank as bank


# ---------------------------------------------------------------------------
# Целостность банка
# ---------------------------------------------------------------------------

def test_level_counts():
    assert len(bank.LEVELS) == 3
    for lvl in bank.LEVELS:
        assert len(lvl["themes"]) == 12
    assert len(bank.THEMES) == 36


def test_levels_reference_existing_themes():
    for lvl in bank.LEVELS:
        for tid in lvl["themes"]:
            assert tid in bank.THEMES
            assert bank.THEMES[tid]["level"] == lvl["id"]


def test_theme_levels_are_valid():
    assert {lvl["id"] for lvl in bank.LEVELS} == {"a", "b", "c"}
    for th in bank.THEMES.values():
        assert th["level"] in {"a", "b", "c"}


def test_themes_have_eight_terms_and_five_quiz():
    for th in bank.THEMES.values():
        assert len(th["terms"]) == 8, th["id"]
        for term in th["terms"]:
            assert len(term) == 3, th["id"]
            assert all(term), th["id"]
        assert len(th["quiz"]) == 5, th["id"]
        for task in th["quiz"]:
            assert len(task) == 4, th["id"]
            assert len(task[1]) == 3, th["id"]
            assert 0 <= task[2] < 3, th["id"]


def test_lookup_helpers():
    assert bank.level_by_id("a")["id"] == "a"
    assert bank.level_by_id("nope") is None
    assert bank.theme_by_id("greetings")["level"] == "a"
    assert bank.theme_by_id("nope") is None
    assert [th["id"] for th in bank.themes_for_level("a")] == [
        "greetings", "routine", "food", "job", "family", "time", "home", "weather",
        "articles", "present_cont", "past_simple", "plurals",
    ]
    assert bank.themes_for_level("nope") == []


# ---------------------------------------------------------------------------
# Хелперы движка (без БД)
# ---------------------------------------------------------------------------

def test_fresh_state_starts_empty():
    st = leveled._fresh_state()
    assert st["themes_studied"] == []
    assert st["tests_passed"] == []


def test_section_points():
    st = leveled._fresh_state()
    assert leveled.section_points(st) == 0
    st["themes_studied"] = ["greetings", "routine"]
    st["tests_passed"] = ["greetings"]
    # 2*1 (темы) + 1*1 (тест) = 3
    assert leveled.section_points(st) == 3


def test_progress_summary_reflects_state():
    st = leveled._fresh_state()
    st["themes_studied"] = ["greetings", "routine", "travel", "negotiation"]
    st["tests_passed"] = ["greetings"]
    summary = leveled.progress_summary(st)
    assert "4/36" in summary
    assert "1/36" in summary
    assert "Level A" in summary and "Level C" in summary
    # 4*1 + 1*1 = 5
    assert str(4 + 1) in summary


# ---------------------------------------------------------------------------
# Тест темы (вопросы)
# ---------------------------------------------------------------------------

def test_theme_test_questions_shape():
    for th in bank.THEMES.values():
        qs = leveled.theme_test_questions(th["id"])
        assert len(qs) == 5, th["id"]
        # 3 словарных (4 варианта) + 2 грамматических (3 варианта)
        for q in qs[:3]:
            assert len(q["options"]) == 4, th["id"]
            assert 0 <= q["correct"] < 4, th["id"]
        for q in qs[3:]:
            assert len(q["options"]) == 3, th["id"]
            assert 0 <= q["correct"] < 3, th["id"]


def test_theme_test_questions_are_deterministic():
    for th in bank.THEMES.values():
        assert leveled.theme_test_questions(th["id"]) == leveled.theme_test_questions(th["id"])


def test_vocab_question_correct_option_matches_meaning():
    qs = leveled.theme_test_questions("greetings")
    vocab = qs[0]
    theme = bank.theme_by_id("greetings")
    assert vocab["options"][vocab["correct"]] == theme["terms"][0][1]


def test_theme_test_questions_unknown_theme():
    assert leveled.theme_test_questions("nope") == []


# ---------------------------------------------------------------------------
# Карточки
# ---------------------------------------------------------------------------

def _card_id(card):
    return card["cardsV2"][0]["cardId"]


def _button_texts(card):
    widgets = card["cardsV2"][0]["card"]["sections"][0]["widgets"]
    return [b["text"] for w in widgets if "buttonList" in w for b in w["buttonList"]["buttons"]]


def test_all_cards_share_single_card_id():
    st = leveled._fresh_state()
    theme = bank.theme_by_id("greetings")
    assert _card_id(leveled.build_level_menu_card()) == "leveled"
    assert _card_id(leveled.build_themes_card("a", st)) == "leveled"
    assert _card_id(leveled.build_theme_card(theme, st)) == "leveled"
    assert _card_id(leveled.build_progress_card(st)) == "leveled"

    qs = leveled.theme_test_questions("greetings")
    assert _card_id(leveled._test_question_card("t", 0, 5, qs[0], 0, "leveled_test_answer", {"theme": "greetings"})) == "leveled"
    assert _card_id(leveled._test_feedback_card("t", 0, 5, qs[0], True, 1, "leveled_test", {"theme": "greetings"})) == "leveled"
    assert _card_id(leveled._test_result_card("t", True, 5, 5, 4, 1, "leveled_themes", "↩", {"level": "a"})) == "leveled"


def test_level_menu_has_three_level_buttons():
    card = leveled.build_level_menu_card()
    texts = _button_texts(card)
    assert sum(1 for t in texts if "Level A" in t) == 1
    assert sum(1 for t in texts if "Level B" in t) == 1
    assert sum(1 for t in texts if "Level C" in t) == 1


def test_themes_card_lists_twelve_themes():
    card = leveled.build_themes_card("b", leveled._fresh_state())
    texts = _button_texts(card)
    assert sum(1 for t in texts if t.startswith(("▫️", "📖", "✅"))) == 12


def test_theme_card_has_test_button():
    theme = bank.theme_by_id("greetings")
    card = leveled.build_theme_card(theme, leveled._fresh_state())
    texts = _button_texts(card)
    assert any("Take the test" in t for t in texts)


def test_question_card_has_answer_buttons():
    qs = leveled.theme_test_questions("greetings")
    card = leveled._test_question_card("t", 0, 5, qs[0], 0, "leveled_test_answer", {"theme": "greetings"})
    texts = _button_texts(card)
    # 4 варианта ответа (A./B./C./D.)
    assert sum(1 for t in texts if t[:2] in ("A.", "B.", "C.", "D.")) == 4


def test_progress_card_shows_points():
    st = leveled._fresh_state()
    st["themes_studied"] = ["greetings"]
    st["tests_passed"] = ["greetings"]
    card = leveled.build_progress_card(st)
    widgets = card["cardsV2"][0]["card"]["sections"][0]["widgets"]
    text = widgets[0]["textParagraph"]["text"]
    assert "2" in text
