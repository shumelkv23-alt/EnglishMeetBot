"""alias_game — таблицы для игры Alias (games, game_teams, game_players, game_rounds, game_word_events)

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006"
down_revision: Union[str, Sequence[str], None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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


def downgrade() -> None:
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
