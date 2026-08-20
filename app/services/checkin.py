"""Self-check-in окно ±N минут вокруг встречи (REQ-6.2, REQ-9.6)."""
from datetime import datetime, timedelta


def checkin_window(scheduled_start: datetime, window_min: int) -> tuple[datetime, datetime]:
    """Открытие/закрытие окна «Я на встрече ✅»."""
    return (
        scheduled_start - timedelta(minutes=window_min),
        scheduled_start + timedelta(minutes=window_min),
    )


def is_within_window(now: datetime, open_at: datetime, close_at: datetime) -> bool:
    return open_at <= now <= close_at


def job_ids(instance_id: str) -> dict:
    """id джобов открытия/закрытия окна."""
    return {"open": f"checkin_open_{instance_id}", "close": f"checkin_close_{instance_id}"}