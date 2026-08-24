from datetime import date

from app.services.weekly_questions import build_weekly_question_card, question_for_profile


def test_build_card_has_question_field_and_button():
    card = build_weekly_question_card("Любимый фильм?", "https://x/hook")
    sections = card["cardsV2"][0]["card"]["sections"]
    assert sections[0]["widgets"][0]["textParagraph"]["text"] == "Любимый фильм?"
    assert sections[1]["widgets"][0]["textInput"]["name"] == "answer"
    btn = sections[2]["widgets"][0]["buttonList"]["buttons"][0]
    assert btn["text"] == "Отправить ответ"
    params = {p["key"]: p["value"] for p in btn["onClick"]["action"]["parameters"]}
    assert params["method"] == "submit_weekly_question"
    assert params["question"] == "Любимый фильм?"


def test_question_for_profile_uses_llm(monkeypatch):
    monkeypatch.setattr(
        "app.services.weekly_questions.generate_personal_question",
        lambda interests: "Твой персональный вопрос",
    )
    assert question_for_profile(["кино"], date(2026, 8, 24)) == "Твой персональный вопрос"


def test_question_for_profile_falls_back_to_bank(monkeypatch):
    monkeypatch.setattr(
        "app.services.weekly_questions.generate_personal_question",
        lambda interests: None,
    )
    from app.services.question_bank import bank_questions_for
    q = question_for_profile([], date(2026, 8, 24))
    assert q == bank_questions_for(date(2026, 8, 24))[0]
