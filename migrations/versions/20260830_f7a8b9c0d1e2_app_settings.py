"""app_settings 表：后台可配的系统设置（Telegram 对接、品牌文案），敏感值 Fernet 加密。

延续 §12 模式：DB 优先 env 兜底、60s 缓存 + Redis 广播失效，后台改配置不重启即生效。

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-08-30

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f7a8b9c0d1e2"
down_revision: str | None = "e6f7a8b9c0d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("is_encrypted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
