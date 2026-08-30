"""渠道归因：conversations/leads 加 source_channel（/start 深链参数，首触归因）。

客户在不同投放位使用 t.me/<bot>?start=<渠道标识> 深链，/start 时记录到会话，
线索创建时继承——回答"哪个渠道的钱花得值"。

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-08-30

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e6f7a8b9c0d1"
down_revision: str | None = "d5e6f7a8b9c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("source_channel", sa.Text(), nullable=True))
    op.add_column("leads", sa.Column("source_channel", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("leads", "source_channel")
    op.drop_column("conversations", "source_channel")
