# tests/test_weekly_questions_theme.py
import json

from app.services.llm_questions import generate_personal_question
from app.services.weekly_questions import questions_for_profile


def test_generate_personal_question_sends_theme(monkeypatch):
    captured = {}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": json.dumps({"question_text": "Q?"})}}]}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["payload"] = json
        return _Resp()

    monkeypatch.setattr("app.services.llm_questions.requests.post", fake_post)
    generate_personal_question(["food"], level="B1", theme="Travel and places", api_key="k", model="m")
    user_prompt = captured["payload"]["messages"][1]["content"]
    assert "Travel and places" in user_prompt


def test_questions_for_profile_passes_theme(monkeypatch):
    from app.services import weekly_questions as wq

    captured = {}

    def fake_generate(interests, level="A2", avoid=None, theme=None):
        captured["theme"] = theme
        return "personal?"

    monkeypatch.setattr(wq, "generate_personal_question", fake_generate)
    wq.questions_for_profile(["food"], wq.current_week_start(), "B1", avoid=[], theme="Travel")
    assert captured["theme"] == "Travel"


def test_bank_is_large_enough_for_nonrepeat():
    from app.services.question_bank import BANK

    assert len(BANK) >= 40
