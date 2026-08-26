"""движок карточек: card_types, cards, content_bank

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0010"
down_revision: Union[str, Sequence[str], None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "card_types",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("min_group_size", sa.Integer(), server_default=sa.text("2"), nullable=False),
        sa.Column("max_group_size", sa.Integer(), nullable=True),
        sa.Column("cefr_min", sa.String(length=10), nullable=False),
        sa.Column("cefr_max", sa.String(length=10), nullable=False),
        sa.Column("base_weight", sa.Float(), nullable=False),
        sa.Column("cooldown", sa.Integer(), server_default=sa.text("3"), nullable=False),
        sa.Column("safety_tier", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "cards",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("space_id", sa.String(length=255), nullable=False),
        sa.Column("meeting_id", sa.BigInteger(), sa.ForeignKey("meeting_instances.id"), nullable=False),
        sa.Column("card_type_id", sa.BigInteger(), sa.ForeignKey("card_types.id"), nullable=False),
        sa.Column("difficulty_level", sa.String(length=10), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.Column("generated_by", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_cards_space_created", "cards", ["space_id", "created_at"])
    op.create_index("idx_cards_meeting", "cards", ["meeting_id"])
    op.create_index("idx_cards_type", "cards", ["card_type_id"])

    op.create_table(
        "content_bank",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("card_type_id", sa.BigInteger(), sa.ForeignKey("card_types.id"), nullable=False),
        sa.Column("safety_tier", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("is_approved", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("added_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_content_bank_type", "content_bank", ["card_type_id"])
    op.create_index("idx_content_bank_approved", "content_bank", ["is_approved"])


def downgrade() -> None:
    op.drop_table("content_bank")
    op.drop_table("cards")
    op.drop_table("card_types")
