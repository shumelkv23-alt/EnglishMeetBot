"""Смоук-тест «Words of Wonders»: целостность банка + поток + LLM-бонус."""
import asyncio
import time
from collections import Counter

from app.services import words_of_wonders as wow
from app.services.words_of_wonders_bank import PUZZLES
from app.services.games_llm import is_real_word
from app.database import AsyncSessionLocal
from app.services.onboarding import get_or_create_profile
from app.services import games


def test_bank():
    seen = set()
    for p in PUZZLES:
        letters = "".join(sorted(p["letters"]))
        assert letters not in seen, f"дубль букв {letters}"
        seen.add(letters)
        assert 6 <= len(letters) <= 7 and letters.isalpha()
        assert len(p["words"]) == len(set(p["words"])), f"дубль слов в {letters}"
        for w in p["words"]:
            assert len(w) >= 3, f"{letters}: '{w}' <3"
            assert not (Counter(w) - Counter(letters)), f"{letters}: '{w}' не подслово"
    print(f"BANK OK: {len(PUZZLES)} puzzles, все слова валидны")


async def test_llm():
    print("is_real_word('apple') ->", await is_real_word("apple"))
    print("is_real_word('zzzzz') ->", await is_real_word("zzzzz"))


async def main():
    test_bank()
    await test_llm()

    ts = int(time.time())
    space = f"smoke_wow_{ts}"
    wid = f"users/smoke_wow_{ts}"
    async with AsyncSessionLocal() as db:
        profile = await get_or_create_profile(
            db, workspace_user_id=wid, email=f"smoke.wow.{ts}@example.com",
            display_name="Smoke Wow",
        )
        start = await wow.start(db, space, profile)
        assert "cardsV2" in start, "start должен вернуть карточку"
        print("START OK ->", start["cardsV2"][0]["card"]["header"]["subtitle"])

        active = await games.get_active_game(db, space)
        assert active is not None and active.game_type == "words_of_wonders"
        gid = active.id
        state = active.state
        print("  letters:", state["letters"], "answers:", len(state["answers"]))

        # основное слово
        answer = state["answers"][0]
        r1 = await wow.check(db, gid, profile, answer)
        assert "cardsV2" in r1
        print("TARGET OK ->", r1.get("text"))

        # повтор
        r2 = await wow.check(db, gid, profile, answer)
        print("DUP OK ->", r2.get("text"))

        # слово не из букв
        r3 = await wow.check(db, gid, profile, "zzzz")
        print("BAD OK ->", r3.get("text"))

        # бонус: реальное слово из букв, не в банке
        candidates = ["the", "and", "you", "for", "are", "but", "not", "all", "can",
                      "get", "has", "her", "him", "his", "how", "man", "men", "new",
                      "now", "old", "see", "two", "way", "who", "day", "eat", "out",
                      "own", "yes", "age", "arm", "art", "end", "era", "red", "run",
                      "ran", "rat", "mat", "met", "pan", "pen", "pet", "tap", "lie",
                      "west", "test", "time", "mine", "menu", "tune", "item", "mute",
                      "unit", "into", "sat", "ton", "son", "turn", "tour", "your",
                      "out", "cut", "cry", "toy", "try", "rice", "ripe", "true",
                      "trip", "cup", "ice", "pie", "pit", "put", "epic", "cute", "price"]
        answers = set(state["answers"])
        bonus_word = next(
            (w for w in candidates if len(w) >= 3 and wow._can_make(w, state["letters"]) and w not in answers),
            None,
        )
        if bonus_word:
            r4 = await wow.check(db, gid, profile, bonus_word)
            print(f"BONUS OK ({bonus_word}) ->", r4.get("text"))
        else:
            print("BONUS SKIP (нет подходящего кандидата)")

        # сдаться
        rev = await wow.reveal(db, gid, profile)
        assert "cardsV2" in rev, "reveal должен вернуть итог"
        print("REVEAL OK ->", rev["cardsV2"][0]["card"]["header"]["title"])

        # новый пазл
        new = await wow.new_game(db, gid, profile)
        assert "cardsV2" in new, "new_game должен вернуть карточку"
        print("NEW OK ->", new["cardsV2"][0]["card"]["header"]["subtitle"])

    print("ALL GOOD ✅")


if __name__ == "__main__":
    asyncio.run(main())
