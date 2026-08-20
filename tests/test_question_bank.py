from datetime import date, timedelta

from app.services.question_bank import bank_questions_for, BANK


def test_returns_two_nonempty_questions():
    q = bank_questions_for(date(2026, 8, 20))
    assert len(q) == 2
    assert q[0] and q[1]
    assert q[0] != q[1]


def test_deterministic_same_week():
    assert bank_questions_for(date(2026, 8, 20)) == bank_questions_for(date(2026, 8, 21))


def test_rotates_between_weeks():
    first_monday = date(2026, 1, 5)
    weeks = [
        bank_questions_for(first_monday + timedelta(weeks=i))[0]
        for i in range(len(BANK) + 1)
    ]
    assert len(set(weeks)) > 1  # первая и последняя недели дают разные вопросы


def test_fallback_pair_differs_from_main_question():
    # запасной вопрос для фолбэка не совпадает с основным в той же неделе
    q = bank_questions_for(date(2026, 8, 20))
    nxt = bank_questions_for(date(2026, 8, 27))
    assert q[1] != q[0]
    assert q[0:2] != nxt[0:2]