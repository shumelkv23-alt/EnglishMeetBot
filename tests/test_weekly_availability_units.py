from datetime import date

from app.services.weekly_availability import (
    build_weekly_table_card,
    day_code_of,
    monday_of,
    week_start_for_poll,
)


def test_monday_of():
    # 2026-08-25 — вторник, понедельник = 24-е
    assert monday_of(date(2026, 8, 25)) == date(2026, 8, 24)


def test_week_start_for_poll_weekday():
    assert week_start_for_poll(date(2026, 8, 25)) == date(2026, 8, 24)  # вт
    assert week_start_for_poll(date(2026, 8, 24)) == date(2026, 8, 24)  # пн


def test_week_start_for_poll_sunday_rolls_forward():
    # воскресенье 2026-08-30 → опрос на следующую неделю (пн 31-е)
    assert week_start_for_poll(date(2026, 8, 30)) == date(2026, 8, 31)


def test_day_code_of():
    assert day_code_of(date(2026, 8, 24)) == "mon"
    assert day_code_of(date(2026, 8, 25)) == "tue"
    assert day_code_of(date(2026, 8, 30)) == "sun"


def test_build_weekly_table_card_buttons():
    days = ["mon", "tue"]
    times = ["15:00", "16:00"]
    votes = {("mon", "15:00"): 2}
    scheduled = {("tue", "16:00")}
    card = build_weekly_table_card(days, times, votes, scheduled, date(2026, 8, 24), "https://x/hook")
    sections = card["cardsV2"][0]["card"]["sections"]
    assert len(sections) == 2
    mon_buttons = sections[0]["widgets"][0]["buttonList"]["buttons"]
    assert mon_buttons[0]["text"] == "15:00 (2)"
    assert mon_buttons[1]["text"] == "16:00"
    tue_buttons = sections[1]["widgets"][0]["buttonList"]["buttons"]
    assert tue_buttons[1]["text"] == "✅ 16:00"
    # все кнопки шлют method=weekly_toggle с URL эндпоинта
    for b in mon_buttons + tue_buttons:
        assert b["onClick"]["action"]["function"] == "https://x/hook"
        keys = {p["key"]: p["value"] for p in b["onClick"]["action"]["parameters"]}
        assert keys["method"] == "weekly_toggle"
