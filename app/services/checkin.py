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


def build_checkin_card(instance_id: str, action_url: str = "") -> dict:
    """Карточка с кнопкой «Я на встрече ✅» (для отправки при открытии окна).

    action_url — URL вебхука (chat_app_audience): в Chat Card API action.function
    это URL, а не имя функции (метод приходит через parameters).
    """
    return {
        "cardsV2": [
            {
                "cardId": "checkin",
                "card": {
                    "header": {"title": "Встреча началась? 🎉", "subtitle": "Отметься, чтобы получить баллы"},
                    "sections": [
                        {
                            "widgets": [
                                {
                                    "buttonList": {
                                        "buttons": [
                                            {
                                                "text": "Я на встрече ✅",
                                                "onClick": {
                                                    "action": {
                                                        "function": action_url or "checkin_submit",
                                                        "parameters": [
                                                            {"key": "method", "value": "checkin_present"},
                                                            {"key": "instance", "value": str(instance_id)},
                                                        ],
                                                    }
                                                },
                                            }
                                        ]
                                    }
                                }
                            ]
                        }
                    ],
                },
            }
        ]
    }


# --- БД-часть ---
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Attendance, MeetingInstance as MeetingORM, Profile

logger = logging.getLogger(__name__)


async def submit_checkin(db: AsyncSession, profile: Profile, instance_id: int, window_min: int = 15) -> dict:
    """Записать self-check-in, только если сейчас в окне встречи (REQ-9.6)."""
    meeting = (
        await db.execute(select(MeetingORM).where(MeetingORM.id == instance_id, MeetingORM.status == "scheduled"))
    ).scalar_one_or_none()
    if meeting is None:
        return {"ok": False, "reason": "no_meeting"}

    open_at, close_at = checkin_window(meeting.scheduled_start, window_min)
    now = datetime.now(timezone.utc)
    within = is_within_window(now, open_at, close_at)

    attendance = (
        await db.execute(
            select(Attendance).where(
                Attendance.profile_id == profile.id,
                Attendance.meeting_instance_id == instance_id,
            )
        )
    ).scalar_one_or_none()
    if attendance is None:
        attendance = Attendance(
            profile_id=profile.id,
            meeting_instance_id=instance_id,
            source="self_checkin",
            status="present" if within else "pending",
            checkin_attempted_at=now,
            is_within_window=within,
        )
        db.add(attendance)
    else:
        attendance.checkin_attempted_at = now
        attendance.is_within_window = within
        if within:
            attendance.status = "present"

    await db.commit()
    logger.info("checkin_submitted profile=%s instance=%s within=%s", profile.id, instance_id, within)
    return {"ok": True, "within": within}