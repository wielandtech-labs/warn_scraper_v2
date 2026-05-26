"""Widen VARCHAR columns that overflow on real-world data.

closure_type VARCHAR(32) → Text  (some states use long strings like
  "Plant Closing/Mass Layoff (Combined)" which is >32 chars).

locations.city / locations.county VARCHAR(128) → Text  (some states
  pack multiple cities into one notice row, e.g. WI, IN).

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-26 00:01:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("notices", "closure_type",
                    existing_type=sa.String(32),
                    type_=sa.Text(),
                    existing_nullable=True)
    op.alter_column("locations", "city",
                    existing_type=sa.String(128),
                    type_=sa.Text(),
                    existing_nullable=True)
    op.alter_column("locations", "county",
                    existing_type=sa.String(128),
                    type_=sa.Text(),
                    existing_nullable=True)


def downgrade() -> None:
    op.alter_column("locations", "county",
                    existing_type=sa.Text(),
                    type_=sa.String(128),
                    existing_nullable=True)
    op.alter_column("locations", "city",
                    existing_type=sa.Text(),
                    type_=sa.String(128),
                    existing_nullable=True)
    op.alter_column("notices", "closure_type",
                    existing_type=sa.Text(),
                    type_=sa.String(32),
                    existing_nullable=True)
