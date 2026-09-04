"""Игра Alias: команды, раунды со словами, счёт, подтверждение.

Поток одной партии:
  1. setup    — команда «алиас» создаёт игру + 2 команды, в группу падает карточка
                со счётом и кнопками «в команду 1/2» и «начать».
  2. active   — после «начать» идёт череда раундов. Объясняющий получает слово в
                личку (кнопки «+1 угадали / −1 скип»). Через round_seconds таймер
                переводит раунд в time_up — последнее слово может угадать ЛЮБАЯ
                команда (кнопки выбора команды).
  3. confirming — после последнего слова объясняющий подтверждает счёт раунда и
                может поправить баллы (+1/−1).
  4. confirmed  — применяется правка, проверяется победитель (первая до target_score);
                если никто не дошёл — ход переходит другой команде.

Счёт в группе обновляется на месте через messages.patch по scoreboard_message_name.
"""
import asyncio
import json
import logging
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import (
    Game,
    GamePlayer,
    GameRound,
    GameTeam,
    GameWordEvent,
    Profile,
)
from app.services.chat_sender import (
    find_user_dm_space,
    patch_message,
    send_message as send_space_message,
)
from app.services.weekly_poll import get_or_create_config
from app.services.games.banks.word_bank import random_word

logger = logging.getLogger(__name__)

# Эмодзи команд по кругу (для произвольного числа команд).
TEAM_EMOJIS = ["🔵", "🔴", "🟢", "🟡", "🟣", "🟠", "⚪", "🟤"]
DEFAULT_TEAM_NAMES = ["Team 1", "Team 2"]

# Поздравления победителю (одно случайное в конце партии).
WINNER_PHRASES = [
    "You're true word masters! 🔥",
    "Brilliant game — all words conquered! 👑",
    "Dream team! The words are afraid of you now. 😎",
    "You explained and won — Alias legends! 🏅",
    "Incredible finish, keep it up! 💪",
]


def parse_alias_args(
    raw_text: str, default_score: int, default_teams: list[str],
) -> tuple[int, list[str]]:
    """Разобрать команду: «алиас [цель] [имя1 имя2 …]».

    Первое слово — сама команда. Необязательное число = очки до победы,
    остальные слова = названия команд (их количество = числу команд).
    """
    tokens = raw_text.strip().split()
    if not tokens:
        return default_score, list(default_teams)
    tokens = tokens[1:]  # отбросить слово «алиас»/«alias»/«элиас»
    target = default_score
    if tokens and tokens[0].isdigit():
        target = int(tokens[0])
        tokens = tokens[1:]
    teams = [t for t in tokens if t] or list(default_teams)
    if len(teams) < 2:
        teams = list(default_teams)
    return target, teams


def _winner_congrats(team: GameTeam) -> str:
    return (
        f"🏆 Team {team.emoji} '{team.name}' wins with {team.score} points! "
        f"{random.choice(WINNER_PHRASES)}"
    )


# Синтетический профиль бота для одиночного режима «алиас тест».
TEST_BOT_USER_ID = "users/alias_bot_test"


def _is_bot(profile: Profile) -> bool:
    return profile.workspace_user_id == TEST_BOT_USER_ID


def is_test_command(raw_text: str) -> bool:
    """«алиас тест [цель]» — одиночная партия против бота."""
    tokens = raw_text.lower().strip().split()
    return len(tokens) >= 2 and tokens[1] in ("тест", "test")


def test_target(raw_text: str) -> int:
    tokens = raw_text.strip().split()
    if len(tokens) >= 3 and tokens[2].isdigit():
        return int(tokens[2])
    return 5


def _action_url() -> str:
    return get_settings().chat_app_audience or "alias"


def _display(profile: Profile) -> str:
    if profile.user_name:
        return profile.user_name
    if profile.user_email and "@" in profile.user_email:
        return profile.user_email.split("@")[0]
    return "—"


# --- Карточки ---


def build_scoreboard_card(
    game: Game,
    teams: list[GameTeam],
    players_by_team: dict[int, list[Profile]],
    action_url: str,
    turn_team: GameTeam | None = None,
) -> dict:
    """Карточка в группе: счёт, составы, кнопки (в setup) / итог (в finished)."""
    if game.status == "setup":
        subtitle = "Gather your teams and press 'Start'"
    elif game.status == "finished":
        subtitle = "Game over"
    else:
        subtitle = f"First to {game.target_score} points · turn: {turn_team.name if turn_team else '…'}"

    sections = []
    for t in teams:
        players = players_by_team.get(t.id, [])
        roster = ", ".join(_display(p) for p in players) if players else "—"
        sections.append({
            "header": f"{t.emoji} {t.name} — {t.score} pts · {len(players)} people",
            "widgets": [{"textParagraph": {"text": roster}}],
        })

    finish_button = {
        "text": "🏁 Finish game",
        "onClick": {"action": {
            "function": action_url,
            "parameters": [
                {"key": "method", "value": "alias_finish"},
                {"key": "game_id", "value": str(game.id)},
            ],
        }},
    }

    if game.status == "setup":
        buttons = []
        for t in teams:
            buttons.append({
                "text": f"{t.emoji} Join '{t.name}'",
                "onClick": {"action": {
                    "function": action_url,
                    "parameters": [
                        {"key": "method", "value": "alias_join"},
                        {"key": "game_id", "value": str(game.id)},
                        {"key": "team_id", "value": str(t.id)},
                    ],
                }},
            })
        buttons.append({
            "text": "▶️ Start",
            "onClick": {"action": {
                "function": action_url,
                "parameters": [
                    {"key": "method", "value": "alias_start"},
                    {"key": "game_id", "value": str(game.id)},
                ],
            }},
        })
        buttons.append(finish_button)
        sections.append({"widgets": [{"buttonList": {"buttons": buttons}}]})
    elif game.status == "active":
        sections.append({"widgets": [{"buttonList": {"buttons": [finish_button]}}]})
    elif game.status == "finished":
        winner = next((t for t in teams if t.id == game.winner_team_id), None)
        if winner is not None:
            if winner.score >= game.target_score:
                text = f"🏆 Team {winner.emoji} '{winner.name}' won!"
            else:
                text = f"🏆 Best result — {winner.emoji} '{winner.name}' ({winner.score} pts)"
            sections.append({"widgets": [{"textParagraph": {"text": text}}]})

    return {"cardsV2": [{
        "cardId": "aliasGame",
        "card": {"header": {"title": "Alias 🎲", "subtitle": subtitle}, "sections": sections},
    }]}


def _countdown_bar(remaining: int, total: int) -> str:
    """Полоска оставшегося времени: «▓▓▓▓░░░░░░» (10 делений)."""
    total = max(1, total)
    remaining = max(0, min(total, remaining))
    filled = round(remaining / total * 10)
    return "▓" * filled + "░" * (10 - filled)


def build_word_card(
    word: str, round_id: int, action_url: str, remaining: int | None = None, total: int = 60,
) -> dict:
    """Карточка слова в личке объясняющего (активный раунд, с отсчётом)."""
    sections = []
    if remaining is not None:
        sections.append({"widgets": [{"textParagraph": {
            "text": f"⏱ {remaining} s left\n{_countdown_bar(remaining, total)}"
        }}]})
    sections.append({"widgets": [{"textParagraph": {"text": word}}]})
    sections.append({"widgets": [{"buttonList": {"buttons": [
        {"text": "✅ Guessed +1", "onClick": {"action": {
            "function": action_url,
            "parameters": [
                {"key": "method", "value": "alias_guess"},
                {"key": "round_id", "value": str(round_id)},
            ],
        }}},
        {"text": "⏭️ Skip −1", "onClick": {"action": {
            "function": action_url,
            "parameters": [
                {"key": "method", "value": "alias_skip"},
                {"key": "round_id", "value": str(round_id)},
            ],
        }}},
    ]}}]})
    return {"cardsV2": [{
        "cardId": "aliasWord",
        "card": {
            "header": {"title": "Explain the word! ⏱", "subtitle": "Don't say the word itself"},
            "sections": sections,
        },
    }]}


def _remaining_seconds(game: Game, round: GameRound) -> int:
    """Сколько секунд осталось у раунда (считаем от started_at, без дрейфа)."""
    if round.started_at is None:
        return game.round_seconds
    started = round.started_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    return max(0, int(game.round_seconds - elapsed))


def _word_card_for(game: Game, round: GameRound) -> dict:
    """Карточка слова с актуальным отсчётом (один источник правды)."""
    remaining = _remaining_seconds(game, round)
    return build_word_card(
        round.current_word or "", round.id, _action_url(), remaining, game.round_seconds,
    )


def build_last_word_card(word: str, round_id: int, teams: list[GameTeam], action_url: str) -> dict:
    """Карточка последнего слова: угадать может любая команда."""
    buttons = []
    for t in teams:
        buttons.append({
            "text": f"{t.emoji} '{t.name}' guessed +1",
            "onClick": {"action": {
                "function": action_url,
                "parameters": [
                    {"key": "method", "value": "alias_last"},
                    {"key": "round_id", "value": str(round_id)},
                    {"key": "team_id", "value": str(t.id)},
                ],
            }},
        })
    buttons.append({
        "text": "⏭️ Skip −1",
        "onClick": {"action": {
            "function": action_url,
            "parameters": [
                {"key": "method", "value": "alias_skip"},
                {"key": "round_id", "value": str(round_id)},
            ],
        }},
    })
    return {"cardsV2": [{
        "cardId": "aliasLastWord",
        "card": {
            "header": {"title": "Last word! 🔥", "subtitle": "Any team can guess"},
            "sections": [
                {"widgets": [{"textParagraph": {"text": word}}]},
                {"widgets": [{"buttonList": {"buttons": buttons}}]},
            ],
        },
    }]}


def build_confirm_card(
    active_team: GameTeam,
    round_points: int,
    adjustment: int,
    action_url: str,
    round_id: int,
) -> dict:
    """Карточка подтверждения счёта раунда (объясняющему в личку)."""
    net = round_points + adjustment
    return {"cardsV2": [{
        "cardId": "aliasConfirm",
        "card": {
            "header": {"title": "Round complete ✅", "subtitle": "Check the score and confirm"},
            "sections": [
                {"widgets": [{"textParagraph": {
                    "text": f"Your team {active_team.emoji} {active_team.name} this round: {net:+d}"
                }}]},
                {"widgets": [{"buttonList": {"buttons": [
                    {"text": "+1 point", "onClick": {"action": {
                        "function": action_url,
                        "parameters": [
                            {"key": "method", "value": "alias_adjust"},
                            {"key": "round_id", "value": str(round_id)},
                            {"key": "delta", "value": "1"},
                        ],
                    }}},
                    {"text": "−1 point", "onClick": {"action": {
                        "function": action_url,
                        "parameters": [
                            {"key": "method", "value": "alias_adjust"},
                            {"key": "round_id", "value": str(round_id)},
                            {"key": "delta", "value": "-1"},
                        ],
                    }}},
                    {"text": "✅ Confirm", "onClick": {"action": {
                        "function": action_url,
                        "parameters": [
                            {"key": "method", "value": "alias_confirm"},
                            {"key": "round_id", "value": str(round_id)},
                        ],
                    }}},
                ]}}]},
            ],
        },
    }]}


def build_done_card(text: str, card_id: str = "aliasLastWord") -> dict:
    """Заглушка-итог, заменяющая карточку последнего слова / подтверждения."""
    return {"cardsV2": [{
        "cardId": card_id,
        "card": {"header": {"title": "Round complete ✅"},
                 "sections": [{"widgets": [{"textParagraph": {"text": text}}]}]},
    }]}


# --- Вспомогательные запросы ---


async def _teams_of_game(db: AsyncSession, game_id: int) -> list[GameTeam]:
    # populate_existing — всегда свежие score из БД (не из кеша сессии), т.к. счёт
    # меняется атомарными UPDATE'ами, которые не трогают объекты в identity map.
    return (await db.execute(
        select(GameTeam)
        .where(GameTeam.game_id == game_id)
        .order_by(GameTeam.id)
        .execution_options(populate_existing=True)
    )).scalars().all()


async def _change_score(db: AsyncSession, team_id: int, delta: int) -> None:
    """Атомарно сдвинуть счёт команды (score = score + delta) без гонок.

    Раньше было `team.score += delta` — это read-modify-write по кешу сессии, и при
    двух параллельных кликах (двойной клик по «+1») один сдвиг терялся: оба читали
    одно значение и писали одинаковое новое. Атомарный UPDATE это исключает.
    """
    await db.execute(
        update(GameTeam)
        .where(GameTeam.id == team_id)
        .values(score=GameTeam.score + delta)
    )


async def _players_by_team(db: AsyncSession, game_id: int) -> dict[int, list[Profile]]:
    rows = (await db.execute(
        select(GamePlayer, Profile)
        .join(Profile, Profile.id == GamePlayer.profile_id)
        .where(GamePlayer.game_id == game_id)
        .order_by(GamePlayer.joined_at)
    )).all()
    result: dict[int, list[Profile]] = {}
    for gp, prof in rows:
        result.setdefault(gp.team_id, []).append(prof)
    return result


async def _current_round(db: AsyncSession, game_id: int) -> GameRound | None:
    return (await db.execute(
        select(GameRound)
        .where(GameRound.game_id == game_id, GameRound.status.in_(("active", "time_up", "confirming")))
        .order_by(GameRound.id.desc())
    )).scalars().first()


async def _pick_word(db: AsyncSession, game_id: int) -> str:
    used = set((await db.execute(
        select(GameWordEvent.word)
        .join(GameRound, GameRound.id == GameWordEvent.round_id)
        .where(GameRound.game_id == game_id)
    )).scalars().all())
    return random_word(exclude=used) or random_word() or "hello"


async def _pick_explainer(
    db: AsyncSession, game_id: int, team_id: int, players: list[Profile],
) -> Profile:
    """Круговой выбор объясняющего: наименее «отходивший» игрок команды."""
    round_count = (await db.execute(
        select(func.count()).select_from(GameRound).where(
            GameRound.game_id == game_id, GameRound.team_id == team_id,
        )
    )).scalar_one()
    return players[round_count % len(players)]


async def _round_team_points(db: AsyncSession, round_id: int, team_id: int) -> int:
    total = (await db.execute(
        select(func.coalesce(func.sum(GameWordEvent.points), 0)).where(
            GameWordEvent.round_id == round_id, GameWordEvent.team_id == team_id,
        )
    )).scalar_one()
    return int(total)


def _send_dm_card(profile: Profile, cards_v2: list[dict], text: str = "") -> str:
    """Submit карточку в личку и вернуть имя сообщения (для patch)."""
    ws = profile.workspace_user_id or ""
    if not ws.startswith("users/"):
        logger.warning("alias_dm_skip_no_workspace profile=%s", profile.id)
        return ""
    dm = find_user_dm_space(ws)
    if not dm:
        logger.warning("alias_dm_not_found profile=%s", profile.id)
        return ""
    resp = send_space_message(dm, text=text, cards_v2=cards_v2)
    return resp.get("name", "")


async def _refresh_scoreboard(
    db: AsyncSession, game: Game, turn_team: GameTeam | None = None,
) -> None:
    """Обновить карточку счёта в группе на месте (messages.patch)."""
    if not game.scoreboard_message_name:
        return
    teams = await _teams_of_game(db, game.id)
    players_by_team = await _players_by_team(db, game.id)
    if turn_team is None and game.status == "active":
        current = await _current_round(db, game.id)
        if current is not None:
            turn_team = next((t for t in teams if t.id == current.team_id), None)
    card = build_scoreboard_card(game, teams, players_by_team, _action_url(), turn_team)
    try:
        patch_message(game.scoreboard_message_name, cards_v2=card["cardsV2"])
    except Exception:
        logger.exception("alias_scoreboard_patch_failed game=%s", game.id)


def _schedule_timer(game: Game, round: GameRound) -> None:
    from app.scheduler import scheduler

    if scheduler is None:
        return
    run_at = datetime.now(timezone.utc) + timedelta(seconds=game.round_seconds)
    scheduler.add_job(
        _on_round_time_up, "date", run_date=run_at,
        id=f"alias_timer_{round.id}", replace_existing=True, args=[round.id],
    )
    # Отсчёт: первый тик через секунду, дальше цепочка сама себя продлевает.
    tick_at = datetime.now(timezone.utc) + timedelta(seconds=1)
    scheduler.add_job(
        _on_countdown_tick, "date", run_date=tick_at,
        id=f"alias_tick_{round.id}", replace_existing=True, args=[round.id],
    )


async def _on_round_time_up(round_id: int) -> None:
    """Таймер: раунд → time_up. В группу НЕ пишем — слово знает только объясняющий.

    Объясняющему меняем карточку слова на карточку «последнее слово» (в его личке).
    """
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        round = (await db.execute(
            select(GameRound).where(GameRound.id == round_id)
        )).scalar_one_or_none()
        if round is None or round.status != "active":
            return
        game = (await db.execute(
            select(Game).where(Game.id == round.game_id)
        )).scalar_one_or_none()
        if game is None or game.status != "active":
            return
        round.status = "time_up"
        round.ended_at = datetime.now(timezone.utc)
        await db.commit()

        teams = await _teams_of_game(db, game.id)
        word = round.current_word or "…"

        if round.word_message_name:
            try:
                card = build_last_word_card(word, round.id, teams, _action_url())
                patch_message(round.word_message_name, cards_v2=card["cardsV2"])
            except Exception:
                logger.exception("alias_last_word_patch_failed round=%s", round.id)


async def _on_countdown_tick(round_id: int) -> None:
    """Тик отсчёта: обновить карточку слова в личке и продлить цепочку.

    Считает остаток от started_at (а не декрементом), поэтому даже при пропуске
    тика число не «уезжает». Останавливается, когда раунд больше не active.
    """
    from app.database import AsyncSessionLocal
    from app.scheduler import scheduler

    next_tick = False
    async with AsyncSessionLocal() as db:
        round = (await db.execute(
            select(GameRound).where(GameRound.id == round_id)
        )).scalar_one_or_none()
        if round is None or round.status != "active":
            return
        game = (await db.execute(
            select(Game).where(Game.id == round.game_id)
        )).scalar_one_or_none()
        if game is None or game.status != "active":
            return
        remaining = _remaining_seconds(game, round)
        if remaining <= 0:
            return
        if round.word_message_name:
            try:
                card = _word_card_for(game, round)
                patch_message(round.word_message_name, cards_v2=card["cardsV2"])
            except Exception:
                logger.exception("alias_countdown_patch_failed round=%s", round.id)
        next_tick = remaining > 1

    if next_tick and scheduler is not None:
        scheduler.add_job(
            _on_countdown_tick, "date",
            run_date=datetime.now(timezone.utc) + timedelta(seconds=1),
            id=f"alias_tick_{round_id}", replace_existing=True, args=[round_id],
        )


def _schedule_bot_turn(round_id: int) -> None:
    from app.scheduler import scheduler

    if scheduler is None:
        return
    run_at = datetime.now(timezone.utc) + timedelta(seconds=3)
    scheduler.add_job(
        _auto_play_bot_turn, "date", run_date=run_at,
        id=f"alias_bot_{round_id}", replace_existing=True, args=[round_id],
    )


async def _auto_play_bot_turn(round_id: int) -> None:
    """Авто-ход бота: случайно набрать 1–3 очка (иногда скип) и завершить раунд."""
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        round = (await db.execute(
            select(GameRound).where(GameRound.id == round_id)
        )).scalar_one_or_none()
        if round is None or round.status != "active":
            return
        game = (await db.execute(
            select(Game).where(Game.id == round.game_id)
        )).scalar_one_or_none()
        if game is None or game.status != "active":
            return
        bot_team = (await db.execute(
            select(GameTeam).where(GameTeam.id == round.team_id)
        )).scalar_one_or_none()
        if bot_team is None:
            return

        gained = 0
        for _ in range(random.randint(1, 3)):
            gained += 1
            await _change_score(db, bot_team.id, 1)
            db.add(GameWordEvent(
                round_id=round.id, word=await _pick_word(db, game.id),
                outcome="guessed", points=1, team_id=bot_team.id, is_last=False,
            ))
        if random.random() < 0.3:
            gained -= 1
            await _change_score(db, bot_team.id, -1)
            db.add(GameWordEvent(
                round_id=round.id, word=await _pick_word(db, game.id),
                outcome="skipped", points=-1, team_id=bot_team.id, is_last=False,
            ))
        await db.commit()
        logger.info("alias_bot_turn_done round=%s gained=%s", round.id, gained)
        await _finalize_round(db, round, game)


# --- Действия ---


async def setup_game(
    db: AsyncSession, space_name: str, target_score: int, team_names: list[str],
) -> dict:
    """Создать игру с N командами и карточку в группу."""
    round_seconds = int((await get_or_create_config(db, "alias_round_seconds", 60)).value or 60)
    game = Game(
        space_id=space_name, status="setup",
        target_score=target_score, round_seconds=round_seconds,
    )
    db.add(game)
    await db.flush()
    for i, name in enumerate(team_names):
        db.add(GameTeam(game_id=game.id, name=name, emoji=TEAM_EMOJIS[i % len(TEAM_EMOJIS)]))
    await db.commit()

    teams = await _teams_of_game(db, game.id)
    card = build_scoreboard_card(game, teams, {}, _action_url())
    resp = await asyncio.to_thread(
        send_space_message,
        space_name, text="Alias game! Gather your teams 🎲", cards_v2=card["cardsV2"],
    )
    game.scoreboard_message_name = resp.get("name")
    await db.commit()
    logger.info("alias_game_setup game=%s space=%s teams=%s", game.id, space_name, len(teams))
    return {"ok": True, "silent": True, "game_id": game.id}


async def game_from_command(db: AsyncSession, space_name: str, raw_text: str) -> dict:
    """Команда «алиас» с опциями: «алиас [цель] [имя1 имя2 …]»."""
    default_score = int((await get_or_create_config(db, "alias_target_score", 15)).value or 15)
    default_teams = (await get_or_create_config(db, "alias_teams", DEFAULT_TEAM_NAMES)).value or DEFAULT_TEAM_NAMES
    if isinstance(default_teams, str):
        default_teams = json.loads(default_teams) if default_teams.strip().startswith("[") else [default_teams]
    target, teams = parse_alias_args(raw_text, default_score, default_teams)
    return await setup_game(db, space_name, target, teams)


async def setup_test_game(
    db: AsyncSession, space_name: str, user_profile: Profile, target_score: int,
) -> dict:
    """«алиас тест»: одиночная партия — команда «Ты» против команды «Бот» (бот играет сам)."""
    round_seconds = int((await get_or_create_config(db, "alias_round_seconds", 60)).value or 60)
    game = Game(
        space_id=space_name, status="setup",
        target_score=target_score, round_seconds=round_seconds,
    )
    db.add(game)
    await db.flush()
    user_team = GameTeam(game_id=game.id, name="You", emoji="🙋")
    bot_team = GameTeam(game_id=game.id, name="Bot", emoji="🤖")
    db.add(user_team)
    db.add(bot_team)
    await db.flush()

    bot = (await db.execute(
        select(Profile).where(Profile.workspace_user_id == TEST_BOT_USER_ID)
    )).scalar_one_or_none()
    if bot is None:
        bot = Profile(
            workspace_user_id=TEST_BOT_USER_ID, user_email="alias_bot@test.local", user_name="Bot 🤖",
        )
        db.add(bot)
        await db.flush()

    db.add(GamePlayer(game_id=game.id, team_id=user_team.id, profile_id=user_profile.id))
    db.add(GamePlayer(game_id=game.id, team_id=bot_team.id, profile_id=bot.id))
    await db.commit()

    teams = await _teams_of_game(db, game.id)
    players_by_team = await _players_by_team(db, game.id)
    card = build_scoreboard_card(game, teams, players_by_team, _action_url())
    resp = await asyncio.to_thread(
        send_space_message,
        space_name, text="Alias game (solo): you vs the bot! 🤖", cards_v2=card["cardsV2"],
    )
    game.scoreboard_message_name = resp.get("name")
    await db.commit()
    logger.info("alias_test_game_setup game=%s space=%s", game.id, space_name)
    return {"ok": True, "silent": True, "game_id": game.id}


async def join_team(db: AsyncSession, profile: Profile, game_id: int, team_id: int) -> dict:
    """Кнопка «в команду»: записать игрока (или переместить), обновить карточку."""
    game = (await db.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
    if game is None:
        return {"ok": False, "text": "Game not found 🤷"}
    if game.status != "setup":
        return {"ok": False, "text": "Game already started 🚀"}
    team = (await db.execute(
        select(GameTeam).where(GameTeam.id == team_id, GameTeam.game_id == game_id)
    )).scalar_one_or_none()
    if team is None:
        return {"ok": False, "text": "Team not found 🤷"}

    existing = (await db.execute(
        select(GamePlayer).where(
            GamePlayer.game_id == game_id, GamePlayer.profile_id == profile.id,
        )
    )).scalar_one_or_none()
    if existing is None:
        db.add(GamePlayer(game_id=game_id, team_id=team_id, profile_id=profile.id))
    elif existing.team_id != team_id:
        existing.team_id = team_id
    await db.commit()

    teams = await _teams_of_game(db, game_id)
    players_by_team = await _players_by_team(db, game_id)
    card = build_scoreboard_card(game, teams, players_by_team, _action_url())
    return {"ok": True, "cards_v2": card["cardsV2"]}


async def start_game(db: AsyncSession, game_id: int) -> dict:
    """Кнопка «начать»: проверить команды, запустить первый раунд."""
    game = (await db.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
    if game is None:
        return {"ok": False, "text": "Game not found 🤷"}
    if game.status != "setup":
        return {"ok": False, "text": "Game already started 🚀"}
    teams = await _teams_of_game(db, game_id)
    players_by_team = await _players_by_team(db, game_id)
    for t in teams:
        if not players_by_team.get(t.id):
            return {"ok": False, "text": f"Team '{t.name}' is empty — add at least one player 🙏"}

    game.status = "active"
    await db.commit()

    first_team = teams[0]
    await _start_round(db, game, first_team, players_by_team)
    card = build_scoreboard_card(game, teams, players_by_team, _action_url(), turn_team=first_team)
    return {"ok": True, "cards_v2": card["cardsV2"]}


async def _start_round(
    db: AsyncSession, game: Game, team: GameTeam, players_by_team: dict[int, list[Profile]],
) -> None:
    """Создать раунд, отправить слово объясняющему, запустить таймер."""
    players = players_by_team.get(team.id, [])
    explainer = await _pick_explainer(db, game.id, team.id, players)
    word = await _pick_word(db, game.id)
    round = GameRound(
        game_id=game.id, team_id=team.id,
        explainer_profile_id=explainer.id, status="active", current_word=word,
    )
    db.add(round)
    await db.commit()
    await db.refresh(round)

    if _is_bot(explainer):
        _schedule_bot_turn(round.id)
        logger.info("alias_bot_turn_scheduled round=%s", round.id)
        return

    card = _word_card_for(game, round)
    name = await asyncio.to_thread(_send_dm_card, explainer, card["cardsV2"], text="")
    if name:
        round.word_message_name = name
        await db.commit()
    _schedule_timer(game, round)
    logger.info("alias_round_started round=%s team=%s explainer=%s", round.id, team.id, explainer.id)


async def guess_word(db: AsyncSession, round_id: int) -> dict:
    """«Угадали +1» в активном раунде: +1 команде, следующее слово."""
    round = (await db.execute(
        select(GameRound).where(GameRound.id == round_id)
    )).scalar_one_or_none()
    if round is None:
        return {"ok": False, "text": "Round not found 🤷"}
    if round.status != "active":
        return {"ok": False, "text": "Time's up! Decide the last word 🔥"}
    game = (await db.execute(select(Game).where(Game.id == round.game_id))).scalar_one_or_none()
    if game is None or game.status != "active":
        return {"ok": False, "text": "Game is over 🏁"}
    team = (await db.execute(
        select(GameTeam).where(GameTeam.id == round.team_id)
    )).scalar_one_or_none()
    await _change_score(db, team.id, 1)
    db.add(GameWordEvent(
        round_id=round.id, word=round.current_word or "",
        outcome="guessed", points=1, team_id=team.id, is_last=False,
    ))
    word = await _pick_word(db, game.id)
    round.current_word = word
    await db.commit()

    await _refresh_scoreboard(db, game)
    card = _word_card_for(game, round)
    return {"ok": True, "cards_v2": card["cardsV2"]}


async def skip_word(db: AsyncSession, round_id: int) -> dict:
    """«Скип −1»: в активном раунде −1 и новое слово; в time_up — скип последнего слова."""
    round = (await db.execute(
        select(GameRound).where(GameRound.id == round_id)
    )).scalar_one_or_none()
    if round is None:
        return {"ok": False, "text": "Round not found 🤷"}
    if round.status not in ("active", "time_up"):
        return {"ok": False, "text": "Round already finished"}
    game = (await db.execute(select(Game).where(Game.id == round.game_id))).scalar_one_or_none()
    if game is None or game.status != "active":
        return {"ok": False, "text": "Game is over 🏁"}
    team = (await db.execute(
        select(GameTeam).where(GameTeam.id == round.team_id)
    )).scalar_one_or_none()
    await _change_score(db, team.id, -1)

    if round.status == "active":
        db.add(GameWordEvent(
            round_id=round.id, word=round.current_word or "",
            outcome="skipped", points=-1, team_id=team.id, is_last=False,
        ))
        word = await _pick_word(db, game.id)
        round.current_word = word
        await db.commit()
        await _refresh_scoreboard(db, game)
        return {"ok": True, "cards_v2": _word_card_for(game, round)["cardsV2"]}

    # time_up: скип последнего слова → −1 активной команде и конец раунда
    db.add(GameWordEvent(
        round_id=round.id, word=round.current_word or "",
        outcome="skipped", points=-1, team_id=team.id, is_last=True,
    ))
    await db.commit()
    return await _end_round(db, round, game)


async def last_word(db: AsyncSession, round_id: int, team_id: int) -> dict:
    """«Угадала команда X +1» на последнем слове: +1 команде X и конец раунда."""
    round = (await db.execute(
        select(GameRound).where(GameRound.id == round_id)
    )).scalar_one_or_none()
    if round is None:
        return {"ok": False, "text": "Round not found 🤷"}
    if round.status != "time_up":
        return {"ok": False, "text": "It's not time for the last word yet"}
    game = (await db.execute(select(Game).where(Game.id == round.game_id))).scalar_one_or_none()
    winner_team = (await db.execute(
        select(GameTeam).where(GameTeam.id == team_id, GameTeam.game_id == game.id)
    )).scalar_one_or_none()
    if winner_team is None:
        return {"ok": False, "text": "Team not found 🤷"}
    # CAS: атомарно пометить раунд обработанным — двойной клик не даст двойной +1.
    res = await db.execute(
        update(GameRound)
        .where(GameRound.id == round_id, GameRound.status == "time_up")
        .values(status="confirming")
    )
    if res.rowcount == 0:
        return {"ok": False, "text": "Round already processed"}
    await _change_score(db, winner_team.id, 1)
    db.add(GameWordEvent(
        round_id=round.id, word=round.current_word or "",
        outcome="guessed", points=1, team_id=winner_team.id, is_last=True,
    ))
    await db.commit()
    return await _end_round(db, round, game)


async def _end_round(db: AsyncSession, round: GameRound, game: Game) -> dict:
    """Перевести раунд в confirming и отправить объясняющему карточку подтверждения."""
    round.status = "confirming"
    await db.commit()
    await _refresh_scoreboard(db, game)

    teams = await _teams_of_game(db, game.id)
    active_team = next((t for t in teams if t.id == round.team_id), None)
    round_points = await _round_team_points(db, round.id, round.team_id)
    explainer = (await db.execute(
        select(Profile).where(Profile.id == round.explainer_profile_id)
    )).scalar_one_or_none()
    if explainer is not None and active_team is not None:
        card = build_confirm_card(active_team, round_points, round.points_adjustment, _action_url(), round.id)
        await asyncio.to_thread(_send_dm_card, explainer, card["cardsV2"], text="Round complete — confirm the score ✅")

    return {"ok": True, "cards_v2": build_done_card("Score saved, check your DMs ✅")["cardsV2"]}


async def adjust_points(db: AsyncSession, round_id: int, delta: int) -> dict:
    """Кнопка «+1/−1» на подтверждении: накопить правку счёта раунда."""
    round = (await db.execute(
        select(GameRound).where(GameRound.id == round_id)
    )).scalar_one_or_none()
    if round is None:
        return {"ok": False, "text": "Round not found 🤷"}
    if round.status != "confirming":
        return {"ok": False, "text": "Round already confirmed"}
    await db.execute(
        update(GameRound)
        .where(GameRound.id == round.id)
        .values(points_adjustment=GameRound.points_adjustment + delta)
    )
    await db.commit()
    await db.refresh(round)  # свежее points_adjustment после атомарного UPDATE

    teams = await _teams_of_game(db, round.game_id)
    active_team = next((t for t in teams if t.id == round.team_id), None)
    round_points = await _round_team_points(db, round.id, round.team_id)
    card = build_confirm_card(active_team, round_points, round.points_adjustment, _action_url(), round.id)
    return {"ok": True, "cards_v2": card["cardsV2"]}


async def confirm_round(db: AsyncSession, round_id: int) -> dict:
    """«Подтвердить»: применить правку, проверить победителя, передать ход."""
    round = (await db.execute(
        select(GameRound).where(GameRound.id == round_id)
    )).scalar_one_or_none()
    if round is None:
        return {"ok": False, "text": "Round not found 🤷"}
    if round.status != "confirming":
        return {"ok": False, "text": "Round already confirmed"}
    game = (await db.execute(select(Game).where(Game.id == round.game_id))).scalar_one_or_none()
    if game is None or game.status != "active":
        return {"ok": False, "text": "Game is over 🏁"}
    return await _finalize_round(db, round, game)


async def _finalize_round(db: AsyncSession, round: GameRound, game: Game) -> dict:
    """Применить правку, завершить раунд, проверить победителя / передать ход."""
    # CAS: только один подтверждающий клик применяет правку и завершает раунд.
    res = await db.execute(
        update(GameRound)
        .where(GameRound.id == round.id, GameRound.status == "confirming")
        .values(status="confirmed", confirmed_at=datetime.now(timezone.utc))
    )
    if res.rowcount == 0:
        return {"ok": False, "text": "Round already confirmed"}
    if round.points_adjustment:
        await _change_score(db, round.team_id, round.points_adjustment)
    await db.commit()

    teams = await _teams_of_game(db, game.id)  # свежий счёт после атомарной правки
    winner = _winner(game, teams)
    if winner is not None:
        game.status = "finished"
        game.winner_team_id = winner.id
        await db.commit()
        await _refresh_scoreboard(db, game)
        congrats = _winner_congrats(winner)
        try:
            await asyncio.to_thread(send_space_message, game.space_id, text=congrats)
        except Exception:
            logger.exception("alias_winner_msg_failed game=%s", game.id)
        return {"ok": True, "cards_v2": build_done_card(
            congrats, card_id="aliasConfirm",
        )["cardsV2"]}

    idx = next((i for i, t in enumerate(teams) if t.id == round.team_id), 0)
    next_team = teams[(idx + 1) % len(teams)]
    players_by_team = await _players_by_team(db, game.id)
    await _start_round(db, game, next_team, players_by_team)
    await _refresh_scoreboard(db, game, turn_team=next_team)
    return {"ok": True, "cards_v2": build_done_card(
        f"Turn: {next_team.emoji} '{next_team.name}'! Check your DMs 😉", card_id="aliasConfirm",
    )["cardsV2"]}


def _winner(game: Game, teams: list[GameTeam]) -> GameTeam | None:
    reached = [t for t in teams if t.score >= game.target_score]
    if not reached:
        return None
    return max(reached, key=lambda t: t.score)


def _build_finish_summary(game: Game, teams: list[GameTeam]) -> str:
    """Сообщение в группу при досрочном завершении: не доиграли, лидер(ы) ближе всех."""
    if not teams:
        return "🏁 Game stopped — didn't reach the end"
    top_score = max(t.score for t in teams)
    leaders = [t for t in teams if t.score == top_score]
    lines = ["🏁 Game stopped — didn't reach the end"]
    if len(leaders) == 1:
        t = leaders[0]
        lines.append(f"Closest to winning: {t.emoji} '{t.name}' — {t.score} pts")
    else:
        names = ", ".join(f"{t.emoji} «{t.name}»" for t in leaders)
        lines.append(f"Tied for the lead: {names} — {top_score} pts each")
    lines.append(f"Target was {game.target_score} points")
    return "\n".join(lines)


async def finish_game(db: AsyncSession, game_id: int) -> dict:
    """Кнопка «🏁 Finish game»: завершить досрочно и показать ближайший результат."""
    game = (await db.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
    if game is None:
        return {"ok": False, "text": "Game not found 🤷"}
    if game.status == "finished":
        return {"ok": False, "text": "Game already finished"}

    teams = await _teams_of_game(db, game_id)
    top_score = max((t.score for t in teams), default=None)
    leaders = [t for t in teams if t.score == top_score] if top_score is not None else []
    game.status = "finished"
    game.winner_team_id = leaders[0].id if len(leaders) == 1 else None
    # Гасим активные раунды, чтобы guess/skip/confirm не продолжали завершённую игру.
    await db.execute(
        update(GameRound)
        .where(GameRound.game_id == game_id, GameRound.status.in_(("active", "time_up")))
        .values(status="confirmed", ended_at=datetime.now(timezone.utc))
    )
    await db.commit()

    await _refresh_scoreboard(db, game)

    summary = _build_finish_summary(game, teams)
    try:
        await asyncio.to_thread(send_space_message, game.space_id, text=summary)
    except Exception:
        logger.exception("alias_finish_msg_failed game=%s", game.id)

    players_by_team = await _players_by_team(db, game_id)
    card = build_scoreboard_card(game, teams, players_by_team, _action_url())
    return {"ok": True, "cards_v2": card["cardsV2"]}
