"""llm_providers 增加 embed_model——后台可完整配置 LLM，env 降级为兜底（§12 修订）

Revision ID: c3d4e5f6a7b8
Revises: b7c8d9e0f1a2
Create Date: 2026-08-30

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "b7c8d9e0f1a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("llm_providers", sa.Column("embed_model", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("llm_providers", "embed_model")
