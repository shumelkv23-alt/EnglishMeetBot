"""Тесты банка и чистых хелперов курса «Survival English for Calls»."""

from app.services import callready
from app.services import callready_bank as bank


# ---------------------------------------------------------------------------
# Целостность банка (контент портирован 1:1 из CallReady)
# ---------------------------------------------------------------------------

def test_bank_counts():
    assert len(bank.MODULES) == 12
    assert len(bank.BLOCKS) == 3
    assert len(bank.BACKUP) == 5
    assert len(bank.GRAMMAR_TOPICS) == 8
    assert len(bank.GRAMMAR_GUIDES) == 8
    assert len(bank.GRAMMAR_TASKS) == 40


def test_module_ids_are_unique():
    ids = [m["id"] for m in bank.MODULES]
    assert len(ids) == len(set(ids))


def test_blocks_reference_existing_modules():
    mods = {m["id"] for m in bank.MODULES}
    for b in bank.BLOCKS:
        assert len(b["modules"]) == 4
        for mid in b["modules"]:
            assert mid in mods


def test_blocks_cover_all_modules_once():
    flat = [mid for b in bank.BLOCKS for mid in b["modules"]]
    assert sorted(flat) == sorted(m["id"] for m in bank.MODULES)


def test_blocks_grammar_indices_in_range():
    for b in bank.BLOCKS:
        for ti in b["grammar"]:
            assert 0 <= ti < len(bank.GRAMMAR_TOPICS)


def test_topics_task_indices_in_range():
    for t in bank.GRAMMAR_TOPICS:
        assert t["tasks"]
        for ti in t["tasks"]:
            assert 0 <= ti < len(bank.GRAMMAR_TASKS)


def test_every_task_referenced_by_some_topic():
    referenced = {ti for t in bank.GRAMMAR_TOPICS for ti in t["tasks"]}
    assert referenced == set(range(len(bank.GRAMMAR_TASKS)))


def test_tasks_have_three_options_and_valid_correct():
    for i, task in enumerate(bank.GRAMMAR_TASKS):
        assert len(task) == 4, f"task {i} shape"
        assert len(task[1]) == 3, f"task {i} options"
        assert 0 <= task[2] < 3, f"task {i} correct index"


def test_modules_have_six_three_part_terms():
    for m in bank.MODULES:
        assert len(m["terms"]) == 6
        for term in m["terms"]:
            assert len(term) == 3
            assert all(term)


# ---------------------------------------------------------------------------
# Хелперы движка (без БД)
# ---------------------------------------------------------------------------

def test_md_converts_html_to_chat_markdown():
    assert callready._md("<b>bold</b>") == "**bold**"
    assert callready._md("<i>it</i>") == "*it*"
    assert callready._md("<s>no</s>") == "~no~"
    out = callready._md("<h3>Title</h3><p>First <b>bold</b>.</p><p>Second.</p>")
    assert out == "**Title**\n\nFirst **bold**.\n\nSecond."


def test_fresh_state_starts_at_first_module():
    st = callready._fresh_state()
    assert st["current_module"] == bank.MODULES[0]["id"]
    assert st["done"] == []
    assert st["grammar"] == {}
    assert st["phrasebook_seen"] == []


def test_module_points():
    st = callready._fresh_state()
    assert callready.module_points(st) == 0
    st["done"] = ["start", "status"]
    st["blocks_read"] = ["foundation"]
    st["modules_tested"] = ["start"]
    st["blocks_tested"] = ["delivery"]
    # 2*1 (модули) + 1*3 (блок) + 1*1 (тест модуля) + 1*2 (тест блока) = 8
    assert callready.module_points(st) == 8


def test_progress_summary_reflects_state():
    st = callready._fresh_state()
    st["done"] = ["start", "status", "clarify", "decide"]  # Block 1 целиком
    st["blocks_read"] = ["foundation"]
    st["modules_tested"] = ["start", "status"]
    st["blocks_tested"] = ["delivery"]
    st["grammar"] = {str(i): True for i in range(40)}       # все задания
    st["phrasebook_seen"] = list(bank.BACKUP)
    summary = callready.progress_summary(st)
    assert "4/12" in summary
    assert "Block 1 · Call foundations: read 4/4" in summary
    assert "40/40" in summary
    assert "5/5" in summary
    # 4*1 + 1*3 + 2*1 + 1*2 = 11
    assert str(4 + 3 + 2 + 2) in summary


# ---------------------------------------------------------------------------
# Карточки
# ---------------------------------------------------------------------------

def _card_id(card):
    return card["cardsV2"][0]["cardId"]


def test_all_cards_share_single_card_id():
    st = callready._fresh_state()
    assert _card_id(callready.build_menu_card()) == "callready"
    assert _card_id(callready.build_module_card(bank.MODULES[0], st)) == "callready"
    assert _card_id(callready.build_route_card(st)) == "callready"
    assert _card_id(callready.build_phrasebook_menu_card()) == "callready"
    assert _card_id(callready.build_phrasebook_cat_card("I need time")) == "callready"
    assert _card_id(callready.build_practice_menu_card()) == "callready"
    assert _card_id(callready.build_topic_card(0)) == "callready"
    assert _card_id(callready.build_task_card(0, 0)) == "callready"
    task = bank.GRAMMAR_TASKS[bank.GRAMMAR_TOPICS[0]["tasks"][0]]
    assert _card_id(callready.build_feedback_card(0, 0, True, task)) == "callready"
    assert _card_id(callready.build_progress_card(st)) == "callready"


def test_task_card_has_three_answer_buttons():
    card = callready.build_task_card(0, 0)
    widgets = card["cardsV2"][0]["card"]["sections"][0]["widgets"]
    answer_buttons = widgets[1]["buttonList"]["buttons"]
    assert len(answer_buttons) == 3


def test_feedback_card_last_question_has_no_next():
    topic = 7  # Linking ideas, 5 tasks
    last_pos = len(bank.GRAMMAR_TOPICS[topic]["tasks"]) - 1
    task = bank.GRAMMAR_TASKS[bank.GRAMMAR_TOPICS[topic]["tasks"][last_pos]]
    card = callready.build_feedback_card(topic, last_pos, True, task)
    widgets = card["cardsV2"][0]["card"]["sections"][0]["widgets"]
    texts = [w["textParagraph"]["text"] for w in widgets if "textParagraph" in w]
    assert any("finished this topic" in t for t in texts)
    # На последнем задании нет кнопки «Next question →».
    button_texts = [b["text"] for w in widgets if "buttonList" in w for b in w["buttonList"]["buttons"]]
    assert not any("Next question" in b for b in button_texts)


def test_module_index_and_block_lookup():
    assert bank.module_index("start") == 0
    assert bank.module_index("email") == 11
    assert bank.module_index("nope") == -1
    assert bank.block_for_module("recover")["id"] == "delivery"
    assert bank.block_for_module("nope") is None
    assert bank.module_by_id("start")["title"] == "Start & participate"
    assert bank.block_by_id("foundation")["id"] == "foundation"
    assert bank.block_by_id("nope") is None


# ---------------------------------------------------------------------------
# Тесты модуля и блока
# ---------------------------------------------------------------------------

def test_module_quiz_covers_all_modules():
    assert set(bank.MODULE_QUIZ) == {m["id"] for m in bank.MODULES}
    for mid, task in bank.MODULE_QUIZ.items():
        assert len(task) == 4, mid
        assert len(task[1]) == 3, mid
        assert 0 <= task[2] < 3, mid


def test_module_test_questions_shape():
    for m in bank.MODULES:
        qs = callready.module_test_questions(m["id"])
        assert len(qs) == 7, m["id"]
        # 6 словарных (4 варианта) + 1 грамматический (3 варианта)
        for q in qs[:6]:
            assert len(q["options"]) == 4
            assert 0 <= q["correct"] < 4
        assert len(qs[6]["options"]) == 3
        assert 0 <= qs[6]["correct"] < 3


def test_block_test_questions_shape():
    for b in bank.BLOCKS:
        qs = callready.block_test_questions(b["id"])
        assert len(qs) == 10, b["id"]
        for q in qs[:6]:
            assert len(q["options"]) == 4
            assert 0 <= q["correct"] < 4
        for q in qs[6:]:
            assert len(q["options"]) == 3
            assert 0 <= q["correct"] < 3


def test_test_questions_are_deterministic():
    for m in bank.MODULES:
        assert callready.module_test_questions(m["id"]) == callready.module_test_questions(m["id"])
    for b in bank.BLOCKS:
        assert callready.block_test_questions(b["id"]) == callready.block_test_questions(b["id"])


def test_vocab_question_correct_option_matches_meaning():
    qs = callready.module_test_questions("start")
    vocab = qs[0]
    assert vocab["options"][vocab["correct"]] == bank.MODULES[0]["terms"][0][1]


def test_module_card_has_module_test_button():
    card = callready.build_module_card(bank.MODULES[0], callready._fresh_state())
    widgets = card["cardsV2"][0]["card"]["sections"][0]["widgets"]
    button_texts = [b["text"] for w in widgets if "buttonList" in w for b in w["buttonList"]["buttons"]]
    assert any("Module test" in b for b in button_texts)


def test_route_card_has_block_test_buttons():
    card = callready.build_route_card(callready._fresh_state())
    widgets = card["cardsV2"][0]["card"]["sections"][0]["widgets"]
    button_texts = [b["text"] for w in widgets if "buttonList" in w for b in w["buttonList"]["buttons"]]
    assert sum(1 for b in button_texts if "Block test" in b) == 3
