# tests/test_weekly_poll_past_day.py
from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.weekly_poll import build_weekly_poll_card


def test_build_card_hides_buttons_for_past_days():
    # сегодня — среда (2); Пн/Вт (0,1) — прошедшие
    card = build_weekly_poll_card([0, 1, 2, 3], ["15:00"], "aud", counts={}, today_dow=2)
    sections = card["cardsV2"][0]["card"]["sections"]
    assert not sections[0]["widgets"][0].get("buttonList", {}).get("buttons")
    assert not sections[1]["widgets"][0].get("buttonList", {}).get("buttons")
    assert sections[2]["widgets"][0]["buttonList"]["buttons"]


def test_build_card_today_defaults_to_app_timezone():
    today = datetime.now(ZoneInfo("Europe/Minsk")).weekday()
    card = build_weekly_poll_card([0, 1, 2, 3, 4, 5, 6], ["15:00"], "aud")
    sections = card["cardsV2"][0]["card"]["sections"]
    for i, s in enumerate(sections):
        buttons = s["widgets"][0].get("buttonList", {}).get("buttons")
        if i < today:
            assert not buttons  # прошедшие — без кнопок
        else:
            assert buttons
