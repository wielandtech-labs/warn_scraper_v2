"""Add is_superseded flag to notices.

Enables deduplication of amendment/duplicate WARN notice pairs without
deleting data.  The mark-superseded CLI command populates this field;
stats queries filter it out so totals reflect the final authoritative
notice for each layoff event.

Revision ID: f7b8c9d0e1f2
Revises: e5f6a7b8c9d0
Create Date: 2026-05-29 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f7b8c9d0e1f2"
down_revision: str | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "notices",
        sa.Column("is_superseded", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_index("ix_notices_is_superseded", "notices", ["is_superseded"])


def downgrade() -> None:
    op.drop_index("ix_notices_is_superseded", table_name="notices")
    op.drop_column("notices", "is_superseded")
