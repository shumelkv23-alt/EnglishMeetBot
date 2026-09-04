# tests/test_weekly_poll_past_day.py
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.services.weekly_poll import build_weekly_poll_card


def test_build_card_hides_buttons_for_past_days():
    # сегодня — среда (2), 09:00; Пн/Вт (0,1) — прошедшие
    wed_9 = datetime(2024, 1, 3, 9, 0, tzinfo=timezone.utc)
    card = build_weekly_poll_card([0, 1, 2, 3], ["15:00"], "aud", counts={}, today_dow=2, now=wed_9)
    sections = card["cardsV2"][0]["card"]["sections"]
    assert not sections[0]["widgets"][0].get("buttonList", {}).get("buttons")
    assert not sections[1]["widgets"][0].get("buttonList", {}).get("buttons")
    assert sections[2]["widgets"][0]["buttonList"]["buttons"]


def test_build_card_today_defaults_to_app_timezone():
    now = datetime.now(ZoneInfo("Europe/Minsk"))
    today = now.weekday()
    card = build_weekly_poll_card([0, 1, 2, 3, 4, 5, 6], ["15:00"], "aud")
    sections = card["cardsV2"][0]["card"]["sections"]
    for i, s in enumerate(sections):
        buttons = s["widgets"][0].get("buttonList", {}).get("buttons")
        closed = i < today or (i == today and now.hour >= 14)
        if closed:
            assert not buttons  # прошедшие и сегодня после 14:00 — без кнопок
        else:
            assert buttons
