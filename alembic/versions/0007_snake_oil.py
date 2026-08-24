"""snake_oil — таблицы для игры Snake Oil / «Змеиное масло»
(snake_games, snake_players, snake_rounds, snake_offers)

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007"
down_revision: Union[str, Sequence[str], None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "snake_games",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("space_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=50), server_default=sa.text("'setup'"), nullable=False),
        sa.Column("target_score", sa.Integer(), server_default=sa.text("3"), nullable=False),
        sa.Column("scoreboard_message_name", sa.String(length=255), nullable=True),
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


def downgrade() -> None:
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
