"""leveled_progress

Revision ID: 0024
Revises: 0023
Create Date: 2026-08-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0024"
down_revision: Union[str, Sequence[str], None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 30. leveled_progress — прогресс раздела «English by level» в личке.
    # Одна строка на профиль; живое состояние в JSONB state (изученные темы,
    # пройденные тесты тем).
    op.create_table(
        "leveled_progress",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"]),
        sa.UniqueConstraint("profile_id", name="unique_leveled_progress_profile"),
    )
    op.create_index("idx_leveled_progress_profile", "leveled_progress", ["profile_id"])


def downgrade() -> None:
    op.drop_index("idx_leveled_progress_profile", table_name="leveled_progress")
    op.drop_table("leveled_progress")
