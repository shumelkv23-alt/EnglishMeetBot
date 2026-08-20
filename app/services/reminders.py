"""Напоминания о встрече T−1ч: расчёт времени и id джоба (REQ-5.3, REQ-9.2)."""
from datetime import datetime, timedelta


def reminder_at(scheduled_start: datetime, lead_hours: int) -> datetime:
    """Момент отправки напоминания = встреча минус lead_hours."""
    return scheduled_start - timedelta(hours=lead_hours)


def reminder_job_id(instance_id: str) -> str:
    """id джоба: перезапись при повторной постановке (REQ-9.2), не дубль."""
    return f"remind_{instance_id}"