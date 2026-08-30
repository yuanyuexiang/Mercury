"""核心表预留租户边界（§20 产品化定制路线）：tenant_id 默认 1，唯一约束改租户作用域。

当前阶段为客户独立实例部署（单租户，tenant_id 恒为 1），查询不做租户过滤；
本 migration 只为将来合并为多租户 SaaS 预留 schema 兼容性。

Revision ID: d5e6f7a8b9c0
Revises: c3d4e5f6a7b8
Create Date: 2026-08-30

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d5e6f7a8b9c0"
down_revision: str | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = (
    "telegram_updates",
    "users",
    "conversations",
    "leads",
    "knowledge_documents",
    "integration_jobs",
    "llm_providers",
    "audit_logs",
)


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column("tenant_id", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        )

    # 唯一约束改为租户作用域（多租户下同一 Telegram 用户可属于不同租户）
    op.drop_constraint("users_telegram_user_id_key", "users", type_="unique")
    op.create_index(
        "uq_users_tenant_telegram", "users", ["tenant_id", "telegram_user_id"], unique=True
    )

    op.drop_index("one_open_conversation", table_name="conversations")
    op.create_index(
        "one_open_conversation",
        "conversations",
        ["tenant_id", "telegram_chat_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("status != 'closed'"),
    )

    # 每租户至多一个激活供应商（原为全局唯一）
    op.drop_index("one_active_provider", table_name="llm_providers")
    op.create_index(
        "one_active_provider",
        "llm_providers",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )


def downgrade() -> None:
    op.drop_index("one_active_provider", table_name="llm_providers")
    op.create_index(
        "one_active_provider",
        "llm_providers",
        [sa.literal_column("(true)")],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.drop_index("one_open_conversation", table_name="conversations")
    op.create_index(
        "one_open_conversation",
        "conversations",
        ["telegram_chat_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("status != 'closed'"),
    )
    op.drop_index("uq_users_tenant_telegram", table_name="users")
    op.create_unique_constraint("users_telegram_user_id_key", "users", ["telegram_user_id"])
    for table in reversed(_TABLES):
        op.drop_column(table, "tenant_id")
