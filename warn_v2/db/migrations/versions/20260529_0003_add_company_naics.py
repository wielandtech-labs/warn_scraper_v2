"""Add naics_code and naics_desc columns to companies.

Additive migration — both columns are nullable, no data risk.
Populated by the enrichment cascade (provider plugin or EDGAR crosswalk).

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-05-29 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("naics_code", sa.String(8), nullable=True))
    op.add_column("companies", sa.Column("naics_desc", sa.String(256), nullable=True))


def downgrade() -> None:
    op.drop_column("companies", "naics_desc")
    op.drop_column("companies", "naics_code")
