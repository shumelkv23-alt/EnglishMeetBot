import json

from app.services.llm_questions import generate_personal_question, parse_generated_json


def test_parse_valid_json():
    assert parse_generated_json('{"question_text": "Какой твой любимый фильм?"}') == "Какой твой любимый фильм?"


def test_parse_missing_field_returns_none():
    assert parse_generated_json('{"foo": "bar"}') is None


def test_parse_invalid_json_returns_none():
    assert parse_generated_json("не json") is None


def test_generate_success(monkeypatch):
    def fake_post(url, **kwargs):
        class R:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"choices": [{"message": {"content": '{"question_text": "Хобби?"}'}}]}

        return R()

    monkeypatch.setattr("app.services.llm_questions.requests.post", fake_post)
    q = generate_personal_question(["кино"], api_key="sk-test", model="m/x")
    assert q == "Хобби?"


def test_generate_http_error_returns_none(monkeypatch):
    def fake_post(url, **kwargs):
        class R:
            status_code = 500

            def raise_for_status(self):
                raise RuntimeError("http 500")

        return R()

    monkeypatch.setattr("app.services.llm_questions.requests.post", fake_post)
    assert generate_personal_question(["кино"], api_key="sk-test") is None


def test_generate_without_key_skips_network():
    # без ключа даже не ходим в сеть — мгновенный None
    assert generate_personal_question(["кино"], api_key=None) is None