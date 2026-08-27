"""Юнит-тесты invites: handle_time_finalized не должен падать на создании джобов."""
from datetime import datetime, timezone

from app.services.invites import local_time_parts


def test_local_time_parts_uses_app_timezone():
    # 12:00 UTC в Europe/Minsk = 15:00 по Минску.
    day, time_ = local_time_parts(datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc))
    assert time_ == "15:00"


class _FakeDB:
    """Минимальный стаб сессии: _config_value видит scalar_one_or_none() -> None."""

    async def execute(self, _stmt):
        return self

    def scalar_one_or_none(self):
        return None


async def test_handle_time_finalized_creates_jobs_without_error(monkeypatch):
    jobs = []

    class FakeScheduler:
        def add_job(self, fn, trigger, **kwargs):
            jobs.append((fn, trigger, kwargs))

    async def _fake_schedule_card(db, instance_id, scheduled_start):
        return None

    monkeypatch.setattr("app.services.invites._scheduler", lambda: FakeScheduler())
    monkeypatch.setattr("app.services.invites.send_text", lambda *a, **k: None)
    monkeypatch.setattr("app.cards.service.schedule_card_for_meeting", _fake_schedule_card)

    from app.services.invites import handle_time_finalized

    await handle_time_finalized(
        _FakeDB(),
        "1",
        "Thu",
        "15:00",
        scheduled_start=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
    )

    # напоминание + открытие/закрытие чек-ина
    assert len(jobs) == 3, f"ожидали 3 джоба, получили {len(jobs)}"
