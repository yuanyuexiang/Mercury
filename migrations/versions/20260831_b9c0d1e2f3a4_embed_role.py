"""检索槽位显式落库（§12 修订：对话/检索双槽位）：llm_providers.is_embed_active。

模型配置改为"服务商只管密钥 + 两个用途槽位"：is_active = 对话槽，is_embed_active = 检索槽，
两者可指向不同服务商。数据迁移：把此前隐式解析会选中的行（激活优先、其次最近更新且配了
embed_model 的行）标记为检索槽，行为不变。

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-08-31

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b9c0d1e2f3a4"
down_revision: str | None = "a8b9c0d1e2f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "llm_providers",
        sa.Column("is_embed_active", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    # 每租户至多一个检索槽（与 one_active_provider 同构）
    op.create_index(
        "one_embed_active_provider",
        "llm_providers",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_embed_active"),
    )
    # 数据迁移：沿用旧隐式解析的选择，避免升级后检索配置丢失
    op.execute(
        """
        UPDATE llm_providers SET is_embed_active = true WHERE id = (
            SELECT id FROM llm_providers
            WHERE embed_model IS NOT NULL
            ORDER BY is_active DESC, updated_at DESC
            LIMIT 1
        )
        """
    )


def downgrade() -> None:
    op.drop_index("one_embed_active_provider", table_name="llm_providers")
    op.drop_column("llm_providers", "is_embed_active")
