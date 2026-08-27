"""onboarding_invite_sent"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005b"
down_revision: Union[str, Sequence[str], None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "profiles",
        sa.Column("onboarding_invite_sent", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("profiles", "onboarding_invite_sent")
