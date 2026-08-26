# tests/test_llm_questions_level.py
import json

from app.services.llm_questions import _system_prompt, generate_personal_question


def test_system_prompt_includes_level_hint():
    a1 = _system_prompt("A1")
    c2 = _system_prompt("C2")
    assert "A1" in a1 and "simple" in a1
    assert "C2" in c2 and "idiomatic" in c2


def test_generate_personal_question_uses_level_prompt(monkeypatch):
    captured = {}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"content": [{"type": "text", "text": json.dumps({"question_text": "Q?"})}]}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["payload"] = json
        return _Resp()

    monkeypatch.setattr("app.services.llm_questions.requests.post", fake_post)

    q = generate_personal_question(["food"], level="C1", api_key="k", model="m")
    assert q == "Q?"
    system = captured["payload"]["system"]
    assert "C1" in system


def test_questions_for_profile_passes_level(monkeypatch):
    from app.services import weekly_questions as wq

    captured = {}

    def fake_generate(interests, level="A2", avoid=None, theme=None):
        captured["level"] = level
        return "personal?"

    monkeypatch.setattr(wq, "generate_personal_question", fake_generate)

    personal, _bank = wq.questions_for_profile(["food"], wq.current_week_start(), "C1", avoid=[])
    assert personal == "personal?"
    assert captured["level"] == "C1"
