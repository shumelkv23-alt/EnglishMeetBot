"""Игра Snake Oil / «Змеиное масло» 🧪 — питчинг абсурдных товаров.

Поток партии:
  1. setup    — команда «снейк» создаёт игру; в группе карточка с кнопками
                «🎲 Я играю!» и «▶️ Начать».
  2. active   — после «начать» идёт череда раундов. Каждый раунд:
                - в группе объявляется покупатель (реальный игрок) + его роль
                  («😺 Кот») + бытовая проблема;
                - каждому продавцу в ЛИЧКУ падает роль + проблема + 2 слова;
                - обсуждение идёт вживую (бот молчит);
                - покупателю в ЛИЧКУ падает список продавцов с их словами и
                  кнопками «Выбрать»;
                - покупатель нажимает «Выбрать» → результат в группу, победителю
                  +1 очко и он становится следующим покупателем.
  3. finished  — первый игрок до target_score побеждает.

Одиночный режим «снейк тест»: игрок против бота. Бот — и покупатель, и продавец
(сам генерирует свою пару слов); LLM судит, чья пара лучше (фолбэк — случайно).

Счёт в группе обновляется на месте через messages.patch по scoreboard_message_name.
"""
import asyncio
import json
import logging
import random
from datetime import datetime, timezone

import requests
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Profile, SnakeGame, SnakeOffer, SnakePlayer, SnakeRound
from app.services.chat_sender import (
    find_user_dm_space,
    patch_message,
    send_message as send_space_message,
)
from app.services.snake_bank import random_persona, random_problem
from app.services.weekly_poll import get_or_create_config
from app.services.word_bank import sample_product_words

logger = logging.getLogger(__name__)

# Синтетический профиль бота для одиночного режима «снейк тест».
TEST_BOT_USER_ID = "users/snake_bot_test"

WINNER_PHRASES = [
    "A genius pitch — the customer is already reaching for their wallet! 💸",
    "That's how Snake Oil legends sell! 🧪",
    "A brilliant pitch, it sold like hotcakes! 🔥",
    "The customer couldn't resist — and we get it! 😎",
    "A true master of the hustle! 👑",
]


def is_test_command(raw_text: str) -> bool:
    """«снейк тест [цель]» — одиночная партия против бота."""
    tokens = raw_text.lower().strip().split()
    return len(tokens) >= 2 and tokens[1] in ("тест", "test")


def test_target(raw_text: str) -> int:
    tokens = raw_text.strip().split()
    if len(tokens) >= 3 and tokens[2].isdigit():
        return int(tokens[2])
    return 3


def parse_snake_args(raw_text: str, default_score: int) -> int:
    """Команда «снейк [цель]» → очки до победы (по умолчанию default_score)."""
    tokens = raw_text.strip().split()
    if len(tokens) >= 2 and tokens[1].isdigit():
        return int(tokens[1])
    return default_score


def _action_url() -> str:
    return get_settings().chat_app_audience or "snake"


def _display(profile: Profile) -> str:
    if profile.user_name:
        return profile.user_name
    if profile.user_email and "@" in profile.user_email:
        return profile.user_email.split("@")[0]
    return "—"


def _is_bot(profile: Profile) -> bool:
    return profile.workspace_user_id == TEST_BOT_USER_ID


def _winner_congrats(profile: Profile, score: int) -> str:
    return f"🏆 {_display(profile)} wins with {score} points! {random.choice(WINNER_PHRASES)}"


# --- Карточки ---


def build_scoreboard_card(
    game: SnakeGame,
    players: list[tuple[SnakePlayer, Profile]],
    action_url: str,
) -> dict:
    """Карточка в группе: счёт игроков, кнопки (setup) / итог (finished)."""
    if game.status == "setup":
        subtitle = "Press «I'm playing!» and then «Start»"
    elif game.status == "finished":
        subtitle = "Game over"
    else:
        subtitle = f"To {game.target_score} points"

    lines = [f"{_display(prof)} — {sp.score} pts" for sp, prof in players] or ["Nobody is playing yet"]
    sections = [{"widgets": [{"textParagraph": {"text": "\n".join(lines)}}]}]

    finish_button = {
        "text": "🏁 End game",
        "onClick": {"action": {
            "function": action_url,
            "parameters": [
                {"key": "method", "value": "snake_finish"},
                {"key": "game_id", "value": str(game.id)},
            ],
        }},
    }

    if game.status == "setup":
        buttons = [
            {
                "text": "🎲 I'm playing!",
                "onClick": {"action": {
                    "function": action_url,
                    "parameters": [
                        {"key": "method", "value": "snake_join"},
                        {"key": "game_id", "value": str(game.id)},
                    ],
                }},
            },
            {
                "text": "▶️ Start",
                "onClick": {"action": {
                    "function": action_url,
                    "parameters": [
                        {"key": "method", "value": "snake_start"},
                        {"key": "game_id", "value": str(game.id)},
                    ],
                }},
            },
            finish_button,
        ]
        sections.append({"widgets": [{"buttonList": {"buttons": buttons}}]})
    elif game.status == "active":
        sections.append({"widgets": [{"buttonList": {"buttons": [finish_button]}}]})
    elif game.status == "finished":
        winner = next((prof for sp, prof in players if prof.id == game.winner_profile_id), None)
        if winner is not None:
            sections.append({"widgets": [{"textParagraph": {
                "text": f"🏆 {_display(winner)} wins!"
            }}]})

    return {"cardsV2": [{
        "cardId": "snakeGame",
        "card": {"header": {"title": "Snake Oil 🧪", "subtitle": subtitle}, "sections": sections},
    }]}


def build_seller_card(round: SnakeRound, word1: str, word2: str, action_url: str, solo: bool = False) -> dict:
    """Карточка продавцу в личке: роль покупателя + проблема + 2 слова."""
    sections = [
        {"widgets": [{"textParagraph": {"text": (
            f"Customer: {round.persona}\n"
            f"❗ Problem: {round.problem}\n\n"
            f"Your product from the words:\n🔹 {word1}\n🔹 {word2}\n\n"
            "Come up with a product and sell it!"
        )}}]},
    ]
    if solo:
        sections.append({"widgets": [{"buttonList": {"buttons": [
            {"text": "🎤 Ready — judge", "onClick": {"action": {
                "function": action_url,
                "parameters": [
                    {"key": "method", "value": "snake_solo_ready"},
                    {"key": "round_id", "value": str(round.id)},
                ],
            }}},
        ]}}]})
    return {"cardsV2": [{
        "cardId": "snakeSeller",
        "card": {"header": {"title": "You're the seller! 🎤", "subtitle": round.persona}, "sections": sections},
    }]}


def build_customer_card(
    round: SnakeRound,
    sellers: list[tuple[SnakeOffer, Profile]],
    action_url: str,
) -> dict:
    """Карточка покупателю в личке: продавцы + их слова + кнопки «Выбрать»."""
    lines = [f"{_display(prof)}: {offer.word1} + {offer.word2}" for offer, prof in sellers]
    buttons = [
        {
            "text": f"Choose {_display(prof)}",
            "onClick": {"action": {
                "function": action_url,
                "parameters": [
                    {"key": "method", "value": "snake_vote"},
                    {"key": "round_id", "value": str(round.id)},
                    {"key": "offer_id", "value": str(offer.id)},
                ],
            }},
        }
        for offer, prof in sellers
    ]
    return {"cardsV2": [{
        "cardId": "snakeCustomer",
        "card": {
            "header": {"title": "You're the customer! 🛒", "subtitle": f"{round.persona} · {round.problem}"},
            "sections": [
                {"widgets": [{"textParagraph": {"text": "Who sold the best product?\n\n" + "\n".join(lines)}}]},
                {"widgets": [{"buttonList": {"buttons": buttons}}]},
            ],
        },
    }]}


def build_done_card(text: str, card_id: str = "snakeCustomer") -> dict:
    return {"cardsV2": [{
        "cardId": card_id,
        "card": {"header": {"title": "Round over ✅"},
                 "sections": [{"widgets": [{"textParagraph": {"text": text}}]}]},
    }]}


# --- Вспомогательные запросы ---


async def _players_of_game(db: AsyncSession, game_id: int) -> list[tuple[SnakePlayer, Profile]]:
    # populate_existing — свежие score после атомарных UPDATE (см. alias_game.py).
    rows = (await db.execute(
        select(SnakePlayer, Profile)
        .join(Profile, Profile.id == SnakePlayer.profile_id)
        .where(SnakePlayer.game_id == game_id)
        .order_by(SnakePlayer.joined_at)
        .execution_options(populate_existing=True)
    )).all()
    return [(sp, prof) for sp, prof in rows]


async def _change_score(db: AsyncSession, game_id: int, profile_id: int, delta: int) -> None:
    """Атомарно сдвинуть счёт игрока (score = score + delta) без гонок."""
    await db.execute(
        update(SnakePlayer)
        .where(SnakePlayer.game_id == game_id, SnakePlayer.profile_id == profile_id)
        .values(score=SnakePlayer.score + delta)
    )


def _is_solo(players: list[tuple[SnakePlayer, Profile]]) -> bool:
    return any(_is_bot(prof) for _, prof in players)


def _bot_of(players: list[tuple[SnakePlayer, Profile]]) -> Profile:
    for _, prof in players:
        if _is_bot(prof):
            return prof
    raise ValueError("bot not in players")


def _send_dm_card(profile: Profile, cards_v2: list[dict], text: str = "") -> str:
    ws = profile.workspace_user_id or ""
    if not ws.startswith("users/"):
        logger.warning("snake_dm_skip_no_workspace profile=%s", profile.id)
        return ""
    dm = find_user_dm_space(ws)
    if not dm:
        logger.warning("snake_dm_not_found profile=%s", profile.id)
        return ""
    resp = send_space_message(dm, text=text, cards_v2=cards_v2)
    return resp.get("name", "")


async def _refresh_scoreboard(db: AsyncSession, game: SnakeGame) -> None:
    if not game.scoreboard_message_name:
        return
    players = await _players_of_game(db, game.id)
    card = build_scoreboard_card(game, players, _action_url())
    try:
        patch_message(game.scoreboard_message_name, cards_v2=card["cardsV2"])
    except Exception:
        logger.exception("snake_scoreboard_patch_failed game=%s", game.id)


def build_round_card(
    round: SnakeRound, customer: Profile, previous_result: str, solo: bool,
) -> dict:
    """Карточка текущего раунда в группе (патчится на месте каждый раунд)."""
    if solo:
        buyer = f"🛒 Customer: 🤖 Bot — {round.persona}"
        hint = "Come up with a product and press «Ready» in your DM 🎤"
    else:
        buyer = f"🛒 Customer: {_display(customer)} — {round.persona}"
        hint = "Sellers are preparing their products… 🎤"
    lines = []
    if previous_result:
        lines.append(previous_result)
    lines.append(buyer)
    lines.append(f"❗ Problem: {round.problem}")
    lines.append(hint)
    return {"cardsV2": [{
        "cardId": "snakeRound",
        "card": {
            "header": {"title": f"Round {round.number} 🧪", "subtitle": "Snake Oil"},
            "sections": [{"widgets": [{"textParagraph": {"text": "\n".join(lines)}}]}],
        },
    }]}


async def _show_round(
    db: AsyncSession, game: SnakeGame, round: SnakeRound, customer: Profile,
    previous_result: str = "", solo: bool = False,
) -> None:
    """Показать карточку раунда: отправить (первый раз) или обновить на месте."""
    card = build_round_card(round, customer, previous_result, solo)
    if game.round_message_name:
        try:
            patch_message(game.round_message_name, cards_v2=card["cardsV2"])
            return
        except Exception:
            logger.exception("snake_round_patch_failed game=%s", game.id)
    resp = send_space_message(game.space_id, cards_v2=card["cardsV2"])
    game.round_message_name = resp.get("name")
    await db.commit()


# --- Судья (LLM) для одиночного режима ---


def _extract_text(resp_json: dict) -> str:
    content = resp_json.get("content")
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts)


def _judge_pair(
    persona: str, problem: str, a_words: tuple[str, str], b_words: tuple[str, str], timeout: float = 15.0,
) -> int | None:
    """Вернуть 1 или 2 — номер выигрышной пары слов. None при сбое (фолбэк — случайно)."""
    settings = get_settings()
    api_key = settings.llm_api_key
    model = settings.llm_model
    if not api_key or not model:
        return None
    base_url = (settings.llm_base_url or "https://llm.azati.ai").rstrip("/")
    system = (
        "You are the customer in the game \"Snake Oil\". Your role and everyday problem "
        "are given. You are offered two products, each built from two random words. Pick the "
        'better/funnier product. Return strictly JSON of the form {"winner": 1}, where 1 or 2 '
        "is the product number. No commentary or markup."
    )
    user_prompt = (
        f"Customer role: {persona}\nProblem: {problem}\n\n"
        f"Product 1: {a_words[0]} + {a_words[1]}\n"
        f"Product 2: {b_words[0]} + {b_words[1]}\n\n"
        "Which product will the customer choose? Return JSON."
    )
    payload = {
        "model": model,
        "max_tokens": 128,
        "system": system,
        "messages": [{"role": "user", "content": user_prompt}],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    try:
        resp = requests.post(
            f"{base_url}/v1/messages", json=payload, headers=headers, timeout=timeout,
        )
        resp.raise_for_status()
        data = json.loads(_extract_text(resp.json()))
        winner = data.get("winner") if isinstance(data, dict) else None
        if winner in (1, 2, "1", "2"):
            return int(winner)
    except Exception:
        logger.warning("snake_judge_failed", exc_info=True)
    return None


async def _judge_round(
    round: SnakeRound, offers: list[tuple[SnakeOffer, Profile]],
) -> Profile:
    """Выбрать победителя в solo-раунде: LLM между парой игрока и парой бота."""
    user = next((p for o, p in offers if not _is_bot(p)), None)
    bot = next((p for o, p in offers if _is_bot(p)), None)
    user_offer = next((o for o, p in offers if not _is_bot(p)), None)
    bot_offer = next((o for o, p in offers if _is_bot(p)), None)
    if user is None or bot is None or user_offer is None or bot_offer is None:
        return random.choice([p for _, p in offers])
    choice = await asyncio.to_thread(
        _judge_pair,
        round.persona, round.problem,
        (user_offer.word1, user_offer.word2),
        (bot_offer.word1, bot_offer.word2),
    )
    if choice == 1:
        return user
    if choice == 2:
        return bot
    return random.choice([user, bot])


# --- Действия ---


async def setup_game(db: AsyncSession, space_name: str, target_score: int) -> dict:
    game = SnakeGame(space_id=space_name, status="setup", target_score=target_score)
    db.add(game)
    await db.flush()
    card = build_scoreboard_card(game, [], _action_url())
    resp = send_space_message(
        space_name, text="Snake Oil! 🧪 Gather up and press «Start»", cards_v2=card["cardsV2"],
    )
    game.scoreboard_message_name = resp.get("name")
    await db.commit()
    logger.info("snake_game_setup game=%s space=%s", game.id, space_name)
    return {"ok": True, "silent": True, "game_id": game.id}


async def game_from_command(db: AsyncSession, space_name: str, raw_text: str) -> dict:
    default = int((await get_or_create_config(db, "snake_target_score", 3)).value or 3)
    target = parse_snake_args(raw_text, default)
    return await setup_game(db, space_name, target)


async def _get_or_create_bot(db: AsyncSession) -> Profile:
    bot = (await db.execute(
        select(Profile).where(Profile.workspace_user_id == TEST_BOT_USER_ID)
    )).scalar_one_or_none()
    if bot is None:
        bot = Profile(
            workspace_user_id=TEST_BOT_USER_ID, user_email="snake_bot@test.local", user_name="Bot 🤖",
        )
        db.add(bot)
        await db.flush()
    return bot


async def setup_test_game(db: AsyncSession, space_name: str, user_profile: Profile, target_score: int) -> dict:
    """«снейк тест»: одиночная партия — игрок против бота (бот судит)."""
    game = SnakeGame(space_id=space_name, status="setup", target_score=target_score)
    db.add(game)
    await db.flush()
    bot = await _get_or_create_bot(db)
    db.add(SnakePlayer(game_id=game.id, profile_id=user_profile.id, score=0))
    db.add(SnakePlayer(game_id=game.id, profile_id=bot.id, score=0))
    await db.commit()

    players = await _players_of_game(db, game.id)
    card = build_scoreboard_card(game, players, _action_url())
    resp = send_space_message(
        space_name, text="Snake Oil (test): you vs the bot! 🤖", cards_v2=card["cardsV2"],
    )
    game.scoreboard_message_name = resp.get("name")
    await db.commit()
    logger.info("snake_test_game_setup game=%s space=%s", game.id, space_name)
    return {"ok": True, "silent": True, "game_id": game.id}


async def join_game(db: AsyncSession, profile: Profile, game_id: int) -> dict:
    """Кнопка «Я играю!»: записать игрока (идемпотентно), обновить карточку."""
    game = (await db.execute(select(SnakeGame).where(SnakeGame.id == game_id))).scalar_one_or_none()
    if game is None:
        return {"ok": False, "text": "Game not found 🤷"}
    if game.status != "setup":
        return {"ok": False, "text": "Game already started 🚀"}
    existing = (await db.execute(
        select(SnakePlayer).where(
            SnakePlayer.game_id == game_id, SnakePlayer.profile_id == profile.id,
        )
    )).scalar_one_or_none()
    if existing is None:
        db.add(SnakePlayer(game_id=game_id, profile_id=profile.id, score=0))
        await db.commit()

    players = await _players_of_game(db, game_id)
    card = build_scoreboard_card(game, players, _action_url())
    return {"ok": True, "cards_v2": card["cardsV2"]}


async def start_game(db: AsyncSession, game_id: int) -> dict:
    game = (await db.execute(select(SnakeGame).where(SnakeGame.id == game_id))).scalar_one_or_none()
    if game is None:
        return {"ok": False, "text": "Game not found 🤷"}
    if game.status != "setup":
        return {"ok": False, "text": "Game already started 🚀"}
    players = await _players_of_game(db, game_id)
    if len(players) < 2:
        return {"ok": False, "text": "Need at least 2 players 🙏"}

    game.status = "active"
    await db.commit()

    if _is_solo(players):
        customer = _bot_of(players)
    else:
        customer = random.choice([prof for _, prof in players])
    await _start_round(db, game, customer, players)

    card = build_scoreboard_card(game, players, _action_url())
    return {"ok": True, "cards_v2": card["cardsV2"]}


async def _start_round(
    db: AsyncSession, game: SnakeGame, customer: Profile, players: list[tuple[SnakePlayer, Profile]],
    previous_result: str = "",
) -> None:
    """Создать раунд: роль + проблема, раздать слова продавцам, отправить карточки."""
    solo = _is_solo(players)
    persona = random_persona()
    problem = random_problem(persona)

    if solo:
        sellers = players  # бот и игрок оба продают, бот-покупатель судит
    else:
        sellers = [(sp, p) for sp, p in players if sp.profile_id != customer.id]

    number = (await db.execute(
        select(func.coalesce(func.max(SnakeRound.number), 0)).where(SnakeRound.game_id == game.id)
    )).scalar_one() + 1
    round = SnakeRound(
        game_id=game.id, number=number, customer_profile_id=customer.id,
        persona=persona, problem=problem, status="active",
    )
    db.add(round)
    await db.flush()

    used: set[str] = set()
    offers: list[tuple[SnakeOffer, Profile]] = []
    for sp, prof in sellers:
        words = sample_product_words(2, exclude=used)
        if len(words) < 2:
            words = sample_product_words(2) or ["sponge", "robot"]
        used.update(words)
        offer = SnakeOffer(round_id=round.id, seller_profile_id=prof.id, word1=words[0], word2=words[1])
        db.add(offer)
        offers.append((offer, prof))
    await db.commit()
    await db.refresh(round)

    await _show_round(db, game, round, customer, previous_result, solo)

    for offer, prof in offers:
        if _is_bot(prof):
            continue
        card = build_seller_card(round, offer.word1, offer.word2, _action_url(), solo=solo)
        _send_dm_card(prof, card["cardsV2"], text="You're the seller! 🎤")

    if not solo:
        card = build_customer_card(round, offers, _action_url())
        _send_dm_card(customer, card["cardsV2"], text="Choose who you're buying from 🛒")

    logger.info("snake_round_started round=%s game=%s customer=%s", round.id, game.id, customer.id)


async def vote(db: AsyncSession, round_id: int, offer_id: int, voter: Profile) -> dict:
    """Покупатель нажимает «Выбрать»: зафиксировать победителя раунда."""
    round = (await db.execute(
        select(SnakeRound).where(SnakeRound.id == round_id)
    )).scalar_one_or_none()
    if round is None:
        return {"ok": False, "text": "Round not found 🤷"}
    if round.status != "active":
        return {"ok": False, "text": "Round already over"}
    if round.customer_profile_id != voter.id:
        return {"ok": False, "text": "Only the customer chooses 🛒"}
    offer = (await db.execute(
        select(SnakeOffer).where(SnakeOffer.id == offer_id, SnakeOffer.round_id == round_id)
    )).scalar_one_or_none()
    if offer is None:
        return {"ok": False, "text": "Offer not found 🤷"}
    game = (await db.execute(
        select(SnakeGame).where(SnakeGame.id == round.game_id)
    )).scalar_one_or_none()
    if game is None or game.status != "active":
        return {"ok": False, "text": "Game over 🏁"}
    winner = (await db.execute(
        select(Profile).where(Profile.id == offer.seller_profile_id)
    )).scalar_one_or_none()
    if winner is None:
        return {"ok": False, "text": "Seller not found 🤷"}
    return await _finalize_vote(db, round, game, winner)


async def solo_ready(db: AsyncSession, round_id: int) -> dict:
    """Кнопка «Готов(а)» в solo-режиме: LLM судит пару игрока против пары бота."""
    round = (await db.execute(
        select(SnakeRound).where(SnakeRound.id == round_id)
    )).scalar_one_or_none()
    if round is None:
        return {"ok": False, "text": "Round not found 🤷"}
    if round.status != "active":
        return {"ok": False, "text": "Round already over"}
    game = (await db.execute(
        select(SnakeGame).where(SnakeGame.id == round.game_id)
    )).scalar_one_or_none()
    if game is None or game.status != "active":
        return {"ok": False, "text": "Game over 🏁"}
    offers = (await db.execute(
        select(SnakeOffer, Profile)
        .join(Profile, Profile.id == SnakeOffer.seller_profile_id)
        .where(SnakeOffer.round_id == round_id)
        .order_by(SnakeOffer.id)
    )).all()
    offers = [(o, p) for o, p in offers]
    winner = await _judge_round(round, offers)
    return await _finalize_vote(db, round, game, winner)


async def _finalize_vote(db: AsyncSession, round: SnakeRound, game: SnakeGame, winner: Profile) -> dict:
    """Зафиксировать победителя раунда: +1 очко, проверить победу / начать следующий."""
    await _change_score(db, game.id, winner.id, 1)
    round.winner_profile_id = winner.id
    round.status = "finished"
    round.ended_at = datetime.now(timezone.utc)
    await db.commit()

    players = await _players_of_game(db, game.id)
    winner_sp = next((sp for sp, p in players if p.id == winner.id), None)
    customer = next((p for sp, p in players if sp.profile_id == round.customer_profile_id), None)
    cname = _display(customer) if customer else "Customer"
    score = winner_sp.score if winner_sp else 0
    result_line = f"🛍️ {cname} bought from {_display(winner)} — {_display(winner)} +1 ({score} pts)"

    if winner_sp is not None and winner_sp.score >= game.target_score:
        game.status = "finished"
        game.winner_profile_id = winner.id
        await db.commit()
        await _refresh_scoreboard(db, game)
        if game.round_message_name:
            try:
                patch_message(game.round_message_name, cards_v2=build_done_card(
                    _winner_congrats(winner, score), card_id="snakeRound",
                )["cardsV2"])
            except Exception:
                logger.exception("snake_winner_patch_failed game=%s", game.id)
        return {"ok": True, "cards_v2": build_done_card(
            _winner_congrats(winner, score),
        )["cardsV2"]}

    next_customer = _bot_of(players) if _is_solo(players) else winner
    await _start_round(db, game, next_customer, players, previous_result=result_line)
    await _refresh_scoreboard(db, game)
    return {"ok": True, "cards_v2": build_done_card("Next round started — check your DM 😉")["cardsV2"]}


def _build_finish_summary(game: SnakeGame, players: list[tuple[SnakePlayer, Profile]]) -> str:
    if not players:
        return "🏁 Game stopped — didn't finish"
    top_score = max(sp.score for sp, _ in players)
    leaders = [p for sp, p in players if sp.score == top_score]
    lines = ["🏁 Game stopped — didn't finish"]
    if len(leaders) == 1:
        lines.append(f"Closest to winning: {_display(leaders[0])} — {top_score} pts")
    else:
        names = ", ".join(_display(p) for p in leaders)
        lines.append(f"Tied in the lead: {names} — {top_score} pts each")
    lines.append(f"The goal was {game.target_score} points")
    return "\n".join(lines)


async def finish_game(db: AsyncSession, game_id: int) -> dict:
    """Кнопка «🏁 Закончить игру»: завершить досрочно и показать ближайший результат."""
    game = (await db.execute(select(SnakeGame).where(SnakeGame.id == game_id))).scalar_one_or_none()
    if game is None:
        return {"ok": False, "text": "Game not found 🤷"}
    if game.status == "finished":
        return {"ok": False, "text": "Game already finished"}

    players = await _players_of_game(db, game_id)
    top_score = max((sp.score for sp, _ in players), default=0)
    leaders = [p for sp, p in players if sp.score == top_score] if players else []
    game.status = "finished"
    game.winner_profile_id = leaders[0].id if len(leaders) == 1 else None
    await db.commit()

    await _refresh_scoreboard(db, game)
    summary = _build_finish_summary(game, players)
    try:
        send_space_message(game.space_id, text=summary)
    except Exception:
        logger.exception("snake_finish_msg_failed game=%s", game.id)

    card = build_scoreboard_card(game, players, _action_url())
    return {"ok": True, "cards_v2": card["cardsV2"]}
