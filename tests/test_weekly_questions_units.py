from datetime import date

from app.services.weekly_questions import build_weekly_question_card, questions_for_profile


def test_build_card_has_two_questions_and_button():
    card = build_weekly_question_card("Любимый фильм?", "Чай или кофе?", "https://x/hook")
    sections = card["cardsV2"][0]["card"]["sections"]
    assert sections[0]["widgets"][0]["textParagraph"]["text"] == "Любимый фильм?"
    assert sections[0]["widgets"][1]["textInput"]["name"] == "q_llm"
    assert sections[1]["widgets"][0]["textParagraph"]["text"] == "Чай или кофе?"
    assert sections[1]["widgets"][1]["textInput"]["name"] == "q_bank"
    btn = sections[2]["widgets"][0]["buttonList"]["buttons"][0]
    params = {p["key"]: p["value"] for p in btn["onClick"]["action"]["parameters"]}
    assert params["method"] == "submit_weekly_question"
    assert params["q_llm_text"] == "Любимый фильм?"
    assert params["q_bank_text"] == "Чай или кофе?"


def test_questions_for_profile_uses_llm(monkeypatch):
    monkeypatch.setattr(
        "app.services.weekly_questions.generate_personal_question",
        lambda interests: "Твой персональный вопрос",
    )
    personal, bank = questions_for_profile(["кино"], date(2026, 8, 24))
    assert personal == "Твой персональный вопрос"
    assert bank and bank != personal  # общий вопрос из банка


def test_questions_for_profile_falls_back_to_bank(monkeypatch):
    monkeypatch.setattr(
        "app.services.weekly_questions.generate_personal_question",
        lambda interests: None,
    )
    from app.services.question_bank import bank_questions_for

    personal, bank = questions_for_profile([], date(2026, 8, 24))
    assert bank == bank_questions_for(date(2026, 8, 24))[0]  # общий = основной банк
    assert personal == bank_questions_for(date(2026, 8, 24))[1]  # fallback = запасной банк
