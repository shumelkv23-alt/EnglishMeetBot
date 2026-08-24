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
    """Выбрать тему, слово и шпиона. rng — для детерминированных тестов."""
    rng = rng or random
    topic = rng.choice(list(WORD_BANK.keys()))
    word = rng.choice(WORD_BANK[topic])
    spy = rng.choice(players)
    return {"topic": topic, "word": word, "spy": spy}


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


def build_spy_vote_card(names: dict[str, str], players: list[str], action_url: str) -> dict:
    """Карточка «Кто шпион?» с кнопкой-именем на каждого игрока."""
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
    return {
        "cardsV2": [
            {
                "cardId": "spy_vote",
                "card": {
                    "header": {"title": "Кто шпион? 🕵️", "subtitle": "Голосуй за подозреваемого"},
                    "sections": [{"widgets": [{"buttonList": {"buttons": buttons}}]}],
                },
            }
        ]
    }


def build_start_vote_card(topic: str, action_url: str) -> dict:
    """Карточка после раздачи: тема + кнопка «Начать голосование»."""
    return {
        "cardsV2": [
            {
                "cardId": "spy_start_vote",
                "card": {
                    "header": {"title": f"Тема: {topic}", "subtitle": "Обсуждайте слово! Когда готовы — голосуем."},
                    "sections": [
                        {
                            "widgets": [
                                {
                                    "buttonList": {
                                        "buttons": [
                                            {
                                                "text": "Начать голосование",
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
        text = f"Ты шпион 🤫. Тема: {topic}" if player == spy else f"Твоё слово: {word}"
        send_dm(player, MessagePayload(text=text))
    return build_start_vote_card(topic, action_url)


async def vote(db, session, user_id: str, target: str, space_name: str) -> dict | None:
    """Записать голос «кто шпион»; когда проголосовали все — подсчёт и очки."""
    state = session.state
    votes = state["votes"]
    votes[user_id] = target
    if len(votes) < len(session.players):
        return None  # ждём остальных

    score = score_spy(state["spy"], votes, session.players)
    for user, points in score.items():
        profile = await get_or_create_profile(db, workspace_user_id=user)
        await award_points(db, profile.id, points, "spy")
    GameManager.end(space_name)
    spy_name = session.names.get(state["spy"], state["spy"])
    lines = [f"{session.names.get(u, u)}: +{p}" for u, p in score.items()]
    return {"text": f"Шпионом был {spy_name}! Слово: {state['word']}\n\n" + "\n".join(lines)}
