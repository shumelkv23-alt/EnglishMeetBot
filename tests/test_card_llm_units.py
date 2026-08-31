import asyncio
from types import SimpleNamespace

from app.cards.generator.llm import generate_llm_content


def _draft(**overrides):
    data = {
        "warm_up": {"question": "What small ritual makes your week better?", "based_on_profile_field": None},
        "main_content": {
            "topic": "Tiny rituals that make ordinary days better",
            "sub_questions": [
                {"text": "What is one tiny ritual you enjoy?", "level": "easy"},
                {"text": "Why do small habits feel powerful?", "level": "medium"},
                {"text": "Which ritual would improve a difficult week?", "level": "hard"},
            ],
            "type_specific_payload": {},
        },
        "vocab_box": [
            {"phrase": "a small ritual", "translation": "маленький ритуал", "example": "Making tea is a small ritual for me."},
            {"phrase": "to set the tone", "translation": "задать настроение", "example": "A calm morning can set the tone for the day."},
        ],
        "stretch_challenge": "Describe the same ritual as if you were selling it to a busy friend.",
        "wrap_up_question": "Which idea from today would you actually try?",
        "suggested_activity_id": "alias",
    }
    data.update(overrides)
    return data


def _settings():
    return SimpleNamespace(
        llm_api_key="key",
        llm_games_model="Azati Fast",
        llm_cards_model="Azati Smart",
        llm_base_url="https://t.local",
    )


def test_generate_full_card_success(monkeypatch):
    calls = []

    async def fake_call(prompt, **kwargs):
        calls.append(prompt)
        if "Generate 3 fresh candidate ideas" in prompt:
            return {"ideas": [{"topic": "Tiny rituals", "angle": "ordinary habits as secret upgrades"}]}
        return _draft()

    monkeypatch.setattr("app.cards.generator.llm.get_settings", _settings)
    monkeypatch.setattr("app.cards.generator.llm._call_llm", fake_call)

    result = asyncio.run(generate_llm_content("topic", "B1", "Participant 1 likes tea"))

    assert result["main_content"]["topic"] == "Tiny rituals that make ordinary days better"
    assert [q["level"] for q in result["main_content"]["sub_questions"]] == ["easy", "medium", "hard"]
    assert result["suggested_activity_id"] == "alias"
    assert result["_generation_meta"]["model"] == "Azati Smart"
    assert len(calls) == 2


def test_generate_grounded_debate_keeps_bank_payload(monkeypatch):
    async def fake_call(prompt, **kwargs):
        if "Generate 3 fresh candidate ideas" in prompt:
            return {"ideas": [{"topic": "Flexible work", "angle": "choice under constraints"}]}
        draft = _draft()
        draft["main_content"]["type_specific_payload"] = {
            "statement": "The model changed the premise.",
            "sides": ["Yes", "No"],
        }
        return draft

    bank_payload = {
        "statement": "Remote work makes small teams more creative.",
        "sides": ["Remote-first", "Office-first"],
    }
    monkeypatch.setattr("app.cards.generator.llm.get_settings", _settings)
    monkeypatch.setattr("app.cards.generator.llm._call_llm", fake_call)

    result = asyncio.run(
        generate_llm_content("debate", "B1", "ctx", bank_payload=bank_payload)
    )

    payload = result["main_content"]["type_specific_payload"]
    assert payload["statement"] == "Remote work makes small teams more creative."
    assert payload["sides"] == ["Remote-first", "Office-first"]


def test_generate_repairs_invalid_first_draft(monkeypatch):
    calls = []

    async def fake_call(prompt, **kwargs):
        calls.append(prompt)
        if "Generate 3 fresh candidate ideas" in prompt:
            return {"ideas": [{"topic": "A repairable idea", "angle": "fix the structure"}]}
        if len(calls) == 2:
            return {"main_content": {"topic": "Incomplete"}}
        return _draft()

    async def fake_sleep(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.cards.generator.llm.get_settings", _settings)
    monkeypatch.setattr("app.cards.generator.llm._call_llm", fake_call)
    monkeypatch.setattr("app.cards.generator.llm.asyncio.sleep", fake_sleep)

    result = asyncio.run(generate_llm_content("topic", "B1", "ctx"))

    assert result is not None
    assert len(calls) == 3
    assert "failed validation" in calls[-1]


def test_grounded_type_without_bank_payload_falls_back(monkeypatch):
    calls = []

    async def fake_call(prompt, **kwargs):
        calls.append(prompt)
        return _draft()

    monkeypatch.setattr("app.cards.generator.llm.get_settings", _settings)
    monkeypatch.setattr("app.cards.generator.llm._call_llm", fake_call)

    result = asyncio.run(generate_llm_content("debate", "B1", "ctx"))

    assert result is None
    assert calls == []
