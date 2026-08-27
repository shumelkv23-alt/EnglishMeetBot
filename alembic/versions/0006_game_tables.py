"""игровые таблицы: Alias, Snake Oil, «Кто я?»/Quiplash + 'game' event_type + config seed

Консолидированная миграция из tree-проекта (0006–0009):
- games, game_teams, game_players, game_rounds, game_word_events (Alias)
- snake_games, snake_players, snake_rounds, snake_offers (Snake Oil)
- game_sessions («Кто я?» / Quiplash)
- расширение CHECK leaderboard_ledger типом 'game'
- сидинг config параметров игр

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006"
down_revision: Union[str, Sequence[str], None] = "0005b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Alias ---
    op.create_table(
        "games",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("space_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=50), server_default=sa.text("'setup'"), nullable=False),
        sa.Column("target_score", sa.Integer(), server_default=sa.text("15"), nullable=False),
        sa.Column("round_seconds", sa.Integer(), server_default=sa.text("60"), nullable=False),
        sa.Column("scoreboard_message_name", sa.String(length=255), nullable=True),
        sa.Column("winner_team_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('setup', 'active', 'finished')", name="valid_game_status"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_games_space", "games", ["space_id"])
    op.create_index("idx_games_status", "games", ["status"])

    op.create_table(
        "game_teams",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("game_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("emoji", sa.String(length=20), nullable=False),
        sa.Column("score", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_game_teams_game", "game_teams", ["game_id"])

    op.create_table(
        "game_players",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("game_id", sa.BigInteger(), nullable=False),
        sa.Column("team_id", sa.BigInteger(), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"]),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"]),
        sa.ForeignKeyConstraint(["team_id"], ["game_teams.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("game_id", "profile_id", name="unique_game_player"),
    )
    op.create_index("idx_game_players_game", "game_players", ["game_id"])
    op.create_index("idx_game_players_team", "game_players", ["team_id"])
    op.create_index("idx_game_players_profile", "game_players", ["profile_id"])

    op.create_table(
        "game_rounds",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("game_id", sa.BigInteger(), nullable=False),
        sa.Column("team_id", sa.BigInteger(), nullable=False),
        sa.Column("explainer_profile_id", sa.BigInteger(), nullable=False),
        sa.Column("current_word", sa.String(length=100), nullable=True),
        sa.Column("word_message_name", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=50), server_default=sa.text("'active'"), nullable=False),
        sa.Column("points_adjustment", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('active', 'time_up', 'confirming', 'confirmed')",
            name="valid_round_status",
        ),
        sa.ForeignKeyConstraint(["explainer_profile_id"], ["profiles.id"]),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"]),
        sa.ForeignKeyConstraint(["team_id"], ["game_teams.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_game_rounds_game", "game_rounds", ["game_id"])
    op.create_index("idx_game_rounds_team", "game_rounds", ["team_id"])

    op.create_table(
        "game_word_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("round_id", sa.BigInteger(), nullable=False),
        sa.Column("word", sa.String(length=100), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.BigInteger(), nullable=False),
        sa.Column("is_last", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["round_id"], ["game_rounds.id"]),
        sa.ForeignKeyConstraint(["team_id"], ["game_teams.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_game_word_events_round", "game_word_events", ["round_id"])
    op.create_index("idx_game_word_events_team", "game_word_events", ["team_id"])

    # --- Snake Oil ---
    op.create_table(
        "snake_games",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("space_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=50), server_default=sa.text("'setup'"), nullable=False),
        sa.Column("target_score", sa.Integer(), server_default=sa.text("3"), nullable=False),
        sa.Column("scoreboard_message_name", sa.String(length=255), nullable=True),
        sa.Column("round_message_name", sa.String(length=255), nullable=True),
        sa.Column("winner_profile_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('setup', 'active', 'finished')", name="valid_snake_game_status"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_snake_games_space", "snake_games", ["space_id"])
    op.create_index("idx_snake_games_status", "snake_games", ["status"])

    op.create_table(
        "snake_players",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("game_id", sa.BigInteger(), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("score", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["game_id"], ["snake_games.id"]),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("game_id", "profile_id", name="unique_snake_player"),
    )
    op.create_index("idx_snake_players_game", "snake_players", ["game_id"])
    op.create_index("idx_snake_players_profile", "snake_players", ["profile_id"])

    op.create_table(
        "snake_rounds",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("game_id", sa.BigInteger(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("customer_profile_id", sa.BigInteger(), nullable=False),
        sa.Column("persona", sa.String(length=100), nullable=False),
        sa.Column("problem", sa.String(length=255), nullable=False),
        sa.Column("winner_profile_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=50), server_default=sa.text("'active'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('active', 'finished')", name="valid_snake_round_status"),
        sa.ForeignKeyConstraint(["customer_profile_id"], ["profiles.id"]),
        sa.ForeignKeyConstraint(["game_id"], ["snake_games.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_snake_rounds_game", "snake_rounds", ["game_id"])

    op.create_table(
        "snake_offers",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("round_id", sa.BigInteger(), nullable=False),
        sa.Column("seller_profile_id", sa.BigInteger(), nullable=False),
        sa.Column("word1", sa.String(length=100), nullable=False),
        sa.Column("word2", sa.String(length=100), nullable=False),
        sa.ForeignKeyConstraint(["round_id"], ["snake_rounds.id"]),
        sa.ForeignKeyConstraint(["seller_profile_id"], ["profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("round_id", "seller_profile_id", name="unique_snake_offer"),
    )
    op.create_index("idx_snake_offers_round", "snake_offers", ["round_id"])

    # --- «Кто я?» / Quiplash ---
    op.create_table(
        "game_sessions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("meeting_instance_id", sa.BigInteger(), nullable=True),
        sa.Column("space_name", sa.String(length=255), nullable=False),
        sa.Column("game_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), server_default=sa.text("'active'"), nullable=False),
        sa.Column("topic", sa.String(length=255), nullable=True),
        sa.Column("state", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["meeting_instance_id"], ["meeting_instances.id"]),
        sa.CheckConstraint("game_type IN ('who_am_i', 'quiplash')", name="valid_game_type"),
        sa.CheckConstraint(
            "status IN ('active', 'finished', 'cancelled')", name="valid_game_status"
        ),
    )
    op.create_index("idx_game_sessions_space_status", "game_sessions", ["space_name", "status"])
    op.create_index("idx_game_sessions_meeting", "game_sessions", ["meeting_instance_id"])

    # Расширить CHECK leaderboard_ledger: добавить тип события 'game' (очки игр)
    op.drop_constraint("valid_event_type", "leaderboard_ledger", type_="check")
    op.create_check_constraint(
        "valid_event_type",
        "leaderboard_ledger",
        "event_type IN ('attendance', 'answer', 'streak', 'mvp', 'bonus', 'game')",
    )

    # Сидинг config: параметры игр
    op.execute(
        """
        INSERT INTO config (key, value, description) VALUES
        ('quiplash_rounds', '10', 'Количество раундов в Quiplash'),
        ('quiplash_winner_points', '3', 'Очки победителю раунда Quiplash'),
        ('quiplash_second_points', '1', 'Очки второму месту раунда Quiplash'),
        ('who_am_i_guess_points', '2', 'Очки за угаданную сущность в «Кто я?»'),
        ('quiplash_answer_timeout_seconds', '300', 'Секунд на ответы в раунде Quiplash'),
        ('quiplash_vote_timeout_seconds', '120', 'Секунд на голосование в раунде Quiplash'),
        ('who_am_i_turn_timeout_seconds', '600', 'Секунд на ход угадывающего в «Кто я?»'),
        ('alias_round_seconds', '60', 'Секунд на раунд Alias'),
        ('alias_target_score', '15', 'Очки до победы в Alias'),
        ('snake_target_score', '3', 'Очки до победы в Snake Oil')
        ON CONFLICT (key) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM config WHERE key IN ('quiplash_rounds', 'quiplash_winner_points', 'quiplash_second_points', 'who_am_i_guess_points', 'quiplash_answer_timeout_seconds', 'quiplash_vote_timeout_seconds', 'who_am_i_turn_timeout_seconds', 'alias_round_seconds', 'alias_target_score', 'snake_target_score')"
    )
    op.drop_constraint("valid_event_type", "leaderboard_ledger", type_="check")
    op.create_check_constraint(
        "valid_event_type",
        "leaderboard_ledger",
        "event_type IN ('attendance', 'answer', 'streak', 'mvp', 'bonus')",
    )
    op.drop_index("idx_game_sessions_meeting", table_name="game_sessions")
    op.drop_index("idx_game_sessions_space_status", table_name="game_sessions")
    op.drop_table("game_sessions")
    op.drop_index("idx_snake_offers_round", table_name="snake_offers")
    op.drop_table("snake_offers")
    op.drop_index("idx_snake_rounds_game", table_name="snake_rounds")
    op.drop_table("snake_rounds")
    op.drop_index("idx_snake_players_profile", table_name="snake_players")
    op.drop_index("idx_snake_players_game", table_name="snake_players")
    op.drop_table("snake_players")
    op.drop_index("idx_snake_games_status", table_name="snake_games")
    op.drop_index("idx_snake_games_space", table_name="snake_games")
    op.drop_table("snake_games")
    op.drop_index("idx_game_word_events_team", table_name="game_word_events")
    op.drop_index("idx_game_word_events_round", table_name="game_word_events")
    op.drop_table("game_word_events")
    op.drop_index("idx_game_rounds_team", table_name="game_rounds")
    op.drop_index("idx_game_rounds_game", table_name="game_rounds")
    op.drop_table("game_rounds")
    op.drop_index("idx_game_players_profile", table_name="game_players")
    op.drop_index("idx_game_players_team", table_name="game_players")
    op.drop_index("idx_game_players_game", table_name="game_players")
    op.drop_table("game_players")
    op.drop_index("idx_game_teams_game", table_name="game_teams")
    op.drop_table("game_teams")
    op.drop_index("idx_games_status", table_name="games")
    op.drop_index("idx_games_space", table_name="games")
    op.drop_table("games")
