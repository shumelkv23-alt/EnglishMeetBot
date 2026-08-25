import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.services.briefing import briefing_at, briefing_job_id, build_briefing_card
from app.services.briefing.generator import generate_briefing

APP_TZ = ZoneInfo(get_settings().app_timezone)


def test_briefing_at_subtracts_lead():
    start = datetime(2026, 8, 26, 15, 0, tzinfo=timezone.utc)
    assert briefing_at(start, 60) == start - timedelta(minutes=60)


def test_briefing_job_id():
    assert briefing_job_id("42") == "briefing_42"


def test_build_briefing_card_structure():
    card = build_briefing_card(
        {
            "topic": "AI at work",
            "statements": ["AI replaces routine tasks.", "Creativity stays human."],
            "phrases": ["In my opinion, …", "That's a good point."],
            "news": ["News one", "News two", "News three"],
        },
        scheduled_start=datetime(2026, 8, 26, 15, 0, tzinfo=APP_TZ),
    )
    entry = card["cardsV2"][0]
    assert entry["cardId"] == "meetingBriefing"
    c = entry["card"]
    assert c["header"]["title"] == "Meeting brief"
    assert c["header"]["imageType"] == "CIRCLE"
    assert "15:00" in c["header"]["subtitle"]

    by_header = {s.get("header", ""): s["widgets"] for s in c["sections"]}
    assert "🎯 Topic" in by_header
    assert "💬 Discussion statements" in by_header
    assert "💡 Useful phrases" in by_header
    assert "📰 In the news" in by_header

    topic_widget = by_header["🎯 Topic"][0]["decoratedText"]
    assert topic_widget["text"] == "AI at work"
    assert topic_widget["topLabel"] == "Today's theme"

    st_widgets = by_header["💬 Discussion statements"]
    assert len(st_widgets) == 2
    assert st_widgets[0]["decoratedText"]["topLabel"] == "Statement 1"

    ph_widgets = by_header["💡 Useful phrases"]
    assert len(ph_widgets) == 2
    assert all(w["decoratedText"]["text"].startswith("💬 ") for w in ph_widgets)

    nw_widgets = by_header["📰 In the news"]
    assert len(nw_widgets) == 3
    assert all(w["decoratedText"]["text"].startswith("📌 ") for w in nw_widgets)


def test_generate_briefing_fallback_without_key(monkeypatch):
    fake_settings = SimpleNamespace(llm_api_key="", llm_games_model="m/x", llm_base_url="https://t.local")
    monkeypatch.setattr("app.services.briefing.generator.get_settings", lambda: fake_settings)
    b = asyncio.run(generate_briefing("ctx"))
    assert b["topic"]
    assert len(b["statements"]) == 2
    assert len(b["news"]) == 3
    assert len(b["phrases"]) == 5


def test_generate_briefing_parses_llm_json(monkeypatch):
    fake_settings = SimpleNamespace(llm_api_key="sk-test", llm_games_model="m/x", llm_base_url="https://t.local")
    monkeypatch.setattr("app.services.briefing.generator.get_settings", lambda: fake_settings)

    def fake_post(url, **kwargs):
        class R:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                '{"topic": "AI at work", '
                                '"statements": ["AI replaces routine tasks.", "Creativity stays human."], '
                                '"news": ["n1", "n2", "n3"], '
                                '"phrases": ["p1", "p2", "p3", "p4", "p5"]}'
                            ),
                        }
                    ]
                }

        return R()

    monkeypatch.setattr("app.services.briefing.generator.requests.post", fake_post)
    b = asyncio.run(generate_briefing("ctx"))
    assert b["topic"] == "AI at work"
    assert b["statements"] == ["AI replaces routine tasks.", "Creativity stays human."]
    assert b["news"] == ["n1", "n2", "n3"]
    assert b["phrases"] == ["p1", "p2", "p3", "p4", "p5"]


def test_generate_briefing_uses_fallback_phrases_when_llm_omits_them(monkeypatch):
    fake_settings = SimpleNamespace(llm_api_key="sk-test", llm_games_model="m/x", llm_base_url="https://t.local")
    monkeypatch.setattr("app.services.briefing.generator.get_settings", lambda: fake_settings)

    def fake_post(url, **kwargs):
        class R:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": '{"topic": "T", "statements": ["s1", "s2"], "news": ["n1"]}',
                        }
                    ]
                }

        return R()

    monkeypatch.setattr("app.services.briefing.generator.requests.post", fake_post)
    b = asyncio.run(generate_briefing("ctx"))
    assert b["topic"] == "T"
    assert b["phrases"] == [
        "In my opinion, …",
        "I see what you mean, but …",
        "That's a good point.",
        "Could you elaborate on that?",
        "On the other hand, …",
    ]


def test_generate_briefing_falls_back_when_statements_is_string(monkeypatch):
    fake_settings = SimpleNamespace(llm_api_key="sk-test", llm_games_model="m/x", llm_base_url="https://t.local")
    monkeypatch.setattr("app.services.briefing.generator.get_settings", lambda: fake_settings)

    def fake_post(url, **kwargs):
        class R:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": '{"topic": "T", "statements": "A and B", "news": ["n1"], "phrases": ["p1"]}',
                        }
                    ]
                }

        return R()

    monkeypatch.setattr("app.services.briefing.generator.requests.post", fake_post)
    b = asyncio.run(generate_briefing("ctx"))
    # Строка вместо списка → фолбэк, а не посимвольный мусор.
    assert b["topic"] == "Life and interests"
    assert b["statements"][0] == "Small daily habits change our lives more than big decisions."


def test_build_context_anonymizes_name():
    from app.services.briefing.briefing import _build_context

    anon = SimpleNamespace(user_name="Alice Smith", english_level="B1", anonymize_answers=True)
    named = SimpleNamespace(user_name="Bob Jones", english_level="A2", anonymize_answers=False)
    profiles = {1: anon, 2: named}
    answers = [
        SimpleNamespace(profile_id=1, answer_text="I love travel"),
        SimpleNamespace(profile_id=2, answer_text="I like movies"),
    ]
    ctx = _build_context(profiles, answers)
    assert "Alice Smith" not in ctx
    assert "Bob Jones" in ctx
    assert "participant" in ctx
    assert "I love travel" in ctx
    assert "I like movies" in ctx
