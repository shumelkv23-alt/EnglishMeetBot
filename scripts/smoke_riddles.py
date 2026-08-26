"""Смоук-тест «Riddles»: целостность банка + поток + LLM-судья."""
import asyncio
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.services import riddles
from app.services.riddles_bank import RIDDLES, random_riddle
from app.services.games_llm import judge_riddle_answer
from app.database import AsyncSessionLocal
from app.services.onboarding import get_or_create_profile
from app.services import games


def test_bank():
    riddles_seen = set()
    answers_seen = set()
    for r in RIDDLES:
        assert r["riddle"].strip() and r["answer"].strip(), r
        assert r["riddle"] not in riddles_seen, f"дубль загадки: {r['riddle']}"
        assert r["answer"] not in answers_seen, f"дубль ответа: {r['answer']}"
        assert "hint" in r, f"нет подсказки: {r['riddle']}"
        riddles_seen.add(r["riddle"])
        answers_seen.add(r["answer"])
    print(f"BANK OK: {len(RIDDLES)} загадок, все уникальны, подсказки есть")


def test_normalize():
    n = riddles._normalize
    assert n("A piano") == n("piano")
    assert n("The Future") == n("future")
    assert n("  an  EGG!! ") == n("egg")
    print("NORMALIZE OK: артикли/регистр/знаки снимаются")


async def main():
    test_bank()
    test_normalize()

    # Разовый LLM-судья (синоним должен засчитаться) — печатаем, не ассертим.
    try:
        print("judge('keyboard' vs 'a piano') ->", await judge_riddle_answer(
            "What has keys but can't open locks?", "a piano", "keyboard"))
    except Exception as e:
        print("LLM judge недоступен:", e)

    ts = int(time.time())
    space = f"smoke_riddles_{ts}"
    wid = f"users/smoke_riddles_{ts}"
    async with AsyncSessionLocal() as db:
        profile = await get_or_create_profile(
            db, workspace_user_id=wid, email=f"smoke.riddles.{ts}@example.com",
            display_name="Smoke Riddles",
        )
        start = await riddles.start(db, space, profile)
        assert "cardsV2" in start, "start должен вернуть карточку"
        print("START OK ->", start["cardsV2"][0]["card"]["header"]["title"])

        active = await games.get_active_game(db, space)
        assert active is not None and active.game_type == "riddles"
        gid = active.id
        state = active.state
        answer = state["answer"]
        print("  riddle:", state["riddle"])
        print("  answer:", answer)

        # точное совпадение (без LLM)
        r1 = await riddles.check(db, gid, profile, answer)
        assert "cardsV2" in r1
        print("CORRECT OK ->", r1["cardsV2"][0]["card"]["header"]["title"])

        # пустой ввод
        r2 = await riddles.check(db, gid, profile, "")
        print("EMPTY OK ->", r2.get("text"))

        # подсказка
        r3 = await riddles.hint(db, gid, profile)
        print("HINT OK ->", r3.get("text"))

        # сдача
        r4 = await riddles.reveal(db, gid, profile)
        assert "cardsV2" in r4
        print("REVEAL OK ->", r4["cardsV2"][0]["card"]["header"]["title"])

        # следующая загадка
        r5 = await riddles.next_riddle(db, gid, profile)
        assert "cardsV2" in r5
        print("NEXT OK ->", r5["cardsV2"][0]["card"]["header"]["subtitle"])

        # финиш
        r6 = await riddles.finish(db, gid, profile)
        assert "cardsV2" in r6
        print("FINISH OK ->", r6["cardsV2"][0]["card"]["header"]["subtitle"])

    print("ALL GOOD ✅")


if __name__ == "__main__":
    asyncio.run(main())
