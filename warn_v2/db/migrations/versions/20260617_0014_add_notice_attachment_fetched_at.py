"""Add notices.attachment_fetched_at — GA enricher fetch stamp.

The GA enricher's candidate set keyed off ``pdf_path IS NULL`` (among other
NULL fields), so notices whose TCSG attachment is a non-PDF (Word/Excel) — never
stored as a PDF — stayed candidates forever and, being newest-first, starved the
rest of the backlog. This stamp marks "entry page + attachment processed" so a
fetched notice drops out of the queue regardless of which fields the source could
supply. Additive/nullable, indexed for the IS NULL candidate filter.

Revision ID: o6e7f8a9b0c1
Revises: n5d6e7f8a9b0
Create Date: 2026-06-17 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "o6e7f8a9b0c1"
down_revision: str | None = "n5d6e7f8a9b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "notices",
        sa.Column("attachment_fetched_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f("ix_notices_attachment_fetched_at"), "notices",
        ["attachment_fetched_at"], unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_notices_attachment_fetched_at"), table_name="notices")
    op.drop_column("notices", "attachment_fetched_at")
