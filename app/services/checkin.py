"""Self-check-in окно ±N минут вокруг встречи (REQ-6.2, REQ-9.6)."""
from datetime import datetime, timedelta


def checkin_window(
    scheduled_start: datetime,
    scheduled_end: datetime | None = None,
    window_min: int = 15,
) -> tuple[datetime, datetime]:
    """Окно «Я на встрече ✅»: вся встреча + window_min минут после её конца.

    Открывается в начале встречи; закрывается через window_min после scheduled_end.
    Если scheduled_end не передан — считаем встречу длиной 60 минут.
    """
    end = scheduled_end or (scheduled_start + timedelta(minutes=60))
    return (scheduled_start, end + timedelta(minutes=window_min))


def is_within_window(now: datetime, open_at: datetime, close_at: datetime) -> bool:
    return open_at <= now <= close_at


def job_ids(instance_id: str) -> dict:
    """id джобов открытия/закрытия окна."""
    return {"open": f"checkin_open_{instance_id}", "close": f"checkin_close_{instance_id}"}


def build_checkin_card(instance_id: str, action_url: str = "") -> dict:
    """Карточка с кнопкой «Я на встрече ✅» (для отправки при открытии окна).

    action_url — URL эндпоинта. В режиме Workspace Add-on кнопка доставляет клик
    только если action.function = URL (метод приходит через parameters["method"]).
    """
    return {
        "cardsV2": [
            {
                "cardId": "checkin",
                "card": {
                    "header": {"title": "Meeting starting? 🎉", "subtitle": "Check in to earn points"},
                    "sections": [
                        {
                            "widgets": [
                                {
                                    "buttonList": {
                                        "buttons": [
                                            {
                                                "text": "I'm at the meeting ✅",
                                                "onClick": {
                                                    "action": {
                                                        "function": action_url or "checkin_submit",
                                                        "parameters": [
                                                            {"key": "method", "value": "checkin_present"},
                                                            {"key": "instance", "value": str(instance_id)},
                                                        ],
                                                    }
                                                },
                                            },
                                            {
                                                "text": "Couldn't make it 😕",
                                                "onClick": {
                                                    "action": {
                                                        "function": action_url or "checkin_submit",
                                                        "parameters": [
                                                            {"key": "method", "value": "checkin_absent"},
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

from app.models import Attendance, Config, MeetingInstance as MeetingORM, Profile

logger = logging.getLogger(__name__)


async def submit_checkin(db: AsyncSession, profile: Profile, instance_id: int, window_min: int | None = None) -> dict:
    """Записать self-check-in, если в окне встречи; начислить баллы за присутствие.

    window_min берётся из config['checkin_window_minutes'], если не передан явно.
    Возвращает {'ok', 'within', 'points'}.
    """
    meeting = (
        await db.execute(select(MeetingORM).where(MeetingORM.id == instance_id, MeetingORM.status == "scheduled"))
    ).scalar_one_or_none()
    if meeting is None:
        return {"ok": False, "reason": "no_meeting", "points": 0}

    if window_min is None:
        cfg = (
            await db.execute(select(Config).where(Config.key == "checkin_window_minutes"))
        ).scalar_one_or_none()
        window_min = int(cfg.value or 15) if cfg is not None else 15

    open_at, close_at = checkin_window(meeting.scheduled_start, meeting.scheduled_end, window_min)
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

    points = 0
    if within:
        from app.services.leaderboard import award_attendance

        points = await award_attendance(db, profile.id, instance_id)

    await db.commit()
    logger.info("checkin_submitted profile=%s instance=%s within=%s points=%s", profile.id, instance_id, within, points)
    return {"ok": True, "within": within, "points": points}


async def submit_absent_checkin(db: AsyncSession, profile: Profile, instance_id: int, window_min: int | None = None) -> dict:
    """Записать «не был на встрече» (self_checkin, status=absent, без баллов).

    Отдельная кнопка от «Я на встрече ✅»; окно не требуется — отсутствие можно
    отметить в любой момент. Баллы не начисляются.
    """
    meeting = (
        await db.execute(select(MeetingORM).where(MeetingORM.id == instance_id, MeetingORM.status == "scheduled"))
    ).scalar_one_or_none()
    if meeting is None:
        return {"ok": False, "reason": "no_meeting"}

    now = datetime.now(timezone.utc)
    within = False
    if window_min is None:
        cfg = (
            await db.execute(select(Config).where(Config.key == "checkin_window_minutes"))
        ).scalar_one_or_none()
        window_min = int(cfg.value or 15) if cfg is not None else 15
    open_at, close_at = checkin_window(meeting.scheduled_start, meeting.scheduled_end, window_min)
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
            status="absent",
            checkin_attempted_at=now,
            is_within_window=within,
        )
        db.add(attendance)
    else:
        attendance.checkin_attempted_at = now
        attendance.is_within_window = within
        attendance.status = "absent"

    await db.commit()
    logger.info("absent_checkin_submitted profile=%s instance=%s", profile.id, instance_id)
    return {"ok": True, "within": within, "points": 0}