"""Add companies.provider_attempted_at — D&B attempt stamp for provider-first flow.

The main enrichment flow is now provider-only (DUNS linkage is the value);
misses no longer fall through to Claude. The stamp lets find_pending skip
already-attempted companies so the queue drains instead of looping on misses.
Additive/nullable.

Revision ID: n5d6e7f8a9b0
Revises: m4c5d6e7f8a9
Create Date: 2026-06-12 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "n5d6e7f8a9b0"
down_revision: str | None = "m4c5d6e7f8a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "companies", sa.Column("provider_attempted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(
        op.f("ix_companies_provider_attempted_at"), "companies",
        ["provider_attempted_at"], unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_companies_provider_attempted_at"), table_name="companies")
    op.drop_column("companies", "provider_attempted_at")
