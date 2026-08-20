"""Напоминания о встрече T−1ч: расчёт времени и id джоба (REQ-5.3, REQ-9.2)."""
from datetime import datetime, timedelta


def reminder_at(scheduled_start: datetime, lead_hours: int) -> datetime:
    """Момент отправки напоминания = встреча минус lead_hours."""
    return scheduled_start - timedelta(hours=lead_hours)


def reminder_job_id(instance_id: str) -> str:
    """id джоба: перезапись при повторной постановке (REQ-9.2), не дубль."""
    return f"remind_{instance_id}"


# --- БД-часть ---
import logging
from datetime import timezone

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import Config, MeetingInstance as MeetingORM

logger = logging.getLogger(__name__)


async def restore_reminders_on_startup() -> int:
    """Пересоздать джобы напоминаний/check-in для будущих встреч после рестарта."""
    from app.scheduler import scheduler

    if scheduler is None:
        return 0
    async with AsyncSessionLocal() as db:
        meetings = (await db.execute(
            select(MeetingORM).where(
                MeetingORM.status == "scheduled",
                MeetingORM.scheduled_start.isnot(None),
            )
        )).scalars().all()
        cfg_lead = (await db.execute(select(Config).where(Config.key == "meet_reminder_hours"))).scalar_one_or_none()
        lead_hours = int(cfg_lead.value or 1) if cfg_lead is not None else 1
        cfg_window = (await db.execute(select(Config).where(Config.key == "checkin_window_min"))).scalar_one_or_none()
        window_min = int(cfg_window.value or 15) if cfg_window is not None else 15
        cfg_space = (await db.execute(select(Config).where(Config.key == "space_id"))).scalar_one_or_none()
        space_id = cfg_space.value or "" if cfg_space is not None else ""

    from app.services.checkin import build_checkin_card, checkin_window, job_ids
    from app.services.invites import _close_checkin, _open_checkin, _send_reminder

    now = datetime.now(timezone.utc)
    restored = 0
    for m in meetings:
        remind = reminder_at(m.scheduled_start, lead_hours)
        open_at, close_at = checkin_window(m.scheduled_start, window_min)
        if remind > now:
            scheduler.add_job(_send_reminder, "date", run_date=remind, id=reminder_job_id(str(m.id)), replace_existing=True, args=[str(m.id)])
            restored += 1
        if open_at > now:
            scheduler.add_job(_open_checkin, "date", run_date=open_at, id=job_ids(str(m.id))["open"], replace_existing=True, args=[space_id, build_checkin_card(str(m.id))])
            restored += 1
        if close_at > now:
            scheduler.add_job(_close_checkin, "date", run_date=close_at, id=job_ids(str(m.id))["close"], replace_existing=True)
            restored += 1
    logger.info("reminders_restored count=%s", restored)
    return restored