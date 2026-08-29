"""leads 增加事实布尔列 asked_demo / freebie_only（§8 评分依据，替代 notes 标记设计）

Revision ID: a1b2c3d4e5f6
Revises: d7cafe5c6cbd
Create Date: 2026-08-30

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "d7cafe5c6cbd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "leads",
        sa.Column("asked_demo", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "leads",
        sa.Column("freebie_only", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("leads", "freebie_only")
    op.drop_column("leads", "asked_demo")
