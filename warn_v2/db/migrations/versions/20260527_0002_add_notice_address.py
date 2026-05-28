"""Add notices.address column for layoff-site mailing address.

Most state WARN forms include a layoff-site street address; previously this
data was dropped on the floor (or stashed in NoticeRow.extra, which is not
persisted). Promote it to a first-class column.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-05-27 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("notices", sa.Column("address", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("notices", "address")
