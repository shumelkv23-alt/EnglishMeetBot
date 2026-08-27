# app/services/games/spy.py
"""Шпион: рандомная тема+слово, тайный шпион, голосование, очки."""
import logging
import random

from app.messaging import send_message as send_dm
from app.schemas import MessagePayload
from app.services.games.scores import award_points
from app.services.games.session import GameManager
from app.services.onboarding import get_or_create_profile

logger = logging.getLogger(__name__)

WORD_BANK: dict[str, list[str]] = {
    "food": ["pizza", "sushi", "pancake", "popcorn", "sandwich"],
    "animals": ["penguin", "kangaroo", "octopus", "hamster", "flamingo"],
    "objects": ["umbrella", "backpack", "toothbrush", "microwave", "scooter"],
    "places": ["airport", "beach", "library", "gym", "cinema"],
}


def assign_roles(players: list[str], rng: random.Random | None = None) -> dict:
    """Choose тему, слово и шпиона. rng — для детерминированных тестов."""
    rng = rng or random
    topic = rng.choice(list(WORD_BANK.keys()))
    word = rng.choice(WORD_BANK[topic])
    spy = rng.choice(players)
    return {"topic": topic, "word": word, "spy": spy}


def tally_votes(votes: dict[str, str], players: list[str]) -> dict[str, int]:
    """Сколько голосов набрал каждый игрок (нули для тех, за кого не голосовали)."""
    tally = {p: 0 for p in players}
    for target in votes.values():
        tally[target] = tally.get(target, 0) + 1
    return tally


def score_spy(spy: str, votes: dict[str, str], players: list[str]) -> dict[str, int]:
    """Очки за раунд: {user_id: positive_points}.

    Шпион пойман, только если у него строго больше голосов, чем у любого другого.
    """
    tally: dict[str, int] = {}
    for target in votes.values():
        tally[target] = tally.get(target, 0) + 1
    spy_votes = tally.get(spy, 0)
    others_max = max((c for t, c in tally.items() if t != spy), default=0)
    caught = spy_votes > 0 and spy_votes > others_max
    if caught:
        return {p: 1 for p in players if p != spy}
    return {spy: 3}


def build_spy_vote_card(
    names: dict[str, str],
    players: list[str],
    action_url: str,
    votes: dict[str, str] | None = None,
) -> dict:
    """Карточка «Кто шпион?» с кнопкой-именем и живой сводкой голосов.

    votes — {голосующий: цель}. Если заданы, карточка показывает счётчик голосов
    за каждого и список тех, кто ещё не проголосовал.
    """
    votes = votes or {}
    buttons = [
        {
            "text": names.get(p, p),
            "onClick": {
                "action": {
                    "function": action_url,
                    "parameters": [{"key": "method", "value": "spy_vote"}, {"key": "target", "value": p}],
                }
            },
        }
        for p in players
    ]
    tally = tally_votes(votes, players)
    status_text = "Votes: " + ", ".join(f"{names.get(p, p)} — {tally[p]}" for p in players)
    waiting = [p for p in players if p not in votes]
    if waiting:
        status_text += "\nWaiting to vote: " + ", ".join(names.get(p, p) for p in waiting)
    sections = [
        {"widgets": [{"textParagraph": {"text": status_text}}]},
        {"widgets": [{"buttonList": {"buttons": buttons}}]},
    ]
    return {
        "cardsV2": [
            {
                "cardId": "spy_vote",
                "card": {
                    "header": {"title": "Who's the spy? 🕵️", "subtitle": "Vote for a suspect"},
                    "sections": sections,
                },
            }
        ]
    }


def build_start_vote_card(topic: str, action_url: str) -> dict:
    """Карточка после раздачи: тема + кнопка «Start voting»."""
    return {
        "cardsV2": [
            {
                "cardId": "spy_start_vote",
                "card": {
                    "header": {"title": f"Topic: {topic}", "subtitle": "Discuss the word! When ready — we vote."},
                    "sections": [
                        {
                            "widgets": [
                                {
                                    "buttonList": {
                                        "buttons": [
                                            {
                                                "text": "Start voting",
                                                "onClick": {
                                                    "action": {
                                                        "function": action_url,
                                                        "parameters": [{"key": "method", "value": "spy_start_vote"}],
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


def start_spy(session, action_url: str) -> dict:
    """Раздать роли: не-шпионам слово, шпиону — «ты шпион». Вернуть карточку с темой."""
    roles = assign_roles(session.players)
    topic, word, spy = roles["topic"], roles["word"], roles["spy"]
    session.state.update({"topic": topic, "word": word, "spy": spy, "votes": {}})
    for player in session.players:
        text = f"You are the spy 🤫. Topic: {topic}" if player == spy else f"Your word: {word}"
        send_dm(player, MessagePayload(text=text))
    return build_start_vote_card(topic, action_url)


async def vote(db, session, user_id: str, target: str, space_name: str, action_url: str) -> dict | None:
    """Записать голос «кто шпион»; когда проголосовали все — подсчёт и очки.

    Возвращает None (раунд уже подсчитан), обновлённую карточку ({"cardsV2"}), пока
    ждём остальных, или финальный текст ({"text"}).
    """
    state = session.state
    if state.get("scored"):
        return None  # раунд уже подсчитан
    if state.get("votes") is None:
        return None  # протухшая карточка / раунд ещё не начат
    if user_id not in session.players:
        return None  # голос чужака не считаем
    votes = state["votes"]
    votes[user_id] = target
    if len(votes) < len(session.players):
        return build_spy_vote_card(session.names, session.players, action_url, votes)
    state["scored"] = True  # до первого await — чтобы повторный клик не начислил очки дважды

    score = score_spy(state["spy"], votes, session.players)
    for user, points in score.items():
        profile = await get_or_create_profile(db, workspace_user_id=user)
        await award_points(db, profile.id, points, "spy")
    GameManager.end(space_name)
    spy_name = session.names.get(state["spy"], state["spy"])
    tally = tally_votes(votes, session.players)
    vote_lines = [f"{session.names.get(p, p)}: {tally[p]}" for p in session.players]
    score_lines = [f"{session.names.get(u, u)}: +{p}" for u, p in score.items()]
    return {
        "text": (
            f"The spy was {spy_name}! Word: {state['word']}\n\n"
            f"Voting:\n" + "\n".join(vote_lines) + "\n\n"
            f"Points:\n" + "\n".join(score_lines)
        )
    }
