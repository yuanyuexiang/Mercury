"""messages.source_update_id 外键改 ON DELETE SET NULL——数据保留期清理不被阻断（§14）

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-08-30

"""

from collections.abc import Sequence

from alembic import op

revision: str = "b7c8d9e0f1a2"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FK = "messages_source_update_id_fkey"


def upgrade() -> None:
    op.drop_constraint(_FK, "messages", type_="foreignkey")
    op.create_foreign_key(
        _FK,
        "messages",
        "telegram_updates",
        ["source_update_id"],
        ["update_id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(_FK, "messages", type_="foreignkey")
    op.create_foreign_key(_FK, "messages", "telegram_updates", ["source_update_id"], ["update_id"])
