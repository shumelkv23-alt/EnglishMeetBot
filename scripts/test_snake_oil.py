"""Проверка игры Snake Oil / «Змеиное масло» без Google: полный матч на реальной БД.

Заглушает отправку в чат (send/patch/dm) и судью LLM, чтобы проверить логику
раундов, счёта и победы. Создаёт временные профили и игру, в конце удаляет их.

Запуск:
    venv/Scripts/python.exe scripts/test_snake_oil.py
"""
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")
    except Exception:
        pass
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

from sqlalchemy import delete, select

from app.database import AsyncSessionLocal
from app.models import (
    Profile,
    SnakeGame,
    SnakeOffer,
    SnakePlayer,
    SnakeRound,
)
from app.services import snake_bank, snake_oil
from app.services.word_bank import PRODUCT_NOUNS, sample_product_words

# Заглушки — не ходим в реальный Google Chat и не дёргаем LLM.
_sent: list[tuple] = []
snake_oil.send_space_message = lambda *a, **k: (_sent.append(("send", a, k)) or {"name": "spaces/TEST/messages/1"})
snake_oil.patch_message = lambda *a, **k: (_sent.append(("patch", a, k)) or {})
snake_oil.find_user_dm_space = lambda *a, **k: ""
# Судья всегда выбирает товар 1 (пару игрока в solo-режиме).
snake_oil._judge_pair = lambda *a, **k: 1


async def _cleanup(db) -> None:
    test_games = (await db.execute(
        select(SnakeGame.id).where(SnakeGame.space_id == "spaces/TEST_SNAKE")
    )).scalars().all()
    for gid in test_games:
        await db.execute(delete(SnakeOffer).where(
            SnakeOffer.round_id.in_(select(SnakeRound.id).where(SnakeRound.game_id == gid))
        ))
        await db.execute(delete(SnakeRound).where(SnakeRound.game_id == gid))
        await db.execute(delete(SnakePlayer).where(SnakePlayer.game_id == gid))
        await db.execute(delete(SnakeGame).where(SnakeGame.id == gid))
    test_profiles = (await db.execute(
        select(Profile.id).where(Profile.workspace_user_id.like("users/snake_test_%"))
    )).scalars().all()
    for pid in test_profiles:
        await db.execute(delete(Profile).where(Profile.id == pid))
    await db.commit()


async def _make_profile(db, i: int) -> Profile:
    ws = f"users/snake_test_{i}"
    prof = (await db.execute(
        select(Profile).where(Profile.workspace_user_id == ws)
    )).scalar_one_or_none()
    if prof is None:
        prof = Profile(
            workspace_user_id=ws, user_email=f"snake_test_{i}@test.local", user_name=f"Тест {i}",
        )
        db.add(prof)
        await db.commit()
        await db.refresh(prof)
    return prof


async def _active_round(db, game_id: int) -> SnakeRound:
    return (await db.execute(
        select(SnakeRound).where(SnakeRound.game_id == game_id, SnakeRound.status == "active")
    )).scalars().first()


async def test_mode(db) -> None:
    """Одиночный режим «снейк тест»: игрок против бота, судья выбирает игрока."""
    print("\n== Снейк тест: ты против бота ==")
    assert snake_oil.is_test_command("снейк тест")
    assert snake_oil.is_test_command("снейк тест 4")
    assert not snake_oil.is_test_command("снейк 3")
    assert snake_oil.test_target("снейк тест") == 3
    assert snake_oil.test_target("снейк тест 4") == 4

    user = await _make_profile(db, 9)
    result = await snake_oil.setup_test_game(db, "spaces/TEST_SNAKE", user, 3)
    assert result.get("ok"), result
    game_id = result["game_id"]
    players = await snake_oil._players_of_game(db, game_id)
    assert len(players) == 2, players
    assert any(snake_oil._is_bot(p) for _, p in players), "должен быть бот"
    print(f"  игроки: {[snake_oil._display(p) for _, p in players]}")

    await snake_oil.start_game(db, game_id)
    round = await _active_round(db, game_id)
    assert round is not None
    assert snake_oil._is_bot((await db.get(Profile, round.customer_profile_id))), "покупатель — бот"

    offers = (await db.execute(
        select(SnakeOffer).where(SnakeOffer.round_id == round.id)
    )).scalars().all()
    assert len(offers) == 2, "две пары: игрок + бот"

    user_player = next((sp for sp, p in players if not snake_oil._is_bot(p)), None)
    before = user_player.score
    result = await snake_oil.solo_ready(db, round.id)
    assert result.get("ok"), result
    players = await snake_oil._players_of_game(db, game_id)
    user_player = next((sp for sp, p in players if not snake_oil._is_bot(p)), None)
    print(f"  после суда игрок: {before} -> {user_player.score}")
    assert user_player.score == before + 1, "судья выбрал игрока (товар 1)"


async def test_words() -> None:
    """Слова Snake Oil — только конкретные существительные (без глаголов/абстракций)."""
    print("\n== Банк слов (только существительные) ==")
    banned = {
        "jump", "run", "swim", "fly", "sleep", "eat", "drink", "read", "write",
        "sing", "dance", "laugh", "cry", "cook", "drive", "climb", "throw",
        "catch", "paint", "draw", "build", "break", "open", "close", "push",
        "pull", "carry", "hide", "find", "win", "lose", "think", "smile",
        "big", "small", "fast", "slow", "hot", "cold", "happy", "sad", "angry",
        "tired", "hungry", "thirsty", "old", "young", "tall", "short", "loud",
        "quiet", "clean", "dirty", "heavy", "light", "soft", "hard", "wet",
        "dry", "expensive", "cheap", "beautiful", "dangerous", "funny",
    }
    assert PRODUCT_NOUNS and len(PRODUCT_NOUNS) > 100
    assert len(set(PRODUCT_NOUNS)) == len(PRODUCT_NOUNS), "в списке есть дубликаты"
    leaked = banned & set(PRODUCT_NOUNS)
    assert not leaked, f"глаголы/абстракции попали в банк: {sorted(leaked)}"
    sample = sample_product_words(2)
    assert all(w in PRODUCT_NOUNS for w in sample)
    assert sample[0] != sample[1]
    print(f"  существительных: {len(PRODUCT_NOUNS)}, пример пары: {sample[0]} + {sample[1]}")


async def test_bank(db) -> None:
    """Проблемы подбираются под роль покупателя."""
    print("\n== Банк ролей и проблем ==")
    assert len(snake_bank.PERSONAS) == 20
    for persona in snake_bank.PERSONAS:
        problems = snake_bank.PERSONA_PROBLEMS.get(persona)
        assert problems, f"у роли {persona} должен быть свой список проблем"
        assert all(p not in snake_bank.GENERIC_PROBLEMS for p in problems), (
            f"проблемы {persona} не должны дублировать общий фолбэк"
        )
    for _ in range(20):
        p = snake_bank.random_problem("😺 Кот")
        assert p in snake_bank.PERSONA_PROBLEMS["😺 Кот"], p
    # роль без своего списка (если появится) → общий фолбэк
    assert snake_bank.random_problem("🙈 Нет в банке") in snake_bank.GENERIC_PROBLEMS
    print("  у каждой роли — свои проблемы, фолбэк работает")


async def test_full_game(db) -> None:
    """Полный матч на 3 очка: покупатели голосуют, победитель растёт до цели."""
    print("\n== Полный матч: цель 3 ==")
    assert snake_oil.parse_snake_args("снейк 3", 3) == 3
    assert snake_oil.parse_snake_args("снейк", 3) == 3
    assert snake_oil.parse_snake_args("снейк 5", 3) == 5

    result = await snake_oil.game_from_command(db, "spaces/TEST_SNAKE", "снейк 3")
    assert result.get("ok"), result
    game_id = result["game_id"]

    profiles = [await _make_profile(db, i) for i in (1, 2, 3)]
    for prof in profiles:
        await snake_oil.join_game(db, prof, game_id)
    players = await snake_oil._players_of_game(db, game_id)
    assert len(players) == 3, len(players)

    await snake_oil.start_game(db, game_id)

    # карточка раунда должна быть отправлена ОДИН раз и дальше патчиться на месте
    game = (await db.execute(select(SnakeGame).where(SnakeGame.id == game_id))).scalar_one()
    assert game.round_message_name, "карточка раунда должна сохранить имя сообщения"

    for _ in range(30):  # защита от бесконечного цикла
        game = (await db.execute(select(SnakeGame).where(SnakeGame.id == game_id))).scalar_one()
        if game.status == "finished":
            break
        round = await _active_round(db, game_id)
        assert round is not None, "нет активного раунда"
        customer = await db.get(Profile, round.customer_profile_id)
        offers = (await db.execute(
            select(SnakeOffer).where(SnakeOffer.round_id == round.id).order_by(SnakeOffer.id)
        )).scalars().all()
        assert len(offers) == 2, "у 3 игроков должно быть 2 продавца"
        # покупатель выбирает первого продавца
        result = await snake_oil.vote(db, round.id, offers[0].id, customer)
        assert result.get("ok"), result

    game = (await db.execute(select(SnakeGame).where(SnakeGame.id == game_id))).scalar_one()
    assert game.status == "finished", game.status
    players = await snake_oil._players_of_game(db, game_id)
    winner = next((p for sp, p in players if p.id == game.winner_profile_id), None)
    assert winner is not None
    winner_sp = next((sp for sp, p in players if p.id == game.winner_profile_id), None)
    print(f"  победитель: {snake_oil._display(winner)} ({winner_sp.score} очк.)")
    assert winner_sp.score >= 3


async def test_finish(db) -> None:
    """Кнопка «🏁 Закончить игру»: досрочное завершение + ближайший результат."""
    print("\n== Досрочное завершение игры ==")
    game = SnakeGame(space_id="spaces/TEST_SNAKE", status="setup", target_score=3)
    db.add(game)
    await db.flush()
    p1 = await _make_profile(db, 11)
    p2 = await _make_profile(db, 12)
    db.add(SnakePlayer(game_id=game.id, profile_id=p1.id, score=2))
    db.add(SnakePlayer(game_id=game.id, profile_id=p2.id, score=0))
    await db.commit()

    _sent.clear()
    result = await snake_oil.finish_game(db, game.id)
    assert result.get("ok"), result
    game = (await db.execute(select(SnakeGame).where(SnakeGame.id == game.id))).scalar_one()
    assert game.status == "finished"
    assert game.winner_profile_id == p1.id, "лидер — игрок с наибольшим счётом"
    summary = next((k["text"] for _, a, k in _sent if k.get("text")), "")
    assert "не доиграли" in summary, summary
    assert "Тест 11" in summary, summary
    print(f"  статус={game.status}, лидер={snake_oil._display(p1)}")
    print(f"  сообщение в группу:\n{summary}")

    result = await snake_oil.finish_game(db, game.id)
    assert not result.get("ok"), "повторное завершение должно отказать"


async def main() -> None:
    async with AsyncSessionLocal() as db:
        await _cleanup(db)

        await test_words()

        await test_bank(db)

        await test_full_game(db)
        await _cleanup(db)

        await test_mode(db)
        await _cleanup(db)

        await test_finish(db)
        await _cleanup(db)

        print("\n✅ Проверка пройдена. Временные данные удалены.")


if __name__ == "__main__":
    asyncio.run(main())
