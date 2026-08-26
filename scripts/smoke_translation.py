"""Смоук-тест игры «Переведи-ка» на реальной БД (space уникальный)."""
import asyncio
import time

from app.database import AsyncSessionLocal
from app.services.onboarding import get_or_create_profile
from app.services import translation, games


async def main():
    space = f"smoke_translation_{int(time.time())}"
    wid = f"users/smoke_translation_{int(time.time())}"
    async with AsyncSessionLocal() as db:
        profile = await get_or_create_profile(
            db, workspace_user_id=wid, email="smoke.translation@example.com",
            display_name="Smoke Translation",
        )
        start = await translation.start_translation(db, space, profile)
        assert "cardsV2" in start, f"start должен вернуть карточку, got {start.keys()}"
        print("START OK ->", start["cardsV2"][0]["card"]["header"]["subtitle"])

        active = await games.get_active_game(db, space)
        assert active is not None and active.game_type == "translation", "нет активной партии"
        gid = active.id
        state = active.state
        print("state:", {k: state.get(k) for k in ("direction", "source", "target", "streak", "total")})

        # wrong answer
        wrong = await translation.check(db, gid, profile, "zzz no such thing")
        assert "cardsV2" in wrong, "wrong должен вернуть карточку результата"
        print("WRONG OK ->", wrong["cardsV2"][0]["card"]["header"]["title"])

        # correct answer (exact reference)
        right = await translation.check(db, gid, profile, state["target"])
        assert "cardsV2" in right, "right должен вернуть карточку результата"
        print("RIGHT OK ->", right["cardsV2"][0]["card"]["header"]["title"])

        # next round preserves streak
        nxt = await translation.next_round(db, gid, profile)
        assert "cardsV2" in nxt, "next должен вернуть новую карточку"
        print("NEXT OK ->", nxt["cardsV2"][0]["card"]["header"]["subtitle"])

        # finish
        fin = await translation.finish(db, gid, profile)
        assert "cardsV2" in fin, "finish должен вернуть итог"
        print("FINISH OK ->", fin["cardsV2"][0]["card"]["sections"][0]["widgets"][0]["textParagraph"]["text"].replace("\n", " | "))

    print("ALL GOOD ✅")


if __name__ == "__main__":
    asyncio.run(main())
