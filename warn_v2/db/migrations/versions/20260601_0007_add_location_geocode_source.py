"""Add locations.geocode_source — which geocoding tier populated lat/lon.

Records which tier of the geocoding cascade produced the coordinates:
  'census' | 'zip' | 'city' | 'county'

Additive migration — nullable, no data risk. Rows geocoded before this
migration are left NULL; they will be populated on the next backfill-geo run.

Revision ID: h9d0e1f2a3b4
Revises: g8c9d0e1f2a3
Create Date: 2026-06-01 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "h9d0e1f2a3b4"
down_revision: str | None = "g8c9d0e1f2a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("locations", sa.Column("geocode_source", sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_column("locations", "geocode_source")
