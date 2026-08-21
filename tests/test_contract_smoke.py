# tests/test_contract_smoke.py
# Смоук-тест контракта: проверяет, что окружение собрано и общие модули
# импортируются/конструируются без бота, сети и БД.
from datetime import datetime, timedelta, timezone

from app.messaging import send_message
from app.schemas import Activity, MeetingInstance, MeetingStatus, MessagePayload, Slot, WeeklyAnswer


def test_domain_models_construct():
    now = datetime.now(timezone.utc)
    inst = MeetingInstance(
        id="m1",
        week_start=now,
        status=MeetingStatus.VOTING,
        slots=[Slot(id="s1", day="Wed", time="19:00", votes=["users/a"])],
        deadline=now + timedelta(hours=24),
    )
    assert inst.final_slot_id is None

    answer = WeeklyAnswer(user_id="users/u1", question_id="q1", answer_text="Дюна", week_id="w1")
    assert answer.answer_text == "Дюна"

    activity = Activity(type="digest", content={"kind": "digest", "items": []})
    assert activity.type == "digest"


def test_send_message_stub_does_not_raise():
    send_message("users/u1", MessagePayload(text="привет", card=None))