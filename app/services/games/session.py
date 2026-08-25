# app/services/games/session.py
"""Каркас игр: in-memory сессия и карточка «Who's playing?»."""
from dataclasses import dataclass, field


@dataclass
class GameSession:
    """Одна игра в одном пространстве (in-memory: рестарт бота сбрасывает всё)."""

    game: str
    players: list[str] = field(default_factory=list)      # workspace_user_id по порядку
    names: dict[str, str] = field(default_factory=dict)   # workspace_user_id -> display_name
    state: dict = field(default_factory=dict)             # игра-специфичное состояние
    started: bool = False


class GameManager:
    """Синглтон-реестр активных игр: {space_name: GameSession}."""

    _sessions: dict[str, GameSession] = {}

    @classmethod
    def get(cls, space_id: str) -> GameSession | None:
        return cls._sessions.get(space_id)

    @classmethod
    def start(cls, game: str, space_id: str) -> GameSession:
        session = GameSession(game=game)
        cls._sessions[space_id] = session
        return session

    @classmethod
    def join(cls, space_id: str, user_id: str, name: str = "") -> GameSession | None:
        session = cls.get(space_id)
        if session is None or session.started:
            return None
        if user_id not in session.players:
            session.players.append(user_id)
        if name:
            session.names[user_id] = name
        return session

    @classmethod
    def end(cls, space_id: str) -> None:
        cls._sessions.pop(space_id, None)

    @classmethod
    def reset(cls) -> None:
        cls._sessions.clear()


def build_join_card(
    action_url: str,
    title: str,
    players: list[str] | None = None,
    names: dict[str, str] | None = None,
) -> dict:
    """Карточка «Who's playing?» с кнопками «I'm in» (join_game) и «Начать» (start_game).

    Если переданы players/names — в тексте карточки показываем текущий состав и счётчик.
    """
    players = players or []
    names = names or {}
    status = ""
    if players:
        roster = ", ".join(names.get(p, p) for p in players)
        status = f"Playing ({len(players)}): {roster}"
    return {
        "cardsV2": [
            {
                "cardId": "game_lobby",
                "card": {
                    "header": {"title": title, "subtitle": "Who's playing?"},
                    "sections": [
                        {
                            "widgets": [
                                {
                                    "textParagraph": {
                                        "text": "Press 'I'm in' to join. When everyone's ready — 'Start'."
                                        + (f"\n{status}" if status else "")
                                    }
                                }
                            ]
                        },
                        {
                            "widgets": [
                                {
                                    "buttonList": {
                                        "buttons": [
                                            {
                                                "text": "I'm in",
                                                "onClick": {
                                                    "action": {
                                                        "function": action_url,
                                                        "parameters": [{"key": "method", "value": "join_game"}],
                                                    }
                                                },
                                            },
                                            {
                                                "text": "Start",
                                                "onClick": {
                                                    "action": {
                                                        "function": action_url,
                                                        "parameters": [{"key": "method", "value": "start_game"}],
                                                    }
                                                },
                                            },
                                        ]
                                    }
                                }
                            ]
                        },
                    ],
                },
            }
        ]
    }
