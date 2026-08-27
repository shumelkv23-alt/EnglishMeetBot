"""Разовый прогон полного цикла бота для сегодняшнего дня (в реальный Google Chat).

Этапы: окружение → онбординг → вопросы недели → опрос недели → голосование →
кворум → приглашение → карточка занятия → чек-ин.

Каждый этап вызывает ту же функцию, что и соответствующий джоб scheduler'а,
и проверяет результат. В конце — сводка OK/FAIL по этапам.

Если встреча на сегодня уже создана (повторный запуск), этап «кворум» берёт её,
а не падает.

Запуск: ./venv/Scripts/python -m scripts.run_full_cycle
"""
import sys
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import Attendance, MeetingInstance

# Три реальных акка + один тестовый (для кворума 4).
REAL_USERS = [
    "users/111473858428808568928",  # profile 1
    "users/114377988499229847823",  # profile 2
    "users/106097977256159874444",  # profile 3
]
TEST_USER = "users/test_cycle_4"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    """Зафиксировать результат этапа и вывести его."""
    results.append((name, ok, detail))
    print(f"[{'OK' if ok else 'FAIL'}] {name}: {detail}")


async def main() -> None:
    from app.services.onboarding import get_or_create_profile
    from app.services.weekly_poll import (
        DAYS,
        active_weekly_poll,
        ensure_weekly_poll,
        finalize_day,
        get_or_create_config,
        send_weekly_poll_card,
        submit_poll,
    )

    tz = ZoneInfo(get_settings().app_timezone)
    today_dow = datetime.now(tz).weekday()
    print(f"=== Прогон цикла: {DAYS[today_dow]} (day={today_dow}) ===\n")

    # 1. Окружение
    async with AsyncSessionLocal() as db:
        space_id = (await get_or_create_config(db, "space_id", "")).value or ""
    check("окружение", bool(space_id), f"space_id={'найден' if space_id else 'ПУСТО'}")
    if not space_id:
        return

    # 2. Онбординг — заводим тестовый профиль
    async with AsyncSessionLocal() as db:
        p = await get_or_create_profile(db, workspace_user_id=TEST_USER, email="test_cycle@test.local")
        await db.commit()
        test_id = p.id
    check("онбординг", test_id is not None, f"профиль id={test_id}")

    # 3. Вопросы недели
    async with AsyncSessionLocal() as db:
        from app.services.weekly_questions import send_weekly_questions

        sent_q = await send_weekly_questions(db)
    check("вопросы недели", sent_q > 0, f"разослано={sent_q}")

    # 4. Опрос недели
    async with AsyncSessionLocal() as db:
        poll = await ensure_weekly_poll(db)
        await send_weekly_poll_card(db, poll)
        poll_id = poll.id
    check("опрос недели", poll_id is not None, f"poll_id={poll_id}")

    # 5. Голосование — 4 голоса за сегодня, слот 15:00
    voters = REAL_USERS + [TEST_USER]
    voted = 0
    async with AsyncSessionLocal() as db:
        form = {
            "day": {"stringInputs": {"value": [str(today_dow)]}},
            "time": {"stringInputs": {"value": ["15:00"]}},
        }
        for uid in voters:
            profile = await get_or_create_profile(db, workspace_user_id=uid)
            res = await submit_poll(db, profile, form)
            if res.get("ok"):
                voted += 1
    check("голосование", voted >= 4, f"проголосовало={voted}/4")

    # 6. Кворум + приглашение (создать встречу, либо взять уже существующую)
    meeting_id = None
    async with AsyncSessionLocal() as db:
        from app.services.invites import handle_time_finalized

        poll = await active_weekly_poll(db)
        result = await finalize_day(db, poll, today_dow) if poll else None
        if result is not None:
            meeting, time_str = result
            meeting_id = meeting.id
            await handle_time_finalized(
                db, meeting.id, DAYS[today_dow], time_str, scheduled_start=meeting.scheduled_start,
            )
            check("кворум+приглашение", True, f"встреча создана id={meeting_id} на {time_str}")
        elif poll is not None:
            day = poll.poll_date + timedelta(days=today_dow)
            day_start = datetime.combine(day, time.min, tzinfo=timezone.utc)
            existing = (
                await db.execute(
                    select(MeetingInstance).where(
                        MeetingInstance.poll_id == poll.id,
                        MeetingInstance.scheduled_start >= day_start,
                        MeetingInstance.scheduled_start < day_start + timedelta(days=1),
                    )
                )
            ).scalars().first()
            if existing is not None:
                meeting_id = existing.id
                check("кворум+приглашение", True, f"встреча уже есть id={meeting_id}")
            else:
                check("кворум+приглашение", False, "квота не набрана")
        else:
            check("кворум+приглашение", False, "нет опроса")

    # 7. Карточка занятия
    if meeting_id:
        from app.cards.service import send_card

        await send_card(str(meeting_id))
        check("карточка занятия", True, f"meeting={meeting_id}")
    else:
        check("карточка занятия", False, "нет встречи")

    # 8. Чек-ин — фиксируем attendance участников
    async with AsyncSessionLocal() as db:
        from app.services.checkin import submit_checkin

        checked = 0
        for uid in voters:
            profile = await get_or_create_profile(db, workspace_user_id=uid)
            r = await submit_checkin(db, profile, meeting_id) if meeting_id else {"ok": False}
            if r.get("ok"):
                checked += 1
        n_att = (
            await db.execute(
                select(func.count())
                .select_from(Attendance)
                .where(Attendance.meeting_instance_id == meeting_id)
            )
        ).scalar_one() if meeting_id else 0
    check("чек-ин", n_att >= 1, f"чекинулось={checked}, attendance-записей={n_att}")

    # Сводка
    failed = [r for r in results if not r[1]]
    print("\n=== СВОДКА ===")
    for name, ok, detail in results:
        print(f"  [{'OK' if ok else 'FAIL'}] {name}: {detail}")
    print(f"\nИтого: {len(results) - len(failed)}/{len(results)} OK")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
