"""沉睡线索唤醒：leads 加 revive_count / last_revived_at（防骚扰的幂等依据）。

Revision ID: a8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-08-31

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a8b9c0d1e2f3"
down_revision: str | None = "f7a8b9c0d1e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "leads",
        sa.Column("revive_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column("leads", sa.Column("last_revived_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("leads", "last_revived_at")
    op.drop_column("leads", "revive_count")
