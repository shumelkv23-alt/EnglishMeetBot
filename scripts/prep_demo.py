"""Подготовка демо fast_cycle: включить режим, завести 3 тестовых голоса за день.

Готовит сценарий «3 голоса уже стоят, зритель добавляет решающий 4-й»:
- включает fast_cycle (config['fast_cycle'] = true) и паузу между этапами;
- создаёт активный опрос недели (если его нет);
- заводит 3 тестовых профиля users/demo_1..3 и голосует ими за целевой день/время.

Идемпотентен: повторный запуск не плодит дубли (голоса перезаписываются,
профили/опрос переиспользуются).

Запуск:
    venv/Scripts/python.exe -m scripts.prep_demo --space "spaces/XXXX"
    venv/Scripts/python.exe -m scripts.prep_demo --space "spaces/XXXX" --step 30 --day 2 --time 15:00

Аргументы:
    --space  имя группы Google Chat (обязательно; иначе бот никуда не пишет)
    --step   пауза между этапами fast_cycle, сек (по умолчанию 60)
    --day    день недели 0=Пн..6=Вс (по умолчанию — сегодня по таймзоне приложения)
    --time   целевое время слота (по умолчанию "15:00")
"""
import argparse
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.services.onboarding import get_or_create_profile
from app.services.weekly_poll import (
    DAYS,
    ensure_weekly_poll,
    get_or_create_config,
    poll_counts,
    submit_poll,
)

DEMO_USERS = ["users/demo_1", "users/demo_2", "users/demo_3"]


async def main() -> None:
    parser = argparse.ArgumentParser(description="Подготовка демо fast_cycle")
    parser.add_argument("--space", default="", help="имя группы Google Chat (spaces/...)")
    parser.add_argument("--step", type=int, default=60, help="пауза между этапами, сек")
    parser.add_argument("--day", type=int, default=None, help="день недели 0..6")
    parser.add_argument("--time", default="15:00", help="целевое время слота")
    args = parser.parse_args()

    tz = ZoneInfo(get_settings().app_timezone)
    today_dow = datetime.now(tz).weekday()
    day = args.day if args.day is not None else today_dow
    if not (0 <= day <= 6):
        print(f"Неверный day={day} (нужно 0..6)")
        return

    async with AsyncSessionLocal() as db:
        # 1. fast_cycle on + пауза
        fc = await get_or_create_config(db, "fast_cycle", False)
        fc.value = True
        fc_step = await get_or_create_config(db, "fast_cycle_seconds", 60)
        fc_step.value = args.step
        # 2. space_id
        space_id = args.space
        if space_id:
            scfg = await get_or_create_config(db, "space_id", "")
            scfg.value = space_id
        else:
            space_id = (await get_or_create_config(db, "space_id", "")).value or ""
        await db.commit()

        # 3. опрос недели + 3 голоса за целевой день/время
        poll = await ensure_weekly_poll(db)
        form = {
            "day": {"stringInputs": {"value": [str(day)]}},
            "time": {"stringInputs": {"value": [args.time]}},
        }
        for uid in DEMO_USERS:
            profile = await get_or_create_profile(db, workspace_user_id=uid)
            await submit_poll(db, profile, form)

        _, _, counts = await poll_counts(db, poll.id)
        target_votes = counts.get((day, args.time), 0)

        print("=== Подготовка демо ===")
        print(f"день: {DAYS[day]} (dow={day}) время={args.time}")
        print(f"fast_cycle: True, пауза между этапами: {args.step}s")
        print(f"space_id: {space_id or 'ПУСТО (заполни --space!)'}")
        print(f"опрос: id={poll.id} (poll_date={poll.poll_date})")
        print(f"голосов за {DAYS[day]} {args.time}: {target_votes}/3")
        if not space_id:
            print("ВНИМАНИЕ: space_id пуст — бот не будет никуда писать.")


if __name__ == "__main__":
    asyncio.run(main())
