"""Add enrichment_source column to companies.

Records which tier of the enrichment cascade populated each row:
  'provider' | 'edgar' | 'claude'

Additive migration — nullable, no data risk. Rows enriched before this
migration are left NULL; they can be backfilled later if needed.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-05-29 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("enrichment_source", sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_column("companies", "enrichment_source")
