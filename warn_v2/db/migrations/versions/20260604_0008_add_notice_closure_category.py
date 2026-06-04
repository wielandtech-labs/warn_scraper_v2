"""Add notices.closure_category — normalized, filterable closure bucket.

Freeform ``closure_type`` text is batched into 'Closure' | 'Layoff' | NULL so
the API/UI can filter by type.  Backfills existing rows from their current
``closure_type`` using the same normalizer the ingest path uses.

Revision ID: i0e1f2a3b4c5
Revises: h9d0e1f2a3b4
Create Date: 2026-06-04 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from warn_v2.closure import normalize_closure_category

revision: str = "i0e1f2a3b4c5"
down_revision: str | None = "h9d0e1f2a3b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("notices", sa.Column("closure_category", sa.String(16), nullable=True))
    op.create_index(
        "ix_notices_closure_category", "notices", ["closure_category"]
    )
    _backfill()


def _backfill() -> None:
    """Set closure_category from existing closure_type values."""
    conn = op.get_bind()
    notices = sa.table(
        "notices",
        sa.column("notice_id", sa.String),
        sa.column("closure_type", sa.Text),
        sa.column("closure_category", sa.String),
    )
    rows = conn.execute(
        sa.select(notices.c.notice_id, notices.c.closure_type).where(
            notices.c.closure_type.isnot(None)
        )
    ).all()

    update = (
        notices.update()
        .where(notices.c.notice_id == sa.bindparam("nid"))
        .values(closure_category=sa.bindparam("cat"))
    )
    params = [
        {"nid": nid, "cat": cat}
        for nid, raw in rows
        if (cat := normalize_closure_category(raw)) is not None
    ]
    if params:
        conn.execute(update, params)


def downgrade() -> None:
    op.drop_index("ix_notices_closure_category", table_name="notices")
    op.drop_column("notices", "closure_category")
