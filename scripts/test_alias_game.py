"""Проверка игры Alias без Google: полный проход партии на реальной БД.

Заглушает отправку в чат (send/patch/dm) и таймер, чтобы проверить логику
счёта, ротации команд и определения победителя. Создаёт временные профили и
игру, в конце удаляет их. Таймер «время вышло» симулируется вручную.

Запуск:
    venv/Scripts/python.exe scripts/test_alias_game.py
"""
import asyncio
import logging
import sys
from pathlib import Path

# Добавляем корень проекта в sys.path, чтобы работал запуск из любой папки.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# UTF-8 для вывода эмодзи/кириллицы в Windows-консоли.
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")
    except Exception:
        pass
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

from sqlalchemy import delete, select

from app.database import AsyncSessionLocal
from app.models import (
    Game,
    GamePlayer,
    GameRound,
    GameTeam,
    GameWordEvent,
    Profile,
)
from app.services import alias_game

# Заглушки — не ходим в реальный Google Chat и не вешаем реальный таймер.
_sent: list[tuple] = []
alias_game.send_space_message = lambda *a, **k: (_sent.append(("send", a, k)) or {"name": "spaces/TEST/messages/1"})
alias_game.patch_message = lambda *a, **k: (_sent.append(("patch", a, k)) or {})
alias_game.find_user_dm_space = lambda *a, **k: ""
alias_game._schedule_timer = lambda game, round: None
alias_game._schedule_bot_turn = lambda round_id: None


async def _cleanup(db) -> None:
    """Удалить прошлые тестовые данные (игру и профили) при наличии."""
    test_games = (await db.execute(
        select(Game.id).where(Game.space_id == "spaces/TEST_ALIAS")
    )).scalars().all()
    for gid in test_games:
        await db.execute(delete(GameWordEvent).where(
            GameWordEvent.round_id.in_(select(GameRound.id).where(GameRound.game_id == gid))
        ))
        await db.execute(delete(GameRound).where(GameRound.game_id == gid))
        await db.execute(delete(GamePlayer).where(GamePlayer.game_id == gid))
        await db.execute(delete(GameTeam).where(GameTeam.game_id == gid))
        await db.execute(delete(Game).where(Game.id == gid))
    test_profiles = (await db.execute(
        select(Profile.id).where(Profile.workspace_user_id.like("users/alias_test_%"))
    )).scalars().all()
    for pid in test_profiles:
        await db.execute(delete(Profile).where(Profile.id == pid))
    await db.commit()


async def _make_profile(db, i: int) -> Profile:
    ws = f"users/alias_test_{i}"
    prof = (await db.execute(
        select(Profile).where(Profile.workspace_user_id == ws)
    )).scalar_one_or_none()
    if prof is None:
        prof = Profile(
            workspace_user_id=ws, user_email=f"alias_test_{i}@test.local", user_name=f"Тест {i}",
        )
        db.add(prof)
        await db.commit()
        await db.refresh(prof)
    return prof


async def test_mode(db) -> None:
    """Одиночный режим «алиас тест»: ты против бота (бот отыгрывает свой ход сам)."""
    print("\n== Алиас тест: ты против бота ==")
    assert alias_game.is_test_command("алиас тест")
    assert alias_game.is_test_command("алиас тест 3")
    assert not alias_game.is_test_command("алиас 3 Красные Синие")
    assert alias_game.test_target("алиас тест") == 5
    assert alias_game.test_target("алиас тест 3") == 3

    user = await _make_profile(db, 9)  # отдельный «пользователь»
    result = await alias_game.setup_test_game(db, "spaces/TEST_ALIAS", user, 6)
    assert result.get("ok"), result
    game_id = result["game_id"]
    teams = (await db.execute(
        select(GameTeam).where(GameTeam.game_id == game_id).order_by(GameTeam.id)
    )).scalars().all()
    assert [(t.name, t.emoji) for t in teams] == [("Ты", "🙋"), ("Бот", "🤖")]
    players = await alias_game._players_by_team(db, game_id)
    assert all(players.get(t.id) for t in teams), "обе команды должны быть заполнены автоматически"
    print(f"  команды: {[(t.emoji, t.name) for t in teams]}")
    print(f"  автозаполнение: Ты={len(players[teams[0].id])}, Бот={len(players[teams[1].id])}")

    # старт → первый ход команды «Ты»
    await alias_game.start_game(db, game_id)
    round = (await db.execute(
        select(GameRound).where(GameRound.game_id == game_id).order_by(GameRound.id.desc())
    )).scalars().first()
    assert round.team_id == teams[0].id, "первый ход — команда Ты"

    # ход «Ты»: 2 угадывания → таймер → последнее слово угадал «Ты» → подтвердить
    await alias_game.guess_word(db, round.id)
    await alias_game.guess_word(db, round.id)
    await alias_game._on_round_time_up(round.id)
    await db.refresh(round)  # таймер работает в отдельной сессии — перечитываем статус
    await alias_game.last_word(db, round.id, teams[0].id)
    await alias_game.confirm_round(db, round.id)  # после этого ход бота

    # ход бота: авто-игра (в реальном боте её запускает таймер, тут — вручную)
    bot_round = (await db.execute(
        select(GameRound).where(GameRound.game_id == game_id).order_by(GameRound.id.desc())
    )).scalars().first()
    assert bot_round.team_id == teams[1].id, "второй ход — бот"
    await db.refresh(teams[1])
    before = teams[1].score
    await alias_game._auto_play_bot_turn(bot_round.id)
    await db.refresh(teams[1])
    print(f"  бот набрал за ход: {teams[1].score - before} (итого {teams[1].score})")
    assert teams[1].score >= before + 1

    # после хода бота — снова ход «Ты»
    next_round = (await db.execute(
        select(GameRound).where(GameRound.game_id == game_id).order_by(GameRound.id.desc())
    )).scalars().first()
    assert next_round.team_id == teams[0].id, "после бота снова ходит Ты"
    print("  после хода бота снова ходит команда «Ты» ✅")


async def test_finish(db) -> None:
    """Кнопка «🏁 Закончить игру»: досрочное завершение + ближайший результат."""
    print("\n== Досрочное завершение игры ==")
    game = Game(space_id="spaces/TEST_ALIAS", status="setup", target_score=15, round_seconds=60)
    db.add(game)
    await db.flush()
    t1 = GameTeam(game_id=game.id, name="Красные", emoji="🔴", score=5)
    t2 = GameTeam(game_id=game.id, name="Синие", emoji="🔵", score=2)
    db.add_all([t1, t2])
    await db.commit()

    _sent.clear()
    result = await alias_game.finish_game(db, game.id)
    assert result.get("ok"), result
    game = (await db.execute(select(Game).where(Game.id == game.id))).scalar_one()
    assert game.status == "finished", game.status
    assert game.winner_team_id == t1.id, "лидер — команда с наибольшим счётом"
    summary = next((k["text"] for _, a, k in _sent if k.get("text")), "")
    assert "не доиграли" in summary, summary
    assert "Красные" in summary, summary
    print(f"  статус={game.status}, лидер={t1.emoji} {t1.name}")
    print(f"  сообщение в группу:\n{summary}")

    # повторное завершение — уже завершена
    result = await alias_game.finish_game(db, game.id)
    assert not result.get("ok"), "повторное завершение должно отказать"


async def main() -> None:
    async with AsyncSessionLocal() as db:
        await _cleanup(db)

        print("== Парсинг команды ==")
        for cmd in ("алиас", "алиас 20", "алиас 20 Красные Синие Зелёные", "алиас Красные Синие"):
            score, teams = alias_game.parse_alias_args(cmd, 15, ["Команда 1", "Команда 2"])
            print(f"  {cmd!r:40} -> цель={score}, команды={teams}")

        print("\n== Создание игры: цель 3, команды Красные/Синие/Зелёные ==")
        result = await alias_game.game_from_command(db, "spaces/TEST_ALIAS", "алиас 3 Красные Синие Зелёные")
        assert result.get("ok"), result
        game_id = result["game_id"]
        teams = (await db.execute(
            select(GameTeam).where(GameTeam.game_id == game_id).order_by(GameTeam.id)
        )).scalars().all()
        assert len(teams) == 3, len(teams)
        print(f"  команд: {len(teams)} -> {[(t.emoji, t.name) for t in teams]}")

        print("\n== Игроки и команды ==")
        profiles = [await _make_profile(db, i) for i in (1, 2, 3)]
        for prof, team in zip(profiles, teams):
            await alias_game.join_team(db, prof, game_id, team.id)
        players = await alias_game._players_by_team(db, game_id)
        print(f"  игроков по командам: {[len(players.get(t.id, [])) for t in teams]}")

        print("\n== Старт и раунд команды 1 ==")
        await alias_game.start_game(db, game_id)
        round = (await db.execute(
            select(GameRound).where(GameRound.game_id == game_id).order_by(GameRound.id.desc())
        )).scalars().first()
        team1 = teams[0]
        print(f"  первый ход: {team1.emoji} {team1.name}, слово={round.current_word!r}")

        # два угадывания → +2 команде 1
        await alias_game.guess_word(db, round.id)
        await alias_game.guess_word(db, round.id)
        await db.refresh(team1)
        print(f"  после 2 угадываний: {team1.emoji} {team1.name} = {team1.score}")

        print("\n== Таймер → последнее слово ==")
        await alias_game._on_round_time_up(round.id)  # симуляция таймера
        await db.refresh(round)
        assert round.status == "time_up", round.status
        print(f"  статус раунда: {round.status}")

        # последнее слово угадывает команда 1 → +1 → итого 3 = победа
        await alias_game.last_word(db, round.id, team1.id)
        await db.refresh(team1)
        print(f"  последнее слово угадано: {team1.emoji} {team1.name} = {team1.score}")

        print("\n== Подтверждение → победитель ==")
        r4 = await alias_game.confirm_round(db, round.id)
        game = (await db.execute(select(Game).where(Game.id == game_id))).scalar_one()
        assert game.status == "finished", game.status
        assert game.winner_team_id == team1.id
        phrase = r4["cards_v2"][0]["card"]["sections"][0]["widgets"][0]["textParagraph"]["text"]
        print(f"  {phrase}")

        print(f"\n  (сообщений в чат было бы отправлено/обновлено: {len(_sent)})")
        await _cleanup(db)

        await test_mode(db)
        await _cleanup(db)

        await test_finish(db)
        await _cleanup(db)
        print("\n✅ Проверка пройдена. Временные данные удалены.")


if __name__ == "__main__":
    asyncio.run(main())
